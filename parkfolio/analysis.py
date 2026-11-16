from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .model import MissingReference, month, require_text
from .store import Store


class Analysis:
    def __init__(self, store: Store):
        self.store = store

    def reading_funnel(self, period: str, store_id: str) -> dict:
        period = month(period)
        store_id = require_text(store_id, "store_id")
        with self.store.read() as conn:
            if not conn.execute("SELECT 1 FROM stores WHERE store_id=?", (store_id,)).fetchone():
                raise MissingReference("store does not exist")
            visits = [dict(row) for row in conn.execute(
                "SELECT visit_id,visitor_id,space_id,opened_at FROM visits "
                "WHERE store_id=? AND substr(opened_at,1,7)=? ORDER BY opened_at,visit_id",
                (store_id, period))]
            visit_ids = {row["visit_id"] for row in visits}
            readings = {row[0] for row in conn.execute(
                "SELECT DISTINCT r.visit_id FROM readings r JOIN visits v USING(visit_id) "
                "WHERE v.store_id=? AND substr(r.occurred_at,1,7)=?", (store_id, period))} & visit_ids
            attended = {row[0] for row in conn.execute(
                "SELECT DISTINCT a.visit_id FROM attendance a JOIN programs p USING(program_id) "
                "WHERE p.store_id=? AND substr(a.occurred_at,1,7)=?", (store_id, period))} & visit_ids
            bought_books = {row[0] for row in conn.execute(
                "SELECT DISTINCT visit_id FROM orders WHERE store_id=? AND category='book' "
                "AND substr(occurred_at,1,7)=? AND visit_id IS NOT NULL", (store_id, period))} & visit_ids
            catered = {row[0] for row in conn.execute(
                "SELECT DISTINCT visit_id FROM orders WHERE store_id=? AND category IN ('food','drink') "
                "AND substr(occurred_at,1,7)=? AND visit_id IS NOT NULL", (store_id, period))} & visit_ids
            return {
                "month": period, "store_id": store_id, "visits": len(visit_ids),
                "unique_visitors": len({row["visitor_id"] for row in visits}),
                "readers": len(readings), "program_visits": len(attended),
                "book_buyers": len(bought_books), "catering_visits": len(catered),
                "read_and_cater": len(readings & catered),
                "cater_without_read": len(catered - readings),
                "read_without_cater": len(readings - catered),
                "reading_visit_ids": sorted(readings),
                "catering_visit_ids": sorted(catered),
            }

    def topic_mix(self, period: str, store_id: str) -> list[dict]:
        period = month(period)
        with self.store.read() as conn:
            data = defaultdict(lambda: {"minutes": 0, "visits": set(), "books": set(), "event_ids": set()})
            rows = conn.execute(
                "SELECT b.topic,r.minutes,r.visit_id,r.book_id,r.event_id FROM readings r "
                "JOIN visits v USING(visit_id) JOIN books b USING(book_id) "
                "WHERE v.store_id=? AND substr(r.occurred_at,1,7)=?", (store_id, period))
            for row in rows:
                item = data[row["topic"]]
                item["minutes"] += row["minutes"]
                item["visits"].add(row["visit_id"])
                item["books"].add(row["book_id"])
                item["event_ids"].add(row["event_id"])
            return [{"topic": topic, "minutes": value["minutes"],
                     "visits": len(value["visits"]), "books": len(value["books"]),
                     "source_event_ids": sorted(value["event_ids"])}
                    for topic, value in sorted(data.items())]

    def space_use(self, period: str, store_id: str) -> list[dict]:
        period = month(period)
        with self.store.read() as conn:
            rows = conn.execute(
                "SELECT s.space_id,s.version,s.kind,s.capacity,count(DISTINCT v.visit_id) AS visits,"
                "coalesce(sum(r.minutes),0) AS reading_minutes "
                "FROM spaces s LEFT JOIN visits v ON v.space_id=s.space_id AND v.space_version=s.version "
                "AND substr(v.opened_at,1,7)=? LEFT JOIN readings r ON r.visit_id=v.visit_id "
                "WHERE s.store_id=? GROUP BY s.space_id,s.version ORDER BY s.space_id,s.version",
                (period, store_id))
            return [dict(row) for row in rows]

    def revenue_bridge(self, period: str, store_id: str) -> dict:
        period = month(period)
        categories = {key: {"gross": Decimal("0"), "refunds": Decimal("0"), "orders": 0}
                      for key in ("book", "food", "drink")}
        with self.store.read() as conn:
            for row in conn.execute("SELECT category,amount FROM orders WHERE store_id=? "
                                    "AND substr(occurred_at,1,7)=?", (store_id, period)):
                entry = categories[row["category"]]
                entry["gross"] += Decimal(row["amount"])
                entry["orders"] += 1
            for row in conn.execute(
                "SELECT o.category,f.amount FROM refunds f JOIN orders o USING(order_id) "
                "WHERE o.store_id=? AND substr(f.occurred_at,1,7)=?", (store_id, period)):
                categories[row["category"]]["refunds"] += Decimal(row["amount"])
        formatted = {key: {"orders": val["orders"], "gross": format(val["gross"], ".2f"),
                           "refunds": format(val["refunds"], ".2f"),
                           "net": format(val["gross"] - val["refunds"], ".2f")}
                     for key, val in categories.items()}
        return {"month": period, "store_id": store_id, "categories": formatted,
                "total_net": format(sum((val["gross"] - val["refunds"] for val in categories.values()),
                                        Decimal("0")), ".2f")}
