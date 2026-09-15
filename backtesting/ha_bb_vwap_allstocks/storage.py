"""Transactional day checkpoints and indexed, read-only dashboard queries."""

import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

from .statistics import microseconds

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY, name TEXT, side TEXT, minutes INTEGER, config TEXT);
CREATE TABLE IF NOT EXISTS days(day TEXT PRIMARY KEY, symbols INTEGER, tested INTEGER, skipped INTEGER, benchmark REAL, source_hash TEXT);
CREATE TABLE IF NOT EXISTS daily(strategy TEXT, scenario TEXT, day TEXT, payload TEXT,
 PRIMARY KEY(strategy,scenario,day));
CREATE TABLE IF NOT EXISTS series(strategy TEXT, scenario TEXT, day TEXT, payload BLOB,
 PRIMARY KEY(strategy,scenario,day));
CREATE TABLE IF NOT EXISTS coverage(day TEXT, symbol TEXT, status TEXT, details TEXT,
 PRIMARY KEY(day,symbol));
CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY, strategy TEXT, scenario TEXT, day TEXT, symbol TEXT,
 minutes INTEGER, side TEXT, entry_us INTEGER, exit_us INTEGER, quantity INTEGER, entry_price REAL,
 net REAL, gross REAL, fees REAL, brokerage REAL, payload BLOB);
CREATE INDEX IF NOT EXISTS trade_selection ON trades(strategy,scenario,day,entry_us);
CREATE INDEX IF NOT EXISTS trade_stock ON trades(strategy,scenario,symbol,day);
CREATE TABLE IF NOT EXISTS fills(trade_id TEXT, seq INTEGER, time_us INTEGER, side TEXT, quantity INTEGER,
 price REAL, fees REAL, brokerage REAL, reason TEXT, costs TEXT,
 PRIMARY KEY(trade_id,seq));
CREATE TABLE IF NOT EXISTS candles(day TEXT,symbol TEXT,minutes INTEGER,payload BLOB,
 PRIMARY KEY(day,symbol,minutes));
CREATE TABLE IF NOT EXISTS rejections(strategy TEXT,scenario TEXT,day TEXT,symbol TEXT,payload TEXT);
"""


def encode(value):
    return zlib.compress(json.dumps(value, allow_nan=False, separators=(",", ":")).encode(), 6)


def decode(value):
    return json.loads(zlib.decompress(value))


class Store:
    def __init__(self, path, manifest, definitions, resume=False):
        self.path = Path(path)
        if self.path.exists() and not resume:
            raise ValueError(
                "Output exists; use resume for the identical run, or a new output directory"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            previous = self.db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()
            if previous and json.loads(previous[0]) != manifest:
                raise ValueError(
                    "Resume refused: source content, code, metadata, costs or selection changed"
                )
            if not previous:
                self.db.execute("INSERT INTO meta VALUES('manifest',?)", (json.dumps(manifest),))
                for sid, cfg in definitions:
                    self.db.execute(
                        "INSERT INTO strategies VALUES(?,?,?,?,?)",
                        (sid, cfg["name"], cfg["side"], cfg["timeframe_minutes"], json.dumps(cfg)),
                    )
                self.db.commit()
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def complete_days(self):
        return {r[0] for r in self.db.execute("SELECT day FROM days")}

    def add_trades(self, trades):
        for t in trades:
            brokerage = sum(f["costs"]["brokerage"] for f in t["fills"])
            self.db.execute(
                "INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    t["id"],
                    t["strategy_id"],
                    t["scenario"],
                    t["day"],
                    t["symbol"],
                    t["minutes"],
                    t["side"],
                    microseconds(t["entry_time"]),
                    microseconds(t["exit_time"]),
                    t["quantity"],
                    t["entry_price"],
                    t["net_pnl"],
                    t["gross_pnl"],
                    t["fees"],
                    brokerage,
                    encode(t),
                ),
            )
            self.db.executemany(
                "INSERT INTO fills VALUES(?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        t["id"],
                        i,
                        microseconds(f["time"]),
                        f["side"],
                        f["quantity"],
                        f["price"],
                        f["fees"],
                        f["costs"]["brokerage"],
                        f["reason"],
                        json.dumps(f["costs"]),
                    )
                    for i, f in enumerate(t["fills"])
                ],
            )

    def daily(self, strategy, path, day, row, series):
        self.db.execute("INSERT INTO daily VALUES(?,?,?,?)", (strategy, path, day, json.dumps(row)))
        self.db.execute("INSERT INTO series VALUES(?,?,?,?)", (strategy, path, day, encode(series)))


def read_connection(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return closing(db)
