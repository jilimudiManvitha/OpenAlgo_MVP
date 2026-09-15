"""Read-only Historify access. No application imports, downloads or migrations."""

import hashlib
import json
from dataclasses import replace
from datetime import datetime, time, timedelta

import duckdb

from strategies.ha_bb_vwap_v1.models import IST, Candle

from .configuration import resolve


def bounds(day):
    start = datetime.combine(datetime.fromisoformat(day).date(), time(9, 15), IST)
    return start, start.replace(hour=15, minute=30)


def aggregate(bars, minutes=5):
    result, bucket = [], []
    for bar in bars:
        start = bar.start.replace(minute=(bar.start.minute // minutes) * minutes)
        if bucket and bucket[0][0] != start:
            result.append(_bucket(bucket, minutes))
            bucket = []
        bucket.append((start, bar))
    if bucket:
        result.append(_bucket(bucket, minutes))
    return result


def _bucket(bucket, minutes):
    start, first = bucket[0]
    return Candle(
        start,
        start + timedelta(minutes=minutes),
        first.open,
        max(b.high for _, b in bucket),
        min(b.low for _, b in bucket),
        bucket[-1][1].close,
        sum(b.volume for _, b in bucket),
        True,
    )


class Source:
    def __init__(self, config):
        self.config, self.db = config, None

    def __enter__(self):
        path = resolve(self.config["source"])
        if not path.is_file():
            raise FileNotFoundError(f"Historify source not found: {path}")
        wal = path.with_suffix(path.suffix + ".wal")
        if wal.exists() and wal.stat().st_size:
            raise ValueError(
                "Use a clean checkpointed DuckDB snapshot; a nonempty WAL is present. Do not delete the WAL."
            )
        self.db = duckdb.connect(
            str(path),
            read_only=True,
            config={
                "threads": self.config["duckdb_threads"],
                "memory_limit": self.config["duckdb_memory_limit"],
            },
        )
        try:
            self.db.execute("SET TimeZone='UTC'")
            columns = {r[0] for r in self.db.execute("DESCRIBE market_data").fetchall()}
            required = {
                "symbol",
                "exchange",
                "interval",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            }
            if not required <= columns:
                raise ValueError(
                    "Expected OpenAlgo Historify market_data schema with epoch-second timestamps"
                )
        except Exception:
            self.db.close()
            raise
        return self

    def __exit__(self, *args):
        if self.db:
            self.db.close()

    def catalog(self):
        a, _ = bounds(self.config["start"])
        _, b = bounds(self.config["end"])
        rows = self.db.execute(
            """SELECT symbol, count(*), min(timestamp), max(timestamp)
            FROM market_data WHERE exchange=? AND interval='1m' AND timestamp>=? AND timestamp<?
            GROUP BY symbol ORDER BY symbol""",
            [self.config["exchange"], int(a.timestamp()), int(b.timestamp())],
        ).fetchall()
        wanted = set(self.config["symbols"])
        selected = [r for r in rows if not wanted or r[0] in wanted]
        if wanted - {r[0] for r in selected}:
            raise ValueError(
                f"Requested symbols absent in date range: {sorted(wanted - {r[0] for r in selected})}"
            )
        return selected

    def calendar(self):
        a, _ = bounds(self.config["start"])
        _, b = bounds(self.config["end"])
        return [
            r[0]
            for r in self.db.execute(
                """SELECT DISTINCT strftime(to_timestamp(timestamp+19800),'%Y-%m-%d') AS session_day
            FROM market_data WHERE exchange=? AND interval='1m' AND timestamp>=? AND timestamp<? ORDER BY session_day""",
                [self.config["exchange"], int(a.timestamp()), int(b.timestamp())],
            ).fetchall()
        ]

    def day_symbols(self, day):
        a, b = bounds(day)
        return [
            r[0]
            for r in self.db.execute(
                "SELECT DISTINCT symbol FROM market_data WHERE exchange=? AND interval='1m' AND timestamp>=? AND timestamp<? ORDER BY symbol",
                [self.config["exchange"], int(a.timestamp()), int(b.timestamp())],
            ).fetchall()
        ]

    def rows(self, symbol, exchange, start, end=None, limit=None):
        sql = "SELECT timestamp,open,high,low,close,volume FROM market_data WHERE symbol=? AND exchange=? AND interval='1m'"
        parameters = [symbol, exchange]
        if end is not None:
            sql += " AND timestamp>=? AND timestamp<? ORDER BY timestamp"
            parameters += [int(start.timestamp()), int(end.timestamp())]
        else:
            sql += " AND timestamp<? ORDER BY timestamp DESC LIMIT ?"
            parameters += [int(start.timestamp()), int(limit)]
        rows = self.db.execute(sql, parameters).fetchall()
        return rows if end is not None else list(reversed(rows))

    def session(self, symbol, day):
        start, end = bounds(day)
        current = self.rows(symbol, self.config["exchange"], start, end)
        prior = self.rows(
            symbol, self.config["exchange"], start, limit=self.config["warmup_bars"] * 5 + 375
        )
        digest = hashlib.sha256(json.dumps([prior, current], allow_nan=True).encode()).hexdigest()

        def convert(rows):
            bars, seen = [], set()
            for stamp, *values in rows:
                when = datetime.fromtimestamp(stamp, IST)
                if not time(9, 15) <= when.time() < time(15, 30):
                    continue
                if when in seen:
                    raise ValueError("Duplicate minute timestamp")
                seen.add(when)
                bar = Candle(when, when + timedelta(minutes=1), *map(float, values), True)
                bar.validate(1)
                bars.append(bar)
            return bars

        bars, warmup = convert(current), convert(prior)
        if not bars:
            raise ValueError("No regular-session minute bars")
        missing = 375 - len(bars)
        if missing and not self.config["allow_missing_minutes"]:
            raise ValueError(f"Incomplete regular session: {missing} missing minutes")
        audit = {
            "rows": len(bars),
            "missing_minutes": missing,
            "zero_volume_minutes": sum(b.volume == 0 for b in bars),
            "warmup_1m": min(len(warmup), self.config["warmup_bars"]),
            "input_sha256": digest,
        }
        return warmup, bars, audit

    def benchmark(self, day):
        a, b = bounds(day)
        rows = self.rows(self.config["benchmark_symbol"], self.config["benchmark_exchange"], a, b)
        if (
            len(rows) != 375
            or not rows[0][1]
            or rows[0][0] != int(a.timestamp())
            or rows[-1][0] != int(b.timestamp()) - 60
        ):
            return None
        return rows[-1][4] / rows[0][1] - 1
