from __future__ import annotations

import csv
import io
import json

from .audit import Audit
from .mart import Mart
from .model import month, require_text
from .quality import Quality
from .releases import Releases


class Exports:
    def __init__(self, mart: Mart, quality: Quality, audit: Audit, releases: Releases):
        self.mart = mart
        self.quality = quality
        self.audit = audit
        self.releases = releases

    def month_json(self, period: str) -> str:
        result = self.mart.period(month(period))
        return json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)

    def month_csv(self, period: str) -> str:
        report = self.mart.period(month(period))
        fieldnames = ["month", "store_id", "park", "store_name", "visits", "unique_visitors",
                      "completed_visits", "reading_visits", "reading_minutes", "book_revenue",
                      "food_revenue", "drink_revenue", "programs", "attendances",
                      "reading_to_visit_rate", "source_event_ids"]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for store in report["stores"]:
            row = {key: store.get(key) for key in fieldnames if key != "month"}
            row["month"] = period
            row["source_event_ids"] = json.dumps(store["source_event_ids"])
            writer.writerow(row)
        return stream.getvalue()

    def quality_json(self, period: str) -> str:
        return json.dumps(self.quality.period(month(period)), ensure_ascii=False,
                          sort_keys=True, indent=2)

    def lineage_json(self, visit_id: str) -> str:
        return json.dumps(self.audit.visit(require_text(visit_id, "visit_id")),
                          ensure_ascii=False, sort_keys=True, indent=2)

    def release_json(self, name: str) -> str:
        return json.dumps(self.releases.get(require_text(name, "name")),
                          ensure_ascii=False, sort_keys=True, indent=2)

    def explain(self, period: str) -> dict:
        report = self.mart.period(month(period))
        source = self.audit.month_sources(period)
        reasons = []
        if report["quality"]["quarantined"]:
            reasons.append("unresolved source dependencies remain")
        if not report["stores"]:
            reasons.append("no stores registered")
        return {"month": period, "ready": report["quality"]["ready"],
                "store_count": len(report["stores"]), "source_events": source["total"],
                "source_groups": source["groups"], "issues": report["quality"]["issues"],
                "explanations": reasons}
