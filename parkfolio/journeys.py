from __future__ import annotations

from .model import Conflict, DomainError, MissingReference, minutes, require_text
from .spaces import Spaces
from .catalog import Catalog
from .store import Store


class Journeys:
    def __init__(self, store: Store, spaces: Spaces, catalog: Catalog):
        self.store = store
        self.spaces = spaces
        self.catalog = catalog

    def open(self, conn, event_id: int, occurred_at: str, payload: dict) -> dict:
        visit_id = require_text(payload.get("visit_id"), "visit_id")
        visitor_id = require_text(payload.get("visitor_id"), "visitor_id")
        store_id = require_text(payload.get("store_id"), "store_id")
        space_id = require_text(payload.get("space_id"), "space_id")
        space = self.spaces.resolve(conn, space_id, occurred_at, store_id)
        if space["kind"] == "dining":
            raise Conflict("reading visit cannot start in dining-only space")
        if conn.execute("SELECT 1 FROM visits WHERE visit_id=?", (visit_id,)).fetchone():
            raise Conflict("visit identity already exists")
        overlapping = conn.execute(
            "SELECT visit_id FROM visits WHERE visitor_id=? AND store_id=? AND opened_at<=? "
            "AND (closed_at IS NULL OR closed_at>?)", (visitor_id, store_id, occurred_at, occurred_at)
        ).fetchone()
        if overlapping:
            raise Conflict("visitor already has an overlapping visit")
        conn.execute("INSERT INTO visits(visit_id,visitor_id,store_id,space_id,space_version,opened_at,open_event) "
                     "VALUES(?,?,?,?,?,?,?)", (visit_id, visitor_id, store_id, space_id,
                                               space["version"], occurred_at, event_id))
        return {"visit_id": visit_id, "space_version": space["version"]}

    def resolve(self, conn, visit_id: str, at: str, *, visitor_id: str | None = None) -> dict:
        row = conn.execute("SELECT * FROM visits WHERE visit_id=?", (visit_id,)).fetchone()
        if not row:
            raise MissingReference("visit has not opened")
        if at < row["opened_at"] or (row["closed_at"] is not None and at >= row["closed_at"]):
            raise Conflict("event falls outside visit")
        if visitor_id is not None and row["visitor_id"] != visitor_id:
            raise Conflict("visitor does not match visit")
        return dict(row)

    def close(self, conn, event_id: int, occurred_at: str, payload: dict) -> dict:
        visit_id = require_text(payload.get("visit_id"), "visit_id")
        row = self.resolve(conn, visit_id, occurred_at)
        if row["closed_at"] is not None:
            raise Conflict("visit already closed")
        if occurred_at <= row["opened_at"]:
            raise DomainError("visit close must follow opening")
        conn.execute("UPDATE visits SET closed_at=?,close_event=? WHERE visit_id=?",
                     (occurred_at, event_id, visit_id))
        return {"visit_id": visit_id, "closed_at": occurred_at}

    def reading(self, conn, event_id: int, occurred_at: str, payload: dict) -> dict:
        visit_id = require_text(payload.get("visit_id"), "visit_id")
        book_id = require_text(payload.get("book_id"), "book_id")
        dwell = minutes(payload.get("minutes"))
        visit = self.resolve(conn, visit_id, occurred_at)
        self.catalog.resolve(conn, book_id, visit["store_id"])
        space = self.spaces.resolve(conn, visit["space_id"], occurred_at, visit["store_id"])
        if space["kind"] == "dining":
            raise Conflict("reading event cannot occur in dining-only space")
        if space["version"] != visit["space_version"]:
            raise Conflict("visit crosses space version; split the visit")
        conn.execute("INSERT INTO readings VALUES(?,?,?,?,?,?,?)", (event_id, visit_id, book_id,
                     dwell, occurred_at, space["space_id"], space["version"]))
        return {"visit_id": visit_id, "book_id": book_id, "minutes": dwell,
                "space_version": space["version"]}

    def list(self, store_id: str | None = None, month: str | None = None) -> list[dict]:
        conditions, args = [], []
        if store_id:
            conditions.append("store_id=?")
            args.append(store_id)
        if month:
            conditions.append("substr(opened_at,1,7)=?")
            args.append(month)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.store.read() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM visits" + where + " ORDER BY opened_at", args)]

    def reading_events(self, visit_id: str) -> list[dict]:
        with self.store.read() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT r.*,b.title,b.topic FROM readings r JOIN books b USING(book_id) "
                "WHERE visit_id=? ORDER BY occurred_at,event_id", (visit_id,))]
