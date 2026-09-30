"""Separate completed history from the requested session; reject ambiguous bars."""

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


def aggregate_minutes(rows, minutes=1, now=None):
    """Aggregate real 1m OHLCV before HA; never fill a missing minute.

    NSE's 09:15 open aligns with both supported epoch buckets. Only the
    current bucket may be partial. Previous incomplete buckets are excluded.
    """
    if minutes == 1:
        return rows
    interval = minutes * 60
    buckets = {}
    for row in rows:
        buckets.setdefault(int(row[0] // interval) * interval, []).append(row)
    result = []
    current = int(now // interval) * interval if now is not None else None
    for stamp, group in sorted(buckets.items()):
        stamps = [int(r[0]) for r in group]
        expected = list(range(stamp, stamp + interval, 60))
        if stamps != expected and not (stamp == current and stamps == expected[: len(group)]):
            continue
        result.append(
            [
                stamp,
                group[0][1],
                max(r[2] for r in group),
                min(r[3] for r in group),
                group[-1][4],
                sum(r[5] for r in group),
            ]
        )
    return result


def shared_request(provider, endpoint, owner, day, historical, cache_path=None):
    """One paced history request across all eight processes; bounded disk cache.

    Only candle data is saved. Neither tokens nor API keys enter the cache.
    A fresh session response is shared for five seconds; completed history is
    reused for this session. Holding the lock through the request coalesces
    identical concurrent warmups and serializes retries too.
    """
    from strategies.top_gain_volumes.coordination import dispatch_lock
    from strategies.top_gain_volumes.profiles import ROOT

    path = cache_path or ROOT / "db/strategy_history_cache.db"
    cache_key = hashlib.sha256((owner + endpoint).encode()).hexdigest()
    with dispatch_lock(path.with_suffix(".lock"), timeout=60):
        with closing(sqlite3.connect(path, timeout=5)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS history_cache "
                "(key TEXT PRIMARY KEY, day TEXT, fetched REAL, payload TEXT)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY, next REAL)")
            conn.execute("DELETE FROM history_cache WHERE day != ?", (day,))
            cached = conn.execute(
                "SELECT fetched,payload FROM history_cache WHERE key=?", (cache_key,)
            ).fetchone()
            if cached and (historical or 0 <= time.time() - cached[0] < 5):
                conn.commit()
                return json.loads(cached[1])
            row = conn.execute("SELECT next FROM pacing WHERE id=1").fetchone()
            delay = max(0, row[0] - time.time()) if row else 0
            if delay > 10:
                conn.commit()
                raise RuntimeError("History cooldown active; retry warmup later")
            if delay:
                time.sleep(delay)
            try:
                response = provider._request(endpoint)
            except Exception:
                conn.execute("INSERT OR REPLACE INTO pacing VALUES(1,?)", (time.time() + 60,))
                conn.commit()
                raise
            conn.execute("INSERT OR REPLACE INTO pacing VALUES(1,?)", (time.time() + 1.25,))
            conn.execute(
                "INSERT OR REPLACE INTO history_cache VALUES(?,?,?,?)",
                (cache_key, day, time.time(), json.dumps(response)),
            )
            conn.execute(
                "DELETE FROM history_cache WHERE key IN "
                "(SELECT key FROM history_cache ORDER BY fetched DESC LIMIT -1 OFFSET 2048)"
            )
            conn.commit()
            return response


def fetch_intraday_history(provider, broker_symbol, day, shared=False, owner=""):
    opening = int(datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
    rows = []
    # Full calendar-day requests can return conflicting duplicate current-day
    # candles from FYERS. Exact regular-session epochs return a single series.
    for first, last in (
        (opening - 7 * 86400, opening - 1),
        (opening + 555 * 60, opening + 930 * 60 - 1),
    ):
        endpoint = "/data/history?"
        endpoint += urlencode(
            {
                "symbol": broker_symbol,
                "resolution": "1",
                "date_format": "0",
                "range_from": str(first),
                "range_to": str(last),
                "cont_flag": "1",
            }
        )
        response = (
            shared_request(provider, endpoint, owner, day, last < opening)
            if shared
            else provider._request(endpoint)
        )
        fetched = response.get("candles") or []
        rows.extend(r for r in fetched if first <= r[0] <= last)
    return rows
