"""Atomic state, order intentions and audit journal, isolated by owner and variant.

Each connection is short-lived. BEGIN IMMEDIATE serializes writers; revision checks
reject two runners trying to advance the same strategy from the same snapshot.
"""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


class StateConflict(RuntimeError):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS states (
                    owner TEXT NOT NULL, strategy TEXT NOT NULL, revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(owner,strategy));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, strategy TEXT NOT NULL,
                    timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_owner_strategy ON events(owner,strategy,id);
                CREATE INDEX IF NOT EXISTS events_daily ON events(owner,strategy,kind,timestamp);
            """)

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def load(self, owner, strategy):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn:
            row = conn.execute(
                "SELECT revision,payload FROM states WHERE owner=? AND strategy=?",
                (owner, strategy),
            ).fetchone()
        return (row[0], json.loads(row[1])) if row else (0, None)

    def save(self, owner, strategy, revision, state, events=()):
        stamp = datetime.now(UTC).isoformat()
        payload = json.dumps(state, sort_keys=True, allow_nan=False)
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT revision FROM states WHERE owner=? AND strategy=?", (owner, strategy)
            ).fetchone()
            current = row[0] if row else 0
            if current != revision:
                raise StateConflict("Another runner changed strategy state")
            conn.execute(
                "INSERT INTO states VALUES (?,?,?,?,?) ON CONFLICT(owner,strategy) DO UPDATE SET "
                "revision=excluded.revision,payload=excluded.payload,updated_at=excluded.updated_at",
                (owner, strategy, revision + 1, payload, stamp),
            )
            for kind, event in events:
                conn.execute(
                    "INSERT INTO events(owner,strategy,timestamp,kind,payload) VALUES (?,?,?,?,?)",
                    (owner, strategy, stamp, kind, json.dumps(event, allow_nan=False)),
                )
        return revision + 1

    def closed_trades(self, owner, strategy, day):
        start = datetime.combine(day, time(), ZoneInfo("Asia/Kolkata"))
        end = start + timedelta(days=1)
        with closing(sqlite3.connect(self.path, timeout=30)) as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE owner=? AND strategy=? AND kind='trade' "
                "AND timestamp>=? AND timestamp<? ORDER BY id",
                (
                    owner,
                    strategy,
                    start.astimezone(UTC).isoformat(),
                    end.astimezone(UTC).isoformat(),
                ),
            ).fetchall()
        return [leg for row in rows for leg in json.loads(row[0])]


def config_hash(profile, policy):
    from dataclasses import asdict

    return hashlib.sha256(
        json.dumps({"profile": asdict(profile), "policy": asdict(policy)}, sort_keys=True).encode()
    ).hexdigest()
