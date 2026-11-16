from parkfolio.model import Conflict, DomainError, MissingReference
from tests.common import Case, event


class JourneyTests(Case):
    def test_open_close_and_read(self):
        opened = self.open()
        self.assertEqual(opened["status"], "applied")
        reading = self.read()
        self.assertEqual(reading["projected"]["minutes"], 20)
        self.assertEqual(self.close()["status"], "applied")
        self.assertEqual(self.service.mart.period("2026-07")["stores"][0]["reading_minutes"], 20)

    def test_read_before_open_is_quarantined_then_retried(self):
        pending = self.read()
        self.assertEqual(pending["status"], "quarantined")
        self.assertIn("not opened", pending["reason"])
        self.open()
        retried = self.service.events.retry(pending["event_id"])
        self.assertEqual(retried["status"], "applied")
        self.assertEqual(self.service.overview()["readings"], 1)

    def test_retry_without_reference_stays_quarantined(self):
        pending = self.read()
        result = self.service.events.retry(pending["event_id"])
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(self.service.overview()["quarantined"], 1)

    def test_duplicate_open_does_not_duplicate_visit(self):
        self.open()
        duplicate = self.open()
        self.assertFalse(duplicate["created"])
        self.assertEqual(self.service.overview()["visits"], 1)

    def test_different_body_same_source_id_conflicts(self):
        self.open()
        with self.assertRaises(Conflict):
            self.service.events.accept(event("door", "open-V1", "visit_open", "10:01:00",
                {"visit_id": "V1", "visitor_id": "A", "store_id": "S1", "space_id": "R1"}))

    def test_overlap_same_visitor_conflicts(self):
        self.open()
        with self.assertRaises(Conflict):
            self.open("V2", "A", "10:20:00")

    def test_different_visitors_can_share_space(self):
        self.open()
        second = self.open("V2", "B", "10:20:00")
        self.assertEqual(second["status"], "applied")
        self.assertEqual(self.service.mart.period("2026-07")["stores"][0]["unique_visitors"], 2)

    def test_close_before_open_quarantines_missing_visit(self):
        pending = self.close()
        self.assertEqual(pending["status"], "quarantined")
        self.open()
        self.assertEqual(self.service.events.retry(pending["event_id"])["status"], "applied")

    def test_read_outside_closed_visit_rejected(self):
        self.open()
        self.close(time="10:20:00")
        with self.assertRaises(Conflict):
            self.read(time="10:30:00")

    def test_read_at_close_boundary_rejected(self):
        self.open()
        self.close(time="10:20:00")
        with self.assertRaises(Conflict):
            self.read(time="10:20:00")

    def test_read_unknown_book_quarantined_then_retried(self):
        self.open()
        pending = self.read(book="B3")
        self.assertEqual(pending["status"], "quarantined")
        self.service.catalog.put("B3", "Water", "nature", "S1")
        self.assertEqual(self.service.events.retry(pending["event_id"])["status"], "applied")

    def test_invalid_reading_duration_rejected_without_landing(self):
        self.open()
        with self.assertRaises(DomainError):
            self.read(duration=0)
        self.assertEqual(self.service.overview()["events"], 1)

    def test_visit_audit_contains_all_raw_events(self):
        self.open()
        self.read()
        self.close()
        lineage = self.service.audit.visit("V1")
        self.assertEqual(len(lineage["source_events"]), 3)
        self.assertEqual(lineage["readings"][0]["title"], "The Lake")

    def test_quality_reports_open_visits_but_does_not_block(self):
        self.open()
        quality = self.service.quality.period("2026-07")
        self.assertEqual(len(quality["open_visits"]), 1)
        self.assertTrue(quality["ready"])

    def test_unknown_audit_visit_raises(self):
        with self.assertRaises(MissingReference):
            self.service.audit.visit("absent")

    def test_close_is_idempotent_when_source_replayed(self):
        self.open()
        self.close()
        replay = self.close()
        self.assertFalse(replay["created"])
        self.assertEqual(self.service.overview()["events"], 2)
