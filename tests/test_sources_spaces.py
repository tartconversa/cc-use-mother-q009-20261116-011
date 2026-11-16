from unittest import TestCase

from parkfolio.model import Conflict, DomainError, MissingReference, Event, decimal, money, month, timestamp
from tests.common import Case, event


class ModelTests(TestCase):
    def test_timestamp_normalizes_offset(self):
        self.assertEqual(timestamp("2026-07-12T18:00:00+08:00"), "2026-07-12T10:00:00+00:00")

    def test_timestamp_rejects_naive(self):
        with self.assertRaises(DomainError):
            timestamp("2026-07-12T10:00:00")

    def test_timestamp_rejects_garbage(self):
        with self.assertRaises(DomainError):
            timestamp("yesterday")

    def test_month_validates_calendar(self):
        self.assertEqual(month("2026-07"), "2026-07")
        for invalid in ("2026-00", "2026-13", "26-07", "2026-7"):
            with self.subTest(invalid=invalid), self.assertRaises(DomainError):
                month(invalid)

    def test_money_preserves_cents(self):
        self.assertEqual(money("12.5"), "12.50")
        self.assertEqual(money("0"), "0.00")

    def test_money_rejects_more_than_cents(self):
        with self.assertRaises(DomainError):
            money("1.001")

    def test_decimal_rejects_nan_and_negative(self):
        for value in ("NaN", "Infinity", "-1", True):
            with self.subTest(value=value), self.assertRaises(DomainError):
                decimal(value, "weight")

    def test_event_requires_payload_and_known_kind(self):
        with self.assertRaises(DomainError):
            Event.parse({"kind": "reading", "payload": "bad"})
        with self.assertRaises(DomainError):
            Event.parse(event("door", "x", "unknown", "10:00:00", {}))


class SourceAndSpaceTests(Case):
    def test_store_registration_is_idempotent(self):
        same = self.service.spaces.put_store("S1", "Garden Books", "Lake Park")
        self.assertEqual(same["park"], "Lake Park")
        self.assertEqual(len(self.service.spaces.list_stores()), 1)

    def test_store_conflict_is_rejected(self):
        with self.assertRaises(Conflict):
            self.service.spaces.put_store("S1", "Different", "Lake Park")

    def test_space_requires_store(self):
        with self.assertRaises(MissingReference):
            self.service.spaces.put_space("X", "missing", "reading", 3, "2026-07-01T00:00:00Z")

    def test_space_rejects_overlap(self):
        with self.assertRaises(Conflict):
            self.service.spaces.put_space("R1", "S1", "mixed", 3, "2026-07-02T00:00:00Z")

    def test_space_accepts_adjacent_versions(self):
        self.service.spaces.put_space("X", "S1", "reading", 2,
                                      "2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z")
        new = self.service.spaces.put_space("X", "S1", "mixed", 3, "2026-07-05T00:00:00Z")
        self.assertEqual(new["version"], 2)
        with self.service.store.read() as conn:
            resolved = self.service.spaces.resolve(conn, "X", "2026-07-05T00:00:00+00:00")
        self.assertEqual(resolved["kind"], "mixed")

    def test_space_rejects_invalid_capacity_and_interval(self):
        with self.assertRaises(DomainError):
            self.service.spaces.put_space("X", "S1", "reading", 0, "2026-07-01T00:00:00Z")
        with self.assertRaises(DomainError):
            self.service.spaces.put_space("X", "S1", "reading", 1,
                                          "2026-07-10T00:00:00Z", "2026-07-01T00:00:00Z")

    def test_source_disable_blocks_new_events(self):
        self.service.events.source("door", False)
        with self.assertRaises(MissingReference):
            self.open()

    def test_source_reenable(self):
        self.service.events.source("door", False)
        self.service.events.source("door", True)
        self.assertEqual(self.open()["status"], "applied")

    def test_dining_space_cannot_start_reading_visit(self):
        with self.assertRaises(Conflict):
            self.open(space="D1")

    def test_catalog_conflicting_identity(self):
        with self.assertRaises(Conflict):
            self.service.catalog.put("B1", "Changed", "fiction", "S1")

    def test_catalog_active_state(self):
        self.service.catalog.set_active("B1", False)
        self.assertEqual(len(self.service.catalog.list(active_only=True)), 1)
        self.open()
        pending = self.read()
        self.assertEqual(pending["status"], "quarantined")
        self.assertIn("active catalog", pending["reason"])

    def test_program_rejects_dining_and_over_capacity(self):
        with self.assertRaises(Conflict):
            self.service.programs.put("X", "S1", "D1", "2026-07-12T10:00:00Z",
                                      "2026-07-12T11:00:00Z", "Dinner", 2)
        with self.assertRaises(Conflict):
            self.service.programs.put("X", "S1", "R1", "2026-07-12T10:00:00Z",
                                      "2026-07-12T11:00:00Z", "Reading", 3)

    def test_program_registration_is_idempotent(self):
        same = self.service.programs.put("P1", "S1", "R1", "2026-07-12T10:00:00Z",
                                         "2026-07-12T11:00:00Z", "Read Together", 2)
        self.assertEqual(same["program_id"], "P1")
        self.assertEqual(len(self.service.programs.list("S1")), 1)
