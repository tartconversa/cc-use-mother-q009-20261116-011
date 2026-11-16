from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .model import month
from .quality import Quality
from .store import Store


class Mart:
    def __init__(self, store: Store, quality: Quality):
        self.store = store
        self.quality = quality

    def period(self, period: str) -> dict:
        period = month(period)
        quality = self.quality.period(period)
        with self.store.read() as conn:
            stores = [dict(row) for row in conn.execute("SELECT * FROM stores ORDER BY store_id")]
            result = []
            for store in stores:
                sid = store["store_id"]
                visits = [dict(row) for row in conn.execute(
                    "SELECT * FROM visits WHERE store_id=? AND substr(opened_at,1,7)=? ORDER BY visit_id",
                    (sid, period))]
                visits_ids = {x["visit_id"] for x in visits}
                reading_rows = [dict(row) for row in conn.execute(
                    "SELECT r.*,b.topic FROM readings r JOIN visits v USING(visit_id) JOIN books b USING(book_id) "
                    "WHERE v.store_id=? AND substr(r.occurred_at,1,7)=? ORDER BY r.event_id", (sid, period))]
                orders = [dict(row) for row in conn.execute(
                    "SELECT * FROM orders WHERE store_id=? AND substr(occurred_at,1,7)=? ORDER BY order_id", (sid, period))]
                refunds = [dict(row) for row in conn.execute(
                    "SELECT f.* FROM refunds f JOIN orders o USING(order_id) "
                    "WHERE o.store_id=? AND substr(f.occurred_at,1,7)=? ORDER BY f.refund_id", (sid, period))]
                attended = [dict(row) for row in conn.execute(
                    "SELECT a.* FROM attendance a JOIN programs p USING(program_id) "
                    "WHERE p.store_id=? AND substr(a.occurred_at,1,7)=? ORDER BY a.event_id", (sid, period))]
                programs = [dict(row) for row in conn.execute(
                    "SELECT * FROM programs WHERE store_id=? AND substr(starts_at,1,7)=?", (sid, period))]
                gross = defaultdict(lambda: Decimal("0"))
                for order in orders:
                    gross[order["category"]] += Decimal(order["amount"])
                order_categories = {row["order_id"]: row["category"] for row in conn.execute(
                    "SELECT order_id,category FROM orders WHERE store_id=?", (sid,))}
                for refund in refunds:
                    gross[order_categories[refund["order_id"]]] -= Decimal(refund["amount"])
                topics = defaultdict(int)
                spaces = defaultdict(int)
                for reading in reading_rows:
                    topics[reading["topic"]] += reading["minutes"]
                    spaces[reading["space_id"]] += reading["minutes"]
                lineage_ids = sorted({x["open_event"] for x in visits}
                                     | {x["close_event"] for x in visits if x["close_event"] is not None}
                                     | {x["event_id"] for x in reading_rows + orders + refunds + attended})
                result.append({
                    "store_id": sid, "park": store["park"], "store_name": store["name"],
                    "visits": len(visits), "unique_visitors": len({x["visitor_id"] for x in visits}),
                    "completed_visits": sum(x["closed_at"] is not None for x in visits),
                    "reading_visits": len({x["visit_id"] for x in reading_rows}),
                    "reading_minutes": sum(x["minutes"] for x in reading_rows),
                    "reading_by_topic": dict(sorted(topics.items())),
                    "reading_by_space": dict(sorted(spaces.items())),
                    "book_revenue": format(gross["book"], ".2f"),
                    "food_revenue": format(gross["food"], ".2f"),
                    "drink_revenue": format(gross["drink"], ".2f"),
                    "programs": len(programs), "attendances": len(attended),
                    "attending_visits": len({x["visit_id"] for x in attended}),
                    "reading_to_visit_rate": str(round(len({x["visit_id"] for x in reading_rows}) / len(visits), 4)) if visits else "0",
                    "source_event_ids": lineage_ids,
                })
            return {"month": period, "quality": quality, "stores": result}

    def store_month(self, store_id: str, period: str) -> dict:
        report = self.period(period)
        for store in report["stores"]:
            if store["store_id"] == store_id:
                return {"month": period, "quality": report["quality"], "store": store}
        from .model import MissingReference
        raise MissingReference("store does not exist")
