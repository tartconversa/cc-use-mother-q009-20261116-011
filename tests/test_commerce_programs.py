from parkfolio.model import Conflict, DomainError, MissingReference
from tests.common import Case, event


class CommerceTests(Case):
    def test_book_order_and_partial_refund(self):
        self.open()
        self.order()
        self.refund()
        detail = self.service.commerce.order_detail("O1")
        self.assertEqual(detail["net_amount"], "11.00")
        self.assertEqual(len(detail["refunds"]), 1)

    def test_food_and_drink_are_separate(self):
        self.open()
        self.order("F", "food", "25.00")
        self.order("D", "drink", "6.00")
        row = self.service.mart.period("2026-07")["stores"][0]
        self.assertEqual(row["book_revenue"], "0.00")
        self.assertEqual(row["food_revenue"], "25.00")
        self.assertEqual(row["drink_revenue"], "6.00")

    def test_order_without_visit_is_allowed(self):
        result = self.order(visit=None)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.service.analysis.reading_funnel("2026-07", "S1")["visits"], 0)

    def test_order_missing_visit_quarantined(self):
        pending = self.order()
        self.assertEqual(pending["status"], "quarantined")
        self.open()
        self.assertEqual(self.service.events.retry(pending["event_id"])["status"], "applied")

    def test_refund_before_order_quarantined(self):
        pending = self.refund()
        self.assertEqual(pending["status"], "quarantined")
        self.open()
        self.order()
        self.assertEqual(self.service.events.retry(pending["event_id"])["status"], "applied")

    def test_refund_cannot_exceed_order(self):
        self.open()
        self.order()
        with self.assertRaises(Conflict):
            self.refund(amount="16.00")
        self.assertEqual(self.service.overview()["refunds"], 0)

    def test_two_refunds_cannot_exceed_order(self):
        self.open()
        self.order()
        self.refund(amount="10.00")
        with self.assertRaises(Conflict):
            self.refund("F2", amount="6.00")

    def test_refund_replay_is_idempotent(self):
        self.open()
        self.order()
        self.refund()
        replay = self.refund()
        self.assertFalse(replay["created"])
        self.assertEqual(self.service.commerce.order_detail("O1")["net_amount"], "11.00")

    def test_invalid_book_order_without_book_id(self):
        self.open()
        with self.assertRaises(DomainError):
            self.service.events.accept(event("cashier", "bad-book", "order", "10:20:00",
                {"order_id": "O1", "store_id": "S1", "category": "book", "amount": "5.00"}))

    def test_invalid_food_order_with_book_id(self):
        with self.assertRaises(DomainError):
            self.service.events.accept(event("cashier", "bad-food", "order", "10:20:00",
                {"order_id": "O1", "store_id": "S1", "category": "food", "amount": "5.00", "book_id": "B1"}))

    def test_negative_or_zero_order_rejected(self):
        self.open()
        for amount in ("-1", "0"):
            with self.subTest(amount=amount), self.assertRaises(DomainError):
                self.order("bad-" + amount, amount=amount)

    def test_refund_revenue_bridge(self):
        self.open()
        self.order()
        self.refund()
        bridge = self.service.analysis.revenue_bridge("2026-07", "S1")
        self.assertEqual(bridge["categories"]["book"]["net"], "11.00")
        self.assertEqual(bridge["total_net"], "11.00")

    def test_unknown_order_detail(self):
        with self.assertRaises(MissingReference):
            self.service.commerce.order_detail("absent")


class ProgramTests(Case):
    def test_attendance_counts_from_matching_visit(self):
        self.open()
        self.attend()
        status = self.service.attendance.status("P1")
        self.assertEqual(status["remaining"], 1)
        self.assertEqual(len(status["attendees"]), 1)

    def test_attendance_requires_visit(self):
        pending = self.attend()
        self.assertEqual(pending["status"], "quarantined")
        self.open()
        self.assertEqual(self.service.events.retry(pending["event_id"])["status"], "applied")

    def test_wrong_visitor_rejected(self):
        self.open()
        with self.assertRaises(Conflict):
            self.attend(visitor="B")

    def test_duplicate_visitor_rejected(self):
        self.open()
        self.attend()
        with self.assertRaises(Conflict):
            self.attend(event_id="attendance-2")

    def test_program_capacity_rejected(self):
        self.open()
        self.open("V2", "B")
        self.open("V3", "C")
        self.attend()
        self.attend("attendance-2", "V2", "B")
        with self.assertRaises(Conflict):
            self.attend("attendance-3", "V3", "C")

    def test_attendance_outside_program_rejected(self):
        self.open()
        with self.assertRaises(DomainError):
            self.attend(time="11:10:00")

    def test_attendance_replay_does_not_use_second_seat(self):
        self.open()
        self.attend()
        self.assertFalse(self.attend()["created"])
        self.assertEqual(self.service.attendance.status("P1")["remaining"], 1)
