import tempfile
from pathlib import Path
from unittest import TestCase

from parkfolio import Parkfolio


DAY = "2026-07-12"


def event(source, external_id, kind, time, payload):
    at = f"{DAY}T{time}Z"
    return {"source": source, "external_id": external_id, "kind": kind,
            "occurred_at": at, "received_at": at, "payload": payload}


class Case(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Parkfolio(Path(self.temp.name) / "parkfolio.sqlite3")
        for name in ("door", "shelf", "cashier", "program"):
            self.service.events.source(name)
        self.service.spaces.put_store("S1", "Garden Books", "Lake Park")
        self.service.spaces.put_space("R1", "S1", "reading", 2, "2026-07-01T00:00:00Z")
        self.service.spaces.put_space("D1", "S1", "dining", 4, "2026-07-01T00:00:00Z")
        self.service.catalog.put("B1", "The Lake", "fiction", "S1")
        self.service.catalog.put("B2", "Trees", "nature", "S1")
        self.service.programs.put("P1", "S1", "R1", f"{DAY}T10:00:00Z",
                                  f"{DAY}T11:00:00Z", "Read Together", 2)

    def open(self, visit="V1", visitor="A", time="10:00:00", space="R1"):
        return self.service.events.accept(event("door", "open-" + visit, "visit_open", time,
            {"visit_id": visit, "visitor_id": visitor, "store_id": "S1", "space_id": space}))

    def close(self, visit="V1", time="11:30:00"):
        return self.service.events.accept(event("door", "close-" + visit, "visit_close", time,
            {"visit_id": visit}))

    def read(self, event_id="reading-1", visit="V1", book="B1", duration=20, time="10:10:00"):
        return self.service.events.accept(event("shelf", event_id, "reading", time,
            {"visit_id": visit, "book_id": book, "minutes": duration}))

    def order(self, order_id="O1", category="book", amount="15.00", visit="V1", time="10:20:00"):
        payload = {"order_id": order_id, "store_id": "S1", "category": category, "amount": amount}
        if visit is not None:
            payload["visit_id"] = visit
        if category == "book":
            payload["book_id"] = "B1"
        return self.service.events.accept(event("cashier", "order-" + order_id, "order", time, payload))

    def attend(self, event_id="attendance-1", visit="V1", visitor="A", time="10:15:00"):
        return self.service.events.accept(event("program", event_id, "attendance", time,
            {"visit_id": visit, "visitor_id": visitor, "program_id": "P1"}))

    def refund(self, refund_id="F1", order="O1", amount="4.00", time="10:40:00"):
        return self.service.events.accept(event("cashier", "refund-" + refund_id, "refund", time,
            {"refund_id": refund_id, "order_id": order, "amount": amount}))
