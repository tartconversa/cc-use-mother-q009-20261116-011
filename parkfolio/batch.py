from __future__ import annotations

import json
from pathlib import Path

from .model import Conflict, DomainError, fingerprint, require_text
from .service import Parkfolio


class Batch:
    def __init__(self, service: Parkfolio):
        self.service = service
        conn = self.service.store.connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                  batch_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                  count INTEGER NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
                  completed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS batch_outcomes (
                  batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                  ordinal INTEGER NOT NULL, event_id INTEGER,
                  status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                  PRIMARY KEY(batch_id,ordinal)
                );
            """)
        finally:
            conn.close()

    def load(self, batch_id: str, events: list[dict], *, stop_after: int | None = None) -> dict:
        batch_id = require_text(batch_id, "batch_id")
        if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
            raise DomainError("batch requires a list of events")
        if stop_after is not None and (type(stop_after) is not int or stop_after < 0):
            raise DomainError("stop_after must be a nonnegative integer")
        digest = fingerprint(events)
        with self.service.store.transaction() as conn:
            row = conn.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if row and (row["digest"] != digest or row["count"] != len(events)):
                raise Conflict("batch id was used for a different manifest")
            if not row:
                conn.execute("INSERT INTO batches(batch_id,digest,count) VALUES(?,?,?)",
                             (batch_id, digest, len(events)))
        processed = 0
        for ordinal, item in enumerate(events):
            with self.service.store.read() as conn:
                cursor = conn.execute("SELECT cursor FROM batches WHERE batch_id=?", (batch_id,)).fetchone()[0]
            if ordinal < cursor:
                continue
            if stop_after is not None and processed >= stop_after:
                break
            try:
                result = self.service.events.accept(item)
                event_id = result["event_id"]
                status = result["status"]
                reason = result.get("reason", "")
            except (DomainError, Conflict) as exc:
                event_id = None
                status = "rejected"
                reason = str(exc)
            with self.service.store.transaction() as conn:
                current = conn.execute("SELECT cursor FROM batches WHERE batch_id=?", (batch_id,)).fetchone()[0]
                if current != ordinal:
                    raise Conflict("concurrent batch cursor changed")
                conn.execute("INSERT INTO batch_outcomes VALUES(?,?,?,?,?)",
                             (batch_id, ordinal, event_id, status, reason))
                conn.execute("UPDATE batches SET cursor=cursor+1 WHERE batch_id=?", (batch_id,))
            processed += 1
        with self.service.store.transaction() as conn:
            row = conn.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if row["cursor"] == row["count"] and not row["completed"]:
                conn.execute("UPDATE batches SET completed=1 WHERE batch_id=?", (batch_id,))
        return self.status(batch_id)

    def status(self, batch_id: str) -> dict:
        with self.service.store.read() as conn:
            row = conn.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if not row:
                from .model import MissingReference
                raise MissingReference("batch not found")
            result = dict(row)
            result["outcomes"] = [dict(x) for x in conn.execute(
                "SELECT * FROM batch_outcomes WHERE batch_id=? ORDER BY ordinal", (batch_id,))]
            return result

    def from_file(self, batch_id: str, path: str | Path, *, stop_after: int | None = None) -> dict:
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(content, list):
            raise DomainError("batch file must be a JSON array")
        return self.load(batch_id, content, stop_after=stop_after)
