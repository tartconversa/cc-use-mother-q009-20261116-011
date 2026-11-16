from __future__ import annotations

from pathlib import Path

from .analysis import Analysis
from .attendance import Attendance
from .audit import Audit
from .catalog import Catalog
from .commerce import Commerce
from .compare import Compare
from .consistency import Consistency
from .events import Events
from .exports import Exports
from .journeys import Journeys
from .mart import Mart
from .programs import Programs
from .quality import Quality
from .releases import Releases
from .spaces import Spaces
from .store import Store


class Parkfolio:
    def __init__(self, path: str | Path):
        self.store = Store(path)
        self.spaces = Spaces(self.store)
        self.catalog = Catalog(self.store)
        self.journeys = Journeys(self.store, self.spaces, self.catalog)
        self.programs = Programs(self.store, self.spaces)
        self.commerce = Commerce(self.store, self.catalog, self.journeys)
        self.attendance = Attendance(self.store, self.programs, self.journeys)
        self.events = Events(self.store, self.journeys, self.commerce, self.attendance)
        self.quality = Quality(self.store)
        self.mart = Mart(self.store, self.quality)
        self.analysis = Analysis(self.store)
        self.audit = Audit(self.store)
        self.consistency = Consistency(self.store)
        self.releases = Releases(self.store, self.mart)
        self.exports = Exports(self.mart, self.quality, self.audit, self.releases)
        self.compare = Compare(self.mart, self.releases)

    def overview(self) -> dict:
        with self.store.read() as conn:
            return {
                "stores": conn.execute("SELECT count(*) FROM stores").fetchone()[0],
                "spaces": conn.execute("SELECT count(*) FROM spaces").fetchone()[0],
                "books": conn.execute("SELECT count(*) FROM books").fetchone()[0],
                "programs": conn.execute("SELECT count(*) FROM programs").fetchone()[0],
                "events": conn.execute("SELECT count(*) FROM raw_events").fetchone()[0],
                "quarantined": conn.execute(
                    "SELECT count(*) FROM raw_events WHERE status='quarantined'").fetchone()[0],
                "visits": conn.execute("SELECT count(*) FROM visits").fetchone()[0],
                "readings": conn.execute("SELECT count(*) FROM readings").fetchone()[0],
                "orders": conn.execute("SELECT count(*) FROM orders").fetchone()[0],
                "refunds": conn.execute("SELECT count(*) FROM refunds").fetchone()[0],
                "attendances": conn.execute("SELECT count(*) FROM attendance").fetchone()[0],
                "releases": conn.execute("SELECT count(*) FROM releases").fetchone()[0],
            }
