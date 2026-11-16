from __future__ import annotations

from decimal import Decimal

from .mart import Mart
from .model import MissingReference, month, require_text
from .releases import Releases


class Compare:
    def __init__(self, mart: Mart, releases: Releases):
        self.mart = mart
        self.releases = releases

    def months(self, store_id: str, first: str, second: str) -> dict:
        store_id = require_text(store_id, "store_id")
        first = month(first)
        second = month(second)
        left = self.mart.store_month(store_id, first)["store"]
        right = self.mart.store_month(store_id, second)["store"]
        counts = ("visits", "unique_visitors", "reading_visits", "reading_minutes", "attendances")
        money = ("book_revenue", "food_revenue", "drink_revenue")
        deltas = {key: right[key] - left[key] for key in counts}
        deltas.update({key: format(Decimal(right[key]) - Decimal(left[key]), ".2f") for key in money})
        return {"store_id": store_id, "first": first, "second": second,
                "first_values": {key: left[key] for key in counts + money},
                "second_values": {key: right[key] for key in counts + money},
                "deltas": deltas, "basis": "current"}

    def release_to_current(self, release_name: str) -> dict:
        release_name = require_text(release_name, "release_name")
        old = self.releases.get(release_name)
        current = self.mart.period(old["month"])
        old_by_id = {row["store_id"]: row for row in old["snapshot"]["stores"]}
        new_by_id = {row["store_id"]: row for row in current["stores"]}
        changes = []
        for sid in sorted(set(old_by_id) | set(new_by_id)):
            left = old_by_id.get(sid)
            right = new_by_id.get(sid)
            if left == right:
                continue
            changes.append({"store_id": sid, "old": left, "current": right,
                            "new_source_ids": sorted(set(right["source_event_ids"]) -
                                                     set(left["source_event_ids"])) if left and right else []})
        return {"release": release_name, "month": old["month"],
                "frozen_fingerprint": old["fingerprint"],
                "changed_stores": changes, "same": not changes}

    def release_pair(self, first_name: str, second_name: str) -> dict:
        first = self.releases.get(first_name)
        second = self.releases.get(second_name)
        if first["month"] != second["month"]:
            raise MissingReference("releases describe different months")
        first_rows = {row["store_id"]: row for row in first["snapshot"]["stores"]}
        second_rows = {row["store_id"]: row for row in second["snapshot"]["stores"]}
        changed = [sid for sid in sorted(set(first_rows) | set(second_rows))
                   if first_rows.get(sid) != second_rows.get(sid)]
        return {"month": first["month"], "first": first_name, "second": second_name,
                "first_fingerprint": first["fingerprint"],
                "second_fingerprint": second["fingerprint"],
                "changed_store_ids": changed}
