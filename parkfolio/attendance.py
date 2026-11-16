from __future__ import annotations

from .journeys import Journeys
from .model import Conflict, DomainError, require_text
from .programs import Programs
from .store import Store


class Attendance:
    def __init__(self, store: Store, programs: Programs, journeys: Journeys):
        self.store = store
        self.programs = programs
        self.journeys = journeys

    def apply(self, conn, event_id: int, occurred_at: str, payload: dict) -> dict:
        program_id = require_text(payload.get("program_id"), "program_id")
        visit_id = require_text(payload.get("visit_id"), "visit_id")
        visitor_id = require_text(payload.get("visitor_id"), "visitor_id")
        program = self.programs.resolve(conn, program_id)
        visit = self.journeys.resolve(conn, visit_id, occurred_at, visitor_id=visitor_id)
        if visit["store_id"] != program["store_id"]:
            raise Conflict("attendance visit belongs to another store")
        if not (program["starts_at"] <= occurred_at < program["ends_at"]):
            raise DomainError("attendance is outside program interval")
        if visit["space_id"] != program["space_id"]:
            raise Conflict("attendance is in the wrong space")
        existing = conn.execute("SELECT 1 FROM attendance WHERE program_id=? AND visitor_id=?",
                                (program_id, visitor_id)).fetchone()
        if existing:
            raise Conflict("visitor already attended this program")
        count = conn.execute("SELECT count(*) FROM attendance WHERE program_id=?", (program_id,)).fetchone()[0]
        if count >= program["capacity"]:
            raise Conflict("program has reached capacity")
        conn.execute("INSERT INTO attendance VALUES(?,?,?,?,?)", (event_id, program_id,
                     visitor_id, visit_id, occurred_at))
        return {"program_id": program_id, "visit_id": visit_id, "visitor_id": visitor_id,
                "attendance_count": count + 1}

    def status(self, program_id: str) -> dict:
        with self.store.read() as conn:
            program = self.programs.resolve(conn, program_id)
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM attendance WHERE program_id=? ORDER BY occurred_at,event_id", (program_id,))]
            return {"program": program, "attendees": rows, "remaining": program["capacity"] - len(rows)}
