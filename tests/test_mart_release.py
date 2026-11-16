from parkfolio.model import Conflict, MissingReference
from tests.common import Case, event


class MartTests(Case):
    def test_visit_and_reading_not_double_counted(self):
        self.open()
        self.read("r1", duration=20)
        self.read("r2", book="B2", duration=15, time="10:30:00")
        row = self.service.mart.period("2026-07")["stores"][0]
        self.assertEqual(row["visits"], 1)
        self.assertEqual(row["reading_visits"], 1)
        self.assertEqual(row["reading_minutes"], 35)
        self.assertEqual(row["reading_by_topic"], {"fiction": 20, "nature": 15})

    def test_program_and_retail_are_distinct(self):
        self.open()
        self.attend()
        self.order("food", "food", "8.00")
        row = self.service.mart.period("2026-07")["stores"][0]
        self.assertEqual(row["programs"], 1)
        self.assertEqual(row["attendances"], 1)
        self.assertEqual(row["food_revenue"], "8.00")
        self.assertEqual(row["book_revenue"], "0.00")

    def test_quality_blocks_quarantined_event(self):
        pending = self.read()
        self.assertEqual(pending["status"], "quarantined")
        quality = self.service.quality.period("2026-07")
        self.assertFalse(quality["ready"])
        self.assertEqual(quality["issues"], ["quarantined events"])
        with self.assertRaises(Conflict):
            self.service.releases.publish("july", "2026-07",
                                          self.service.releases.preview("2026-07")["fingerprint"])

    def test_quarantine_retry_restores_publishability(self):
        pending = self.read()
        self.open()
        self.service.events.retry(pending["event_id"])
        self.assertTrue(self.service.releases.preview("2026-07")["ready"])

    def test_quality_source_health_counts_status(self):
        self.read()
        groups = {row["name"]: row for row in self.service.quality.source_health()}
        self.assertEqual(groups["shelf"]["received"], 1)
        self.assertEqual(groups["shelf"]["quarantined"], 1)

    def test_topic_mix_has_business_lineage(self):
        self.open()
        reading = self.read()
        topic = self.service.analysis.topic_mix("2026-07", "S1")[0]
        self.assertEqual(topic["topic"], "fiction")
        self.assertEqual(topic["source_event_ids"], [reading["event_id"]])

    def test_funnel_separates_catering_from_reading(self):
        self.open()
        self.open("V2", "B")
        self.read()
        self.order("O1", "drink", "4.00", "V2")
        funnel = self.service.analysis.reading_funnel("2026-07", "S1")
        self.assertEqual(funnel["visits"], 2)
        self.assertEqual(funnel["readers"], 1)
        self.assertEqual(funnel["cater_without_read"], 1)
        self.assertEqual(funnel["read_and_cater"], 0)

    def test_space_use_reports_reading_minutes(self):
        self.open()
        self.read(duration=25)
        rows = self.service.analysis.space_use("2026-07", "S1")
        reading = next(row for row in rows if row["space_id"] == "R1")
        self.assertEqual(reading["visits"], 1)
        self.assertEqual(reading["reading_minutes"], 25)

    def test_daily_occupancy(self):
        self.open()
        self.read()
        self.attend()
        row = self.service.consistency.occupancy_by_day("S1", "2026-07")[0]
        self.assertEqual(row["visits"], 1)
        self.assertEqual(row["reading_minutes"], 20)
        self.assertEqual(row["attended_programs"], 1)

    def test_daily_receipts_net(self):
        self.open()
        self.order()
        self.refund()
        row = self.service.consistency.receipts_by_day("S1", "2026-07")[0]
        self.assertEqual(row["book"], "11.00")
        self.assertEqual(len(row["source_event_ids"]), 2)

    def test_consistency_check_store(self):
        self.open()
        self.read()
        check = self.service.consistency.check_store("S1", "2026-07")
        self.assertTrue(check["ready"])
        self.assertEqual(check["observations"][0]["reading_minutes"], 20)

    def test_csv_export_contains_lineage(self):
        self.open()
        text = self.service.exports.month_csv("2026-07")
        self.assertIn("source_event_ids", text)
        self.assertIn("Garden Books", text)

    def test_explain_reports_unresolved(self):
        self.read()
        explained = self.service.exports.explain("2026-07")
        self.assertFalse(explained["ready"])
        self.assertIn("unresolved source dependencies remain", explained["explanations"])


class ReleaseTests(Case):
    def test_freeze_and_same_name_idempotence(self):
        self.open()
        self.read()
        preview = self.service.releases.preview("2026-07")
        first = self.service.releases.publish("july", "2026-07", preview["fingerprint"])
        second = self.service.releases.publish("july", "2026-07", preview["fingerprint"])
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(self.service.releases.list()), 1)

    def test_stale_fingerprint_rejected(self):
        self.open()
        old = self.service.releases.preview("2026-07")
        self.read()
        with self.assertRaises(Conflict):
            self.service.releases.publish("july", "2026-07", old["fingerprint"])

    def test_historical_release_unchanged_after_more_reading(self):
        self.open()
        self.read()
        original = self.service.releases.preview("2026-07")
        self.service.releases.publish("july", "2026-07", original["fingerprint"])
        self.read("r2", duration=10, time="10:25:00")
        old = self.service.releases.get("july")
        self.assertEqual(old["snapshot"]["stores"][0]["reading_minutes"], 20)
        self.assertEqual(self.service.mart.period("2026-07")["stores"][0]["reading_minutes"], 30)
        self.assertEqual(len(self.service.compare.release_to_current("july")["changed_stores"]), 1)

    def test_same_release_name_different_content_conflicts(self):
        self.open()
        old = self.service.releases.preview("2026-07")
        self.service.releases.publish("july", "2026-07", old["fingerprint"])
        self.read()
        new = self.service.releases.preview("2026-07")
        with self.assertRaises(Conflict):
            self.service.releases.publish("july", "2026-07", new["fingerprint"])

    def test_release_source_lineage(self):
        opened = self.open()
        preview = self.service.releases.preview("2026-07")
        self.service.releases.publish("july", "2026-07", preview["fingerprint"])
        result = self.service.audit.release_source("july", opened["event_id"])
        self.assertEqual(result["included_stores"], ["S1"])
        self.assertEqual(result["source"]["kind"], "visit_open")

    def test_two_release_comparison(self):
        self.open()
        first = self.service.releases.preview("2026-07")
        self.service.releases.publish("first", "2026-07", first["fingerprint"])
        self.read()
        second = self.service.releases.preview("2026-07")
        self.service.releases.publish("second", "2026-07", second["fingerprint"])
        diff = self.service.compare.release_pair("first", "second")
        self.assertEqual(diff["changed_store_ids"], ["S1"])

    def test_unknown_release_rejected(self):
        with self.assertRaises(MissingReference):
            self.service.releases.get("missing")

    def test_month_comparison_shows_reading_delta(self):
        self.open()
        self.read()
        comparison = self.service.compare.months("S1", "2026-06", "2026-07")
        self.assertEqual(comparison["deltas"]["reading_minutes"], 20)
