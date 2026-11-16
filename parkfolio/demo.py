from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .service import Parkfolio


def event(source: str, external_id: str, kind: str, when: str, payload: dict) -> dict:
    return {"source": source, "external_id": external_id, "kind": kind,
            "occurred_at": when, "received_at": when, "payload": payload}


def run() -> dict:
    with tempfile.TemporaryDirectory() as root:
        service = Parkfolio(Path(root) / "demo.sqlite3")
        for source in ("door", "shelf", "cashier", "program"):
            service.events.source(source)
        service.spaces.put_store("P1", "Park Reading House", "West Park")
        service.spaces.put_space("R1", "P1", "reading", 12, "2026-07-01T00:00:00Z")
        service.spaces.put_space("D1", "P1", "dining", 8, "2026-07-01T00:00:00Z")
        service.catalog.put("B1", "Poetry by the Lake", "poetry", "P1")
        service.programs.put("E1", "P1", "R1", "2026-07-12T10:00:00Z",
                             "2026-07-12T11:00:00Z", "Poetry Hour", 12)
        pending = service.events.accept(event("shelf", "read-1", "reading",
            "2026-07-12T10:15:00Z", {"visit_id": "V1", "book_id": "B1", "minutes": 30}))
        assert pending["status"] == "quarantined"
        opened = service.events.accept(event("door", "open-1", "visit_open",
            "2026-07-12T10:00:00Z", {"visit_id": "V1", "visitor_id": "X1",
                                      "store_id": "P1", "space_id": "R1"}))
        assert opened["status"] == "applied"
        assert service.events.retry(pending["event_id"])["status"] == "applied"
        assert service.events.accept(event("program", "att-1", "attendance",
            "2026-07-12T10:20:00Z", {"program_id": "E1", "visit_id": "V1",
                                      "visitor_id": "X1"}))["status"] == "applied"
        assert service.events.accept(event("cashier", "order-1", "order",
            "2026-07-12T10:30:00Z", {"order_id": "O1", "visit_id": "V1",
                                      "store_id": "P1", "category": "drink", "amount": "12.00"}))["status"] == "applied"
        assert service.events.accept(event("door", "close-1", "visit_close",
            "2026-07-12T11:00:00Z", {"visit_id": "V1"}))["status"] == "applied"
        report = service.mart.period("2026-07")
        row = report["stores"][0]
        assert row["visits"] == 1 and row["reading_minutes"] == 30
        assert row["drink_revenue"] == "12.00" and row["attendances"] == 1
        preview = service.releases.preview("2026-07")
        assert preview["ready"]
        release = service.releases.publish("july", "2026-07", preview["fingerprint"])
        assert service.releases.get("july")["snapshot"] == report
        return {"status": "ok", "quality": report["quality"]["ready"],
                "visits": row["visits"], "reading_minutes": row["reading_minutes"],
                "attendances": row["attendances"], "drink_revenue": row["drink_revenue"],
                "release": release["fingerprint"]}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
