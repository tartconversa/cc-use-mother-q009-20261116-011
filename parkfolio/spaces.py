from __future__ import annotations

from .model import Conflict, DomainError, MissingReference, require_text, timestamp
from .store import Store


class Spaces:
    def __init__(self, store: Store):
        self.store = store

    def put_store(self, store_id: str, name: str, park: str) -> dict:
        store_id = require_text(store_id, "store_id")
        name = require_text(name, "name")
        park = require_text(park, "park")
        with self.store.transaction() as conn:
            old = conn.execute("SELECT * FROM stores WHERE store_id=?", (store_id,)).fetchone()
            if old:
                if old["name"] != name or old["park"] != park:
                    raise Conflict("store identity already exists with different attributes")
                return dict(old)
            conn.execute("INSERT INTO stores VALUES(?,?,?)", (store_id, name, park))
        return {"store_id": store_id, "name": name, "park": park}

    def put_space(self, space_id: str, store_id: str, kind: str, capacity: int,
                  valid_from: str, valid_until: str | None = None) -> dict:
        space_id = require_text(space_id, "space_id")
        store_id = require_text(store_id, "store_id")
        if kind not in {"reading", "mixed", "dining", "event"}:
            raise DomainError("invalid space kind")
        if type(capacity) is not int or capacity < 1:
            raise DomainError("capacity must be positive integer")
        start = timestamp(valid_from, "valid_from")
        end = timestamp(valid_until, "valid_until") if valid_until else None
        if end and end <= start:
            raise DomainError("valid_until must follow valid_from")
        with self.store.transaction() as conn:
            if not conn.execute("SELECT 1 FROM stores WHERE store_id=?", (store_id,)).fetchone():
                raise MissingReference("unknown store")
            matches = conn.execute("SELECT * FROM spaces WHERE space_id=? ORDER BY version", (space_id,)).fetchall()
            for row in matches:
                if row["valid_from"] < (end or "9999") and start < (row["valid_until"] or "9999"):
                    if (row["store_id"], row["kind"], row["capacity"], row["valid_from"], row["valid_until"]) == (store_id, kind, capacity, start, end):
                        return dict(row)
                    raise Conflict("space effective periods overlap")
            version = (matches[-1]["version"] + 1) if matches else 1
            conn.execute("INSERT INTO spaces VALUES(?,?,?,?,?,?,?)", (space_id, store_id, version, kind, capacity, start, end))
        return {"space_id": space_id, "store_id": store_id, "version": version,
                "kind": kind, "capacity": capacity, "valid_from": start, "valid_until": end}

    def resolve(self, conn, space_id: str, at: str, store_id: str | None = None) -> dict:
        row = conn.execute("SELECT * FROM spaces WHERE space_id=? AND valid_from<=? "
                           "AND (valid_until IS NULL OR valid_until>?)", (space_id, at, at)).fetchone()
        if not row:
            raise MissingReference(f"space {space_id} is not effective at {at}")
        if store_id is not None and row["store_id"] != store_id:
            raise Conflict("space belongs to another store")
        return dict(row)

    def list_stores(self) -> list[dict]:
        with self.store.read() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM stores ORDER BY store_id")]

    def list_spaces(self, store_id: str | None = None) -> list[dict]:
        with self.store.read() as conn:
            if store_id:
                rows = conn.execute("SELECT * FROM spaces WHERE store_id=? ORDER BY space_id,version", (store_id,))
            else:
                rows = conn.execute("SELECT * FROM spaces ORDER BY space_id,version")
            return [dict(row) for row in rows]
