from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .model import MissingReference, month, require_text
from .store import Store


class Consistency:
    def __init__(self, store: Store):
        self.store = store

    def check_store(self, store_id: str, period: str) -> dict:
        store_id = require_text(store_id, "store_id")
        period = month(period)
        with self.store.read() as conn:
            if not conn.execute("SELECT 1 FROM stores WHERE store_id=?", (store_id,)).fetchone():
                raise MissingReference("store does not exist")
            problems = []
            observations = []
            for visit in conn.execute("SELECT * FROM visits WHERE store_id=? AND substr(opened_at,1,7)=?",
                                      (store_id, period)):
                readings = [dict(x) for x in conn.execute(
                    "SELECT * FROM readings WHERE visit_id=?", (visit["visit_id"],))]
                for reading in readings:
                    if reading["occurred_at"] < visit["opened_at"]:
                        problems.append({"kind": "reading_before_visit", "visit_id": visit["visit_id"]})
                    if visit["closed_at"] and reading["occurred_at"] >= visit["closed_at"]:
                        problems.append({"kind": "reading_after_visit", "visit_id": visit["visit_id"]})
                    if reading["space_version"] != visit["space_version"]:
                        problems.append({"kind": "space_version_mismatch", "visit_id": visit["visit_id"]})
                observations.append({"visit_id": visit["visit_id"], "reading_events": len(readings),
                                     "reading_minutes": sum(x["minutes"] for x in readings),
                                     "closed": visit["closed_at"] is not None})
            for order in conn.execute("SELECT * FROM orders WHERE store_id=? AND substr(occurred_at,1,7)=?",
                                      (store_id, period)):
                refunded = sum((Decimal(x[0]) for x in conn.execute(
                    "SELECT amount FROM refunds WHERE order_id=?", (order["order_id"],))), Decimal("0"))
                if refunded > Decimal(order["amount"]):
                    problems.append({"kind": "over_refunded", "order_id": order["order_id"]})
                if order["visit_id"]:
                    visit = conn.execute("SELECT store_id FROM visits WHERE visit_id=?",
                                         (order["visit_id"],)).fetchone()
                    if not visit or visit["store_id"] != store_id:
                        problems.append({"kind": "order_visit_mismatch", "order_id": order["order_id"]})
            for program in conn.execute("SELECT * FROM programs WHERE store_id=? AND substr(starts_at,1,7)=?",
                                        (store_id, period)):
                attending = conn.execute("SELECT count(*) FROM attendance WHERE program_id=?",
                                         (program["program_id"],)).fetchone()[0]
                if attending > program["capacity"]:
                    problems.append({"kind": "program_over_capacity", "program_id": program["program_id"]})
            return {"store_id": store_id, "month": period, "ready": not problems,
                    "problems": problems, "observations": observations}

    def receipts_by_day(self, store_id: str, period: str) -> list[dict]:
        period = month(period)
        amounts = defaultdict(lambda: {"book": Decimal("0"), "food": Decimal("0"),
                                       "drink": Decimal("0"), "events": set()})
        with self.store.read() as conn:
            for order in conn.execute("SELECT order_id,event_id,category,amount,occurred_at FROM orders "
                                      "WHERE store_id=? AND substr(occurred_at,1,7)=?", (store_id, period)):
                row = amounts[order["occurred_at"][:10]]
                row[order["category"]] += Decimal(order["amount"])
                row["events"].add(order["event_id"])
            for refund in conn.execute(
                "SELECT f.event_id,f.amount,f.occurred_at,o.category FROM refunds f "
                "JOIN orders o USING(order_id) WHERE o.store_id=? AND substr(f.occurred_at,1,7)=?",
                (store_id, period)):
                row = amounts[refund["occurred_at"][:10]]
                row[refund["category"]] -= Decimal(refund["amount"])
                row["events"].add(refund["event_id"])
        return [{"day": day, "book": format(row["book"], ".2f"),
                 "food": format(row["food"], ".2f"), "drink": format(row["drink"], ".2f"),
                 "source_event_ids": sorted(row["events"])} for day, row in sorted(amounts.items())]

    def occupancy_by_day(self, store_id: str, period: str) -> list[dict]:
        period = month(period)
        with self.store.read() as conn:
            daily = defaultdict(lambda: {"visits": set(), "visitors": set(),
                                         "readings": 0, "minutes": 0, "programs": set()})
            for visit in conn.execute("SELECT visit_id,visitor_id,opened_at FROM visits WHERE store_id=? "
                                      "AND substr(opened_at,1,7)=?", (store_id, period)):
                day = visit["opened_at"][:10]
                daily[day]["visits"].add(visit["visit_id"])
                daily[day]["visitors"].add(visit["visitor_id"])
            for reading in conn.execute("SELECT r.occurred_at,r.minutes FROM readings r "
                                        "JOIN visits v USING(visit_id) WHERE v.store_id=? "
                                        "AND substr(r.occurred_at,1,7)=?", (store_id, period)):
                item = daily[reading["occurred_at"][:10]]
                item["readings"] += 1
                item["minutes"] += reading["minutes"]
            for attended in conn.execute("SELECT a.program_id,a.occurred_at FROM attendance a "
                                         "JOIN programs p USING(program_id) WHERE p.store_id=? "
                                         "AND substr(a.occurred_at,1,7)=?", (store_id, period)):
                daily[attended["occurred_at"][:10]]["programs"].add(attended["program_id"])
        return [{"day": day, "visits": len(row["visits"]),
                 "visitors": len(row["visitors"]), "reading_events": row["readings"],
                 "reading_minutes": row["minutes"], "attended_programs": len(row["programs"])}
                for day, row in sorted(daily.items())]
