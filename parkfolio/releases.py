from __future__ import annotations

from datetime import datetime, timezone

from .mart import Mart
from .model import Conflict, MissingReference, canonical, fingerprint, month, require_text
from .store import Store


class Releases:
    def __init__(self, store: Store, mart: Mart):
        self.store = store
        self.mart = mart

    def preview(self, period: str) -> dict:
        period = month(period)
        snapshot = self.mart.period(period)
        return {"month": period, "fingerprint": fingerprint(snapshot),
                "ready": snapshot["quality"]["ready"], "snapshot": snapshot}

    def publish(self, name: str, period: str, expected_fingerprint: str) -> dict:
        name = require_text(name, "name")
        period = month(period)
        expected_fingerprint = require_text(expected_fingerprint, "expected_fingerprint")
        with self.store.transaction() as conn:
            old = conn.execute("SELECT * FROM releases WHERE name=?", (name,)).fetchone()
            if old:
                if old["month"] == period and old["fingerprint"] == expected_fingerprint:
                    return {"name": name, "month": period, "fingerprint": old["fingerprint"],
                            "created_at": old["created_at"], "created": False}
                raise Conflict("release name already belongs to different content")
            preview = self.preview(period)
            if not preview["ready"]:
                raise Conflict("month has unresolved input")
            if preview["fingerprint"] != expected_fingerprint:
                raise Conflict("preview fingerprint is stale")
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute("INSERT INTO releases VALUES(?,?,?,?,?)", (name, period,
                         expected_fingerprint, canonical(preview["snapshot"]), created_at))
            return {"name": name, "month": period, "fingerprint": expected_fingerprint,
                    "created_at": created_at, "created": True}

    def get(self, name: str) -> dict:
        import json
        with self.store.read() as conn:
            row = conn.execute("SELECT * FROM releases WHERE name=?", (name,)).fetchone()
            if not row:
                raise MissingReference("release does not exist")
            result = dict(row)
            result["snapshot"] = json.loads(result["snapshot"])
            return result

    def list(self) -> list[dict]:
        with self.store.read() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT name,month,fingerprint,created_at FROM releases ORDER BY created_at,name")]
