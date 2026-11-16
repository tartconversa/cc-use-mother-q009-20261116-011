from __future__ import annotations

import sqlite3

from .attendance import Attendance
from .commerce import Commerce
from .journeys import Journeys
from .model import Conflict, DomainError, Event, MissingReference, canonical, fingerprint, require_text
from .store import Store


class Events:
    def __init__(self, store: Store, journeys: Journeys, commerce: Commerce, attendance: Attendance):
        self.store = store
        self.journeys = journeys
        self.commerce = commerce
        self.attendance = attendance

    def source(self, name: str, enabled: bool = True) -> dict:
        name = require_text(name, "source")
        if type(enabled) is not bool:
            raise DomainError("enabled must be boolean")
        with self.store.transaction() as conn:
            old = conn.execute("SELECT * FROM sources WHERE name=?", (name,)).fetchone()
            if old and old["enabled"] != int(enabled):
                conn.execute("UPDATE sources SET enabled=? WHERE name=?", (int(enabled), name))
            elif not old:
                conn.execute("INSERT INTO sources VALUES(?,?)", (name, int(enabled)))
        return {"name": name, "enabled": enabled}

    def _apply(self, conn, event_id: int, event: Event) -> dict:
        handler = {
            "visit_open": self.journeys.open,
            "visit_close": self.journeys.close,
            "reading": self.journeys.reading,
            "order": self.commerce.order,
            "refund": self.commerce.refund,
            "attendance": self.attendance.apply,
        }[event.kind]
        return handler(conn, event_id, event.occurred_at, event.payload)

    def accept(self, data: dict) -> dict:
        event = Event.parse(data)
        digest = fingerprint(event.data())
        with self.store.transaction() as conn:
            source = conn.execute("SELECT enabled FROM sources WHERE name=?", (event.source,)).fetchone()
            if not source or not source["enabled"]:
                raise MissingReference("source is absent or disabled")
            old = conn.execute("SELECT * FROM raw_events WHERE source=? AND external_id=?",
                               (event.source, event.external_id)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise Conflict("external event identity has different content")
                return {"event_id": old["id"], "created": False, "status": old["status"],
                        "reason": old["reason"]}
            cursor = conn.execute(
                "INSERT INTO raw_events(source,external_id,kind,occurred_at,received_at,body,digest,status) "
                "VALUES(?,?,?,?,?,?,?,'quarantined')",
                (event.source, event.external_id, event.kind, event.occurred_at,
                 event.received_at, canonical(event.data()), digest))
            event_id = cursor.lastrowid
            conn.execute("SAVEPOINT projection")
            try:
                projected = self._apply(conn, event_id, event)
            except MissingReference as exc:
                conn.execute("ROLLBACK TO projection")
                conn.execute("RELEASE projection")
                conn.execute("UPDATE raw_events SET reason=? WHERE id=?", (str(exc), event_id))
                return {"event_id": event_id, "created": True, "status": "quarantined",
                        "reason": str(exc)}
            except Exception:
                conn.execute("ROLLBACK TO projection")
                conn.execute("RELEASE projection")
                raise
            conn.execute("RELEASE projection")
            conn.execute("UPDATE raw_events SET status='applied',reason='' WHERE id=?", (event_id,))
            return {"event_id": event_id, "created": True, "status": "applied", "projected": projected}

    def retry(self, event_id: int) -> dict:
        with self.store.transaction() as conn:
            raw = conn.execute("SELECT * FROM raw_events WHERE id=?", (event_id,)).fetchone()
            if not raw:
                raise MissingReference("raw event does not exist")
            if raw["status"] == "applied":
                return {"event_id": event_id, "created": False, "status": "applied"}
            import json
            event = Event.parse(json.loads(raw["body"]))
            conn.execute("SAVEPOINT projection")
            try:
                projected = self._apply(conn, event_id, event)
            except MissingReference as exc:
                conn.execute("ROLLBACK TO projection")
                conn.execute("RELEASE projection")
                conn.execute("UPDATE raw_events SET reason=? WHERE id=?", (str(exc), event_id))
                return {"event_id": event_id, "created": False, "status": "quarantined", "reason": str(exc)}
            except Exception:
                conn.execute("ROLLBACK TO projection")
                conn.execute("RELEASE projection")
                raise
            conn.execute("RELEASE projection")
            conn.execute("UPDATE raw_events SET status='applied',reason='' WHERE id=?", (event_id,))
            return {"event_id": event_id, "created": False, "status": "applied", "projected": projected}

    def get(self, event_id: int) -> dict:
        with self.store.read() as conn:
            row = conn.execute("SELECT * FROM raw_events WHERE id=?", (event_id,)).fetchone()
            if not row:
                raise MissingReference("raw event does not exist")
            return dict(row)

    def list(self, status: str | None = None, month: str | None = None) -> list[dict]:
        clauses, args = [], []
        if status:
            if status not in {"applied", "quarantined"}:
                raise DomainError("invalid status")
            clauses.append("status=?")
            args.append(status)
        if month:
            clauses.append("substr(occurred_at,1,7)=?")
            args.append(month)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.store.read() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM raw_events" + where + " ORDER BY id", args)]
