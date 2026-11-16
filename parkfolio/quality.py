from __future__ import annotations

from decimal import Decimal

from .model import month
from .store import Store


class Quality:
    def __init__(self, store: Store):
        self.store = store

    def period(self, period: str) -> dict:
        period = month(period)
        with self.store.read() as conn:
            quarantined = [dict(row) for row in conn.execute(
                "SELECT id,source,external_id,kind,reason FROM raw_events "
                "WHERE status='quarantined' AND substr(occurred_at,1,7)=? ORDER BY id", (period,))]
            open_visits = [dict(row) for row in conn.execute(
                "SELECT visit_id,store_id,opened_at FROM visits "
                "WHERE closed_at IS NULL AND substr(opened_at,1,7)=? ORDER BY visit_id", (period,))]
            over_refunds = []
            for row in conn.execute("SELECT order_id,amount FROM orders WHERE substr(occurred_at,1,7)=?", (period,)):
                total = sum((Decimal(x[0]) for x in conn.execute(
                    "SELECT amount FROM refunds WHERE order_id=?", (row["order_id"],))), Decimal("0"))
                if total > Decimal(row["amount"]):
                    over_refunds.append(row["order_id"])
            at_capacity = [dict(row) for row in conn.execute(
                "SELECT p.program_id,p.capacity,count(a.event_id) AS attended FROM programs p "
                "LEFT JOIN attendance a ON a.program_id=p.program_id "
                "WHERE substr(p.starts_at,1,7)=? GROUP BY p.program_id HAVING attended>p.capacity", (period,))]
            problems = []
            if quarantined:
                problems.append("quarantined events")
            if over_refunds:
                problems.append("over refunded orders")
            if at_capacity:
                problems.append("over capacity programs")
            return {"month": period, "ready": not problems, "issues": problems,
                    "quarantined": quarantined, "open_visits": open_visits,
                    "over_refunds": over_refunds, "over_capacity": at_capacity}

    def lineage(self, event_id: int) -> dict:
        with self.store.read() as conn:
            raw = conn.execute("SELECT * FROM raw_events WHERE id=?", (event_id,)).fetchone()
            if not raw:
                return {"event_id": event_id, "found": False}
            links = {}
            for table in ("readings", "orders", "refunds", "attendance"):
                key = "event_id"
                rows = [dict(x) for x in conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (event_id,))]
                if rows:
                    links[table] = rows
            for role, key in (("visit_open", "open_event"), ("visit_close", "close_event")):
                rows = [dict(x) for x in conn.execute(f"SELECT * FROM visits WHERE {key}=?", (event_id,))]
                if rows:
                    links[role] = rows
            return {"event_id": event_id, "found": True, "raw": dict(raw), "projections": links}

    def source_health(self) -> list[dict]:
        with self.store.read() as conn:
            return [dict(x) for x in conn.execute(
                "SELECT s.name,s.enabled,count(r.id) AS received,"
                "sum(CASE WHEN r.status='quarantined' THEN 1 ELSE 0 END) AS quarantined "
                "FROM sources s LEFT JOIN raw_events r ON r.source=s.name "
                "GROUP BY s.name,s.enabled ORDER BY s.name")]
