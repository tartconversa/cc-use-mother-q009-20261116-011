from __future__ import annotations

from decimal import Decimal

from .catalog import Catalog
from .journeys import Journeys
from .model import Conflict, DomainError, MissingReference, money, require_text
from .store import Store


class Commerce:
    def __init__(self, store: Store, catalog: Catalog, journeys: Journeys):
        self.store = store
        self.catalog = catalog
        self.journeys = journeys

    def order(self, conn, event_id: int, occurred_at: str, payload: dict) -> dict:
        order_id = require_text(payload.get("order_id"), "order_id")
        store_id = require_text(payload.get("store_id"), "store_id")
        category = payload.get("category")
        if category not in {"book", "food", "drink"}:
            raise DomainError("order category must be book, food or drink")
        amount = money(payload.get("amount"))
        if Decimal(amount) == 0:
            raise DomainError("order amount must be positive")
        visit_id = payload.get("visit_id")
        if visit_id is not None:
            visit_id = require_text(visit_id, "visit_id")
            visit = self.journeys.resolve(conn, visit_id, occurred_at)
            if visit["store_id"] != store_id:
                raise Conflict("order visit belongs to another store")
        book_id = payload.get("book_id")
        if category == "book":
            book_id = require_text(book_id, "book_id")
            self.catalog.resolve(conn, book_id, store_id)
        elif book_id is not None:
            raise DomainError("food and drink orders cannot carry book_id")
        if not conn.execute("SELECT 1 FROM stores WHERE store_id=?", (store_id,)).fetchone():
            raise MissingReference("order store does not exist")
        if conn.execute("SELECT 1 FROM orders WHERE order_id=?", (order_id,)).fetchone():
            raise Conflict("order identity already exists")
        conn.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)", (order_id, event_id, visit_id,
                     store_id, category, book_id, amount, occurred_at))
        return {"order_id": order_id, "store_id": store_id, "category": category,
                "amount": amount, "visit_id": visit_id}

    def refund(self, conn, event_id: int, occurred_at: str, payload: dict) -> dict:
        refund_id = require_text(payload.get("refund_id"), "refund_id")
        order_id = require_text(payload.get("order_id"), "order_id")
        amount = money(payload.get("amount"))
        if Decimal(amount) == 0:
            raise DomainError("refund amount must be positive")
        order = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not order:
            raise MissingReference("original order has not arrived")
        if occurred_at < order["occurred_at"]:
            raise Conflict("refund precedes original order")
        if conn.execute("SELECT 1 FROM refunds WHERE refund_id=?", (refund_id,)).fetchone():
            raise Conflict("refund identity already exists")
        current = sum((Decimal(row[0]) for row in conn.execute(
            "SELECT amount FROM refunds WHERE order_id=?", (order_id,))), Decimal("0"))
        if current + Decimal(amount) > Decimal(order["amount"]):
            raise Conflict("refunds exceed original order")
        conn.execute("INSERT INTO refunds VALUES(?,?,?,?,?)", (refund_id, event_id, order_id,
                     amount, occurred_at))
        return {"refund_id": refund_id, "order_id": order_id, "amount": amount}

    def order_detail(self, order_id: str) -> dict:
        with self.store.read() as conn:
            row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if not row:
                raise MissingReference("order does not exist")
            result = dict(row)
            result["refunds"] = [dict(refund) for refund in conn.execute(
                "SELECT * FROM refunds WHERE order_id=? ORDER BY occurred_at", (order_id,))]
            result["net_amount"] = format(Decimal(row["amount"]) - sum(
                (Decimal(x["amount"]) for x in result["refunds"]), Decimal("0")), ".2f")
            return result
