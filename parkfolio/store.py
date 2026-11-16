from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources (
  name TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS stores (
  store_id TEXT PRIMARY KEY, name TEXT NOT NULL, park TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spaces (
  space_id TEXT NOT NULL, store_id TEXT NOT NULL REFERENCES stores(store_id),
  version INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('reading','mixed','dining','event')),
  capacity INTEGER NOT NULL CHECK(capacity > 0), valid_from TEXT NOT NULL,
  valid_until TEXT, PRIMARY KEY(space_id,version),
  CHECK(valid_until IS NULL OR valid_until > valid_from)
);
CREATE INDEX IF NOT EXISTS spaces_period ON spaces(space_id,valid_from,valid_until);
CREATE TABLE IF NOT EXISTS books (
  book_id TEXT PRIMARY KEY, title TEXT NOT NULL, topic TEXT NOT NULL,
  store_id TEXT NOT NULL REFERENCES stores(store_id), active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS programs (
  program_id TEXT PRIMARY KEY, store_id TEXT NOT NULL REFERENCES stores(store_id),
  space_id TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
  title TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity > 0),
  CHECK(ends_at > starts_at)
);
CREATE TABLE IF NOT EXISTS raw_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL REFERENCES sources(name),
  external_id TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('applied','quarantined')),
  reason TEXT NOT NULL DEFAULT '', UNIQUE(source,external_id)
);
CREATE INDEX IF NOT EXISTS raw_month ON raw_events(occurred_at,status);
CREATE TABLE IF NOT EXISTS visits (
  visit_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, store_id TEXT NOT NULL REFERENCES stores(store_id),
  space_id TEXT NOT NULL, space_version INTEGER NOT NULL, opened_at TEXT NOT NULL,
  closed_at TEXT, open_event INTEGER NOT NULL REFERENCES raw_events(id),
  close_event INTEGER REFERENCES raw_events(id),
  CHECK(closed_at IS NULL OR closed_at > opened_at)
);
CREATE INDEX IF NOT EXISTS visits_store_time ON visits(store_id,opened_at);
CREATE TABLE IF NOT EXISTS readings (
  event_id INTEGER PRIMARY KEY REFERENCES raw_events(id), visit_id TEXT NOT NULL REFERENCES visits(visit_id),
  book_id TEXT NOT NULL REFERENCES books(book_id), minutes INTEGER NOT NULL CHECK(minutes > 0),
  occurred_at TEXT NOT NULL, space_id TEXT NOT NULL, space_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES raw_events(id),
  visit_id TEXT REFERENCES visits(visit_id), store_id TEXT NOT NULL REFERENCES stores(store_id),
  category TEXT NOT NULL CHECK(category IN ('book','food','drink')),
  book_id TEXT REFERENCES books(book_id), amount TEXT NOT NULL, occurred_at TEXT NOT NULL,
  CHECK((category='book' AND book_id IS NOT NULL) OR (category!='book' AND book_id IS NULL))
);
CREATE TABLE IF NOT EXISTS refunds (
  refund_id TEXT PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES raw_events(id),
  order_id TEXT NOT NULL REFERENCES orders(order_id), amount TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attendance (
  event_id INTEGER PRIMARY KEY REFERENCES raw_events(id), program_id TEXT NOT NULL REFERENCES programs(program_id),
  visitor_id TEXT NOT NULL, visit_id TEXT NOT NULL REFERENCES visits(visit_id),
  occurred_at TEXT NOT NULL, UNIQUE(program_id,visitor_id)
);
CREATE TABLE IF NOT EXISTS releases (
  name TEXT PRIMARY KEY, month TEXT NOT NULL, fingerprint TEXT NOT NULL,
  snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()
