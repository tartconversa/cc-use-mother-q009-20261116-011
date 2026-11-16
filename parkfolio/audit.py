from __future__ import annotations

from .model import MissingReference, month, require_text
from .store import Store


class Audit:
    def __init__(self, store: Store):
        self.store = store

    def visit(self, visit_id: str) -> dict:
        visit_id = require_text(visit_id, "visit_id")
        with self.store.read() as conn:
            visit = conn.execute("SELECT * FROM visits WHERE visit_id=?", (visit_id,)).fetchone()
            if not visit:
                raise MissingReference("visit does not exist")
            readings = [dict(x) for x in conn.execute(
                "SELECT r.*,b.title,b.topic FROM readings r JOIN books b USING(book_id) "
                "WHERE visit_id=? ORDER BY occurred_at,event_id", (visit_id,))]
            orders = [dict(x) for x in conn.execute(
                "SELECT * FROM orders WHERE visit_id=? ORDER BY occurred_at,order_id", (visit_id,))]
            refunds = [dict(x) for x in conn.execute(
                "SELECT f.* FROM refunds f JOIN orders o USING(order_id) "
                "WHERE o.visit_id=? ORDER BY f.occurred_at,f.refund_id", (visit_id,))]
            attendance = [dict(x) for x in conn.execute(
                "SELECT * FROM attendance WHERE visit_id=? ORDER BY occurred_at,event_id", (visit_id,))]
            source_ids = {visit["open_event"]}
            if visit["close_event"] is not None:
                source_ids.add(visit["close_event"])
            source_ids |= {x["event_id"] for x in readings + orders + refunds + attendance}
            raw = [dict(conn.execute("SELECT * FROM raw_events WHERE id=?", (i,)).fetchone())
                   for i in sorted(source_ids)]
            return {"visit": dict(visit), "readings": readings, "orders": orders,
                    "refunds": refunds, "attendance": attendance, "source_events": raw}

    def release_source(self, release_name: str, event_id: int) -> dict:
        release_name = require_text(release_name, "release_name")
        with self.store.read() as conn:
            release = conn.execute("SELECT * FROM releases WHERE name=?", (release_name,)).fetchone()
            if not release:
                raise MissingReference("release does not exist")
            import json
            snapshot = json.loads(release["snapshot"])
            locations = [row["store_id"] for row in snapshot["stores"]
                         if event_id in row["source_event_ids"]]
            raw = conn.execute("SELECT source,external_id,kind,occurred_at,digest FROM raw_events "
                               "WHERE id=?", (event_id,)).fetchone()
            return {"release": release_name, "fingerprint": release["fingerprint"],
                    "event_id": event_id, "included_stores": locations,
                    "source": dict(raw) if raw else None}

    def month_sources(self, period: str) -> dict:
        period = month(period)
        with self.store.read() as conn:
            rows = [dict(x) for x in conn.execute(
                "SELECT source,kind,status,count(*) AS count FROM raw_events "
                "WHERE substr(occurred_at,1,7)=? GROUP BY source,kind,status "
                "ORDER BY source,kind,status", (period,))]
            return {"month": period, "groups": rows, "total": sum(x["count"] for x in rows)}
