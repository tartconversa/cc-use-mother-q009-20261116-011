from __future__ import annotations

from .model import Conflict, MissingReference, require_text
from .store import Store


class Catalog:
    def __init__(self, store: Store):
        self.store = store

    def put(self, book_id: str, title: str, topic: str, store_id: str) -> dict:
        book_id = require_text(book_id, "book_id")
        title = require_text(title, "title", limit=240)
        topic = require_text(topic, "topic")
        store_id = require_text(store_id, "store_id")
        with self.store.transaction() as conn:
            if not conn.execute("SELECT 1 FROM stores WHERE store_id=?", (store_id,)).fetchone():
                raise MissingReference("book store does not exist")
            old = conn.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone()
            if old:
                if (old["title"], old["topic"], old["store_id"]) != (title, topic, store_id):
                    raise Conflict("book identity already exists with different attributes")
                return dict(old)
            conn.execute("INSERT INTO books(book_id,title,topic,store_id) VALUES(?,?,?,?)", (book_id, title, topic, store_id))
        return {"book_id": book_id, "title": title, "topic": topic, "store_id": store_id, "active": 1}

    def resolve(self, conn, book_id: str, store_id: str) -> dict:
        row = conn.execute("SELECT * FROM books WHERE book_id=? AND active=1", (book_id,)).fetchone()
        if not row:
            raise MissingReference("book is not in active catalog")
        if row["store_id"] != store_id:
            raise Conflict("book belongs to another store")
        return dict(row)

    def set_active(self, book_id: str, active: bool) -> dict:
        if type(active) is not bool:
            raise ValueError("active must be boolean")
        with self.store.transaction() as conn:
            row = conn.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone()
            if not row:
                raise MissingReference("book does not exist")
            conn.execute("UPDATE books SET active=? WHERE book_id=?", (int(active), book_id))
            return dict(conn.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone())

    def list(self, store_id: str | None = None, active_only: bool = False) -> list[dict]:
        clauses, args = [], []
        if store_id:
            clauses.append("store_id=?")
            args.append(store_id)
        if active_only:
            clauses.append("active=1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.store.read() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM books" + where + " ORDER BY book_id", args)]
