from __future__ import annotations

from .model import Conflict, DomainError, MissingReference, require_text, timestamp
from .spaces import Spaces
from .store import Store


class Programs:
    def __init__(self, store: Store, spaces: Spaces):
        self.store = store
        self.spaces = spaces

    def put(self, program_id: str, store_id: str, space_id: str, starts_at: str,
            ends_at: str, title: str, capacity: int) -> dict:
        program_id = require_text(program_id, "program_id")
        store_id = require_text(store_id, "store_id")
        space_id = require_text(space_id, "space_id")
        title = require_text(title, "title", limit=240)
        start = timestamp(starts_at, "starts_at")
        end = timestamp(ends_at, "ends_at")
        if end <= start or type(capacity) is not int or capacity < 1:
            raise DomainError("invalid program interval or capacity")
        with self.store.transaction() as conn:
            space = self.spaces.resolve(conn, space_id, start, store_id)
            if space["kind"] not in {"reading", "mixed", "event"}:
                raise Conflict("dining space cannot host reading program")
            if capacity > space["capacity"]:
                raise Conflict("program exceeds space capacity")
            if space["valid_until"] and end > space["valid_until"]:
                raise Conflict("program outlasts effective space")
            old = conn.execute("SELECT * FROM programs WHERE program_id=?", (program_id,)).fetchone()
            data = (program_id, store_id, space_id, start, end, title, capacity)
            if old:
                if tuple(old[key] for key in ("program_id", "store_id", "space_id", "starts_at", "ends_at", "title", "capacity")) != data:
                    raise Conflict("program already exists with different details")
                return dict(old)
            conn.execute("INSERT INTO programs VALUES(?,?,?,?,?,?,?)", data)
        return {"program_id": program_id, "store_id": store_id, "space_id": space_id,
                "starts_at": start, "ends_at": end, "title": title, "capacity": capacity}

    def resolve(self, conn, program_id: str) -> dict:
        row = conn.execute("SELECT * FROM programs WHERE program_id=?", (program_id,)).fetchone()
        if not row:
            raise MissingReference("program does not exist")
        return dict(row)

    def list(self, store_id: str | None = None) -> list[dict]:
        with self.store.read() as conn:
            if store_id:
                rows = conn.execute("SELECT * FROM programs WHERE store_id=? ORDER BY starts_at", (store_id,))
            else:
                rows = conn.execute("SELECT * FROM programs ORDER BY starts_at")
            return [dict(row) for row in rows]
