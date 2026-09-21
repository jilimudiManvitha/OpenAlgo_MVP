"""Standalone, bounded-memory crypto trade replay. Python 3.11+; see README.md."""

import argparse
import csv
import hashlib
import html
import json
import math
import os
import shutil
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime, timezone
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

import duckdb
import numpy as np

# pyrefly: ignore [missing-import]
from numba import njit

VERSION = "1.0.0"
STRATEGIES = (
    ("S029", 1, 1, 23.5),
    ("S104", 1, 5, 10.5),
    ("S232", -1, 1, 24.0),
    ("S344", -1, 5, 29.5),
)
FOLDERS = {"BTCUSD": "btcfut", "ETHUSD": "ethfut", "SOLUSD": "solusd", "XAUTUSD": "xautusdfut"}
REASONS = {0: "entry", 1: "stop_loss", 4: "fixed_target", 8: "end_of_data"}
DAY_US = 86_400_000_000


def iso(us):
    return datetime.fromtimestamp(float(us) / 1e6, UTC).isoformat()


def json_write(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def candle_state():
    # active, bucket, O,H,L,C,V, previous HA O/C, closed count,
    # VWAP date/numerator/volume, ring insertion index; last 19 HA closes.
    return np.zeros(33, dtype=np.float64)


@njit(cache=True)
def snapshot(s, observed, complete, executable, execution_time):
    e = np.full(22, np.nan)
    hc = (s[2] + s[3] + s[4] + s[5]) / 4
    ho = (s[7] + s[8]) / 2 if s[9] else (s[2] + s[5]) / 2
    e[:8] = (
        float(observed),
        s[1],
        float(complete),
        s[5],
        ho,
        max(s[3], ho, hc),
        min(s[4], ho, hc),
        hc,
    )
    if s[9] >= 19:
        # Population standard deviation, BB(20,2) on HA closes.
        total = hc
        for j in range(19):
            total += s[14 + j]
        mean = total / 20
        variance = (hc - mean) ** 2
        for j in range(19):
            variance += (s[14 + j] - mean) ** 2
        sd = math.sqrt(variance / 20)
        e[8:11] = (mean + 2 * sd, mean, mean - 2 * sd)
    same_day = s[1] // DAY_US == s[10]
    numerator = s[11] if same_day else 0.0
    volume = s[12] if same_day else 0.0
    numerator += (s[3] + s[4] + s[5]) / 3 * s[6]
    volume += s[6]
    e[11] = numerator / volume if volume else np.nan
    e[20:22] = (executable, execution_time)
    return e


@njit(cache=True)
def commit_candle(s, e):
    day = s[1] // DAY_US
    if day != s[10]:
        s[10:13] = (day, 0.0, 0.0)
    s[11] += (s[3] + s[4] + s[5]) / 3 * s[6]
    s[12] += s[6]
    s[7:10] = (e[4], e[7], s[9] + 1)
    s[14 + int(s[13])] = e[7]
    s[13] = (s[13] + 1) % 19


@njit(cache=True)
def make_events(ticks, minutes, s):
    events = np.empty((len(ticks) * 2, 22))
    candles = np.empty((len(ticks), 13))
    ne = nc = 0
    interval = minutes * 60_000_000
    for t, p, v in ticks:
        bucket = t // interval * interval
        if s[0] and bucket != s[1]:
            e = snapshot(s, s[1] + interval, 1, p, t)
            events[ne] = e
            ne += 1
            candles[nc] = (
                s[1],
                s[2],
                s[3],
                s[4],
                s[5],
                s[6],
                e[4],
                e[5],
                e[6],
                e[7],
                e[8],
                e[11],
                1.0,
            )
            nc += 1
            commit_candle(s, e)
            s[0] = 0
        if not s[0]:
            s[:7] = (1.0, bucket, p, p, p, p, v)
        else:
            s[3] = max(s[3], p)
            s[4] = min(s[4], p)
            s[5] = p
            s[6] += v
        events[ne] = snapshot(s, t, 0, p, t)
        ne += 1
    return events[:ne], candles[:nc]


def strategy_state():
    # qty units, entry, stop, target, cash, signal_valid, signal_bucket,
    # signal_HA_high/low, used_bucket, initial_stop, entry_signal_bucket.
    s = np.zeros(12)
    s[9] = -1
    return s


@njit(cache=True)
def no_wick(e, direction):
    tolerance = max(abs(e[4]), 1.0) * 1e-10
    return e[6] >= e[4] - tolerance if direction == 1 else e[5] <= e[4] + tolerance


@njit(cache=True)
def trade_events(events, s, direction, minutes, rr, capital, unit, fee_rate, slippage, final=False):
    fills = np.empty((len(events) + 1, 8))
    marks = np.empty((len(events) + 1, 2))
    nf = nm = 0
    for e in events:
        was_open = s[0] > 0
        reason = -1
        q = s[0]
        px = e[3]
        if was_open:
            if direction * (px - s[2]) <= 0:
                reason = 1
            elif direction * (px - s[3]) >= 0:
                reason = 4
        elif s[5]:
            expected = s[6] + minutes * 60_000_000
            if e[1] > expected:
                s[5] = 0
            elif e[1] == expected and s[6] != s[9] and not e[2] and no_wick(e, direction):
                band = e[8] if direction == 1 else e[10]
                threshold = s[7] if direction == 1 else s[8]
                if (
                    np.isfinite(band)
                    and np.isfinite(e[11])
                    and direction * (px - threshold) > 0
                    and direction * (px - band) > 0
                    and direction * (px - e[11]) > 0
                ):
                    initial_stop = s[8] - 0.1 if direction == 1 else s[7] + 0.1
                    risk = direction * (px - initial_stop)
                    if initial_stop > 0 and risk > 0 and px + direction * rr * risk > 0:
                        s[9] = s[6]
                        fill_price = e[20] * (1 + direction * slippage)
                        q = min(
                            math.floor(capital / (px * unit)),
                            math.floor(capital / (fill_price * unit)),
                        )
                        fill_risk = direction * (fill_price - initial_stop)
                        if q > 0 and fill_risk > 0 and fill_price + direction * rr * fill_risk > 0:
                            reason = 0
                            s[10:12] = (initial_stop, s[6])
        if reason >= 0:
            side = direction if reason == 0 else -direction
            fill_price = e[20] * (1 + side * slippage)
            fee = q * unit * fill_price * fee_rate
            s[4] -= fee
            if reason == 0:
                s[0:4] = (
                    q,
                    fill_price,
                    s[10],
                    fill_price + direction * rr * direction * (fill_price - s[10]),
                )
            else:
                s[4] += direction * (fill_price - s[1]) * q * unit
                s[0] = 0
            fills[nf] = (e[21], side * q * unit, fill_price, fee, float(reason), s[11], s[10], s[3])
            nf += 1
        if e[2] and not was_open:
            band = e[8] if direction == 1 else e[10]
            extreme = e[5] if direction == 1 else e[6]
            qualifies = (
                np.isfinite(band)
                and np.isfinite(e[11])
                and no_wick(e, direction)
                and direction * (extreme - band) > 0
                and direction * (extreme - e[11]) > 0
            )
            s[5:9] = (1.0 if qualifies else 0.0, e[1], e[5], e[6])
        marks[nm] = (e[21], s[4] + direction * (e[20] - s[1]) * s[0] * unit)
        nm += 1
    if final and s[0]:
        e = events[-1]
        price = e[20] * (1 - direction * slippage)
        quantity = s[0] * unit
        fee = quantity * price * fee_rate
        s[4] += direction * (price - s[1]) * quantity - fee
        fills[nf] = (e[21], -direction * quantity, price, fee, 8.0, s[11], s[10], s[3])
        nf += 1
        marks[nm] = (e[21], s[4])
        nm += 1
        s[0] = 0
    return fills[:nf], marks[:nm]


class Ledger:
    def __init__(self, folder, sid, direction, capital):
        self.sid, self.direction, self.capital = sid, direction, capital
        self.files = []
        self.fills = self.writer(
            folder / f"{sid}_fills.csv",
            [
                "time",
                "signed_quantity",
                "price",
                "fee",
                "reason",
                "signal_start",
                "initial_stop",
                "target",
            ],
        )
        self.trades = self.writer(
            folder / f"{sid}_trades.csv",
            [
                "entry_time",
                "exit_time",
                "quantity",
                "entry_price",
                "exit_price",
                "gross_pnl",
                "fees",
                "net_pnl",
                "exit_reason",
            ],
        )
        self.open_trade = None
        self.peak = self.drawdown = self.fees = self.net = self.gross = 0.0
        self.min_equity = capital
        self.count = self.wins = 0
        self.win_sum = self.loss_sum = self.best = self.worst = 0.0
        self.daily = {}
        self.cash_ledger = self.signed_position = self.peak_notional = 0.0

    def writer(self, path, columns):
        f = path.open("w", newline="", encoding="utf-8")
        self.files.append(f)
        w = csv.writer(f)
        w.writerow(columns)
        return w

    def add(self, fills, marks):
        for t, q, p, fee, reason, sig, stop, target in fills:
            self.fills.writerow([iso(t), q, p, fee, REASONS[int(reason)], iso(sig), stop, target])
            self.cash_ledger -= q * p + fee
            self.signed_position += q
            self.fees += fee
            if reason == 0:
                if self.open_trade is not None:
                    raise AssertionError("Overlapping position")
                self.open_trade = (t, abs(q), p, fee)
                self.peak_notional = max(self.peak_notional, abs(q) * p)
            else:
                if self.open_trade is None:
                    raise AssertionError("Exit without entry")
                entry_t, quantity, entry_p, entry_fee = self.open_trade
                if not math.isclose(quantity, abs(q), abs_tol=1e-8):
                    raise AssertionError("Exit quantity mismatch")
                gross = self.direction * (p - entry_p) * quantity
                fees = entry_fee + fee
                net = gross - fees
                self.trades.writerow(
                    [
                        iso(entry_t),
                        iso(t),
                        quantity,
                        entry_p,
                        p,
                        gross,
                        fees,
                        net,
                        REASONS[int(reason)],
                    ]
                )
                self.net += net
                self.gross += gross
                self.count += 1
                self.wins += net > 0
                self.win_sum += max(net, 0)
                self.loss_sum += min(net, 0)
                self.best = net if self.count == 1 else max(self.best, net)
                self.worst = net if self.count == 1 else min(self.worst, net)
                self.open_trade = None
        if len(marks):
            curve = marks[:, 1]
            peaks = np.maximum.accumulate(np.maximum(curve, self.peak))
            self.drawdown = max(self.drawdown, float(np.max(peaks - curve)))
            self.peak = float(peaks[-1])
            self.min_equity = min(self.min_equity, self.capital + float(curve.min()))
            days = marks[:, 0].astype(np.int64) // DAY_US
            ends = np.r_[np.flatnonzero(days[1:] != days[:-1]), len(days) - 1]
            for i in ends:
                self.daily[int(days[i])] = float(curve[i])

    def close(self, folder):
        for f in self.files:
            f.close()
        if self.open_trade is not None or abs(self.signed_position) > 1e-6:
            raise AssertionError("Final position is not flat")
        if not math.isclose(self.cash_ledger, self.net, abs_tol=1e-5, rel_tol=1e-9):
            raise AssertionError("Independent fill cashflow reconciliation failed")
        with (folder / f"{self.sid}_daily.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date_utc", "pnl", "cumulative_pnl", "reference_equity"])
            previous = 0.0
            if self.daily:
                for day in range(min(self.daily), max(self.daily) + 1):
                    value = self.daily.get(day, previous)
                    w.writerow(
                        [iso(day * DAY_US)[:10], value - previous, value, self.capital + value]
                    )
                    previous = value
        return {
            "id": self.sid,
            "trades": self.count,
            "net_pnl": self.net,
            "gross_pnl": self.gross,
            "fees": self.fees,
            "max_drawdown": self.drawdown,
            "win_rate_pct": 100 * self.wins / self.count if self.count else 0,
            "profit_factor": self.win_sum / -self.loss_sum if self.loss_sum else None,
            "best_trade": self.best,
            "worst_trade": self.worst,
            "return_pct": 100 * self.net / self.capital,
            "peak_entry_notional": self.peak_notional,
            "min_reference_equity": self.min_equity,
            "fill_cashflow_reconciled": True,
        }


def source_members(folder):
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".csv", ".zip"}:
            continue
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                for member in sorted(z.namelist()):
                    if member.lower().endswith(".csv") and not member.endswith("/"):
                        yield p, member
        else:
            yield p, None


def materialize(path, member, target):
    """Decompress only into our output; hash uncompressed bytes for exact dedup."""
    digest = hashlib.sha256()
    if member is None:
        return path, hash_file(path)
    with zipfile.ZipFile(path) as archive, archive.open(member) as src, target.open("wb") as dst:
        for block in iter(lambda: src.read(4 * 1024 * 1024), b""):
            digest.update(block)
            dst.write(block)
    return target, digest.hexdigest()


def ingest(folder, output, symbol, memory):
    members = list(source_members(folder))
    if not members:
        raise ValueError(f"No CSV or ZIP files in {folder}")
    db = duckdb.connect(str(output / "ticks.duckdb"), config={"threads": 1, "memory_limit": memory})
    db.execute("SET TimeZone='UTC'")
    db.execute("SET enable_progress_bar=false")
    db.execute(
        "CREATE TABLE IF NOT EXISTS ticks(t BIGINT,p DOUBLE,v DOUBLE,source_id INTEGER,row_id BIGINT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS inputs(digest VARCHAR PRIMARY KEY, source_id INTEGER, rows BIGINT)"
    )
    audits, seen = [], set()
    try:
        for path, member in members:
            before = path.stat()
            temporary = output / "import.csv"
            csv_path, digest = materialize(path, member, temporary)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"Source changed during read: {path}")
            audit = {"file": str(path), "member": member, "sha256_uncompressed": digest}
            if digest in seen:
                audit["status"] = "identical_copy_skipped"
                audits.append(audit)
                if member is not None:
                    temporary.unlink()
                continue
            seen.add(digest)
            existing = db.execute(
                "SELECT source_id,rows FROM inputs WHERE digest=?", [digest]
            ).fetchone()
            if existing:
                audit.update(status="cached", rows=existing[1])
            else:
                print(f"{symbol}: importing {path.name} {member or ''}", flush=True)
                db.execute("BEGIN")
                try:
                    db.execute(
                        """CREATE OR REPLACE TEMP TABLE incoming AS
                        SELECT product_symbol, timestamp AS original_time,
                        epoch_us(try_cast(timestamp AS TIMESTAMPTZ)) AS t,
                        try_cast(price AS DOUBLE) AS p, try_cast(size AS DOUBLE) AS v,
                        row_number() OVER () AS row_id
                        FROM read_csv(?, header=true, all_varchar=true, parallel=false)""",
                        [str(csv_path)],
                    )
                    invalid = db.execute(
                        """SELECT count(*) FROM incoming WHERE
                        product_symbol IS DISTINCT FROM ? OR t IS NULL OR p IS NULL OR v IS NULL
                        OR NOT isfinite(p) OR NOT isfinite(v) OR p<=0 OR v<=0
                        OR NOT regexp_matches(original_time, '^\\d{4}-\\d{2}-\\d{2}[ T]')""",
                        [symbol],
                    ).fetchone()[0]
                    if invalid:
                        raise ValueError(
                            f"{path}: {invalid} invalid rows; full dated timestamps and positive finite price/size required. Time-only values cannot be reconstructed."
                        )
                    sid = db.execute("SELECT coalesce(max(source_id),-1)+1 FROM inputs").fetchone()[
                        0
                    ]
                    count = db.execute("SELECT count(*) FROM incoming").fetchone()[0]
                    if not count:
                        raise ValueError(f"Empty CSV: {path}")
                    db.execute("INSERT INTO ticks SELECT t,p,v,?,row_id FROM incoming", [sid])
                    db.execute("INSERT INTO inputs VALUES(?,?,?)", [digest, sid, count])
                    db.execute("COMMIT")
                    audit.update(status="imported", rows=count)
                except Exception:
                    db.execute("ROLLBACK")
                    raise
            audits.append(audit)
            if member is not None:
                temporary.unlink()
            json_write(output / "input_audit.json", audits)
        stored = {r[0] for r in db.execute("SELECT digest FROM inputs").fetchall()}
        if stored != seen:
            raise ValueError(
                "Input files changed since cached import. Choose a fresh --output folder."
            )
        ranges = db.execute(
            "SELECT source_id,min(t),max(t) FROM ticks GROUP BY source_id ORDER BY min(t)"
        ).fetchall()
        for previous, current in zip(ranges, ranges[1:], strict=False):
            if current[1] <= previous[2]:
                raise ValueError(
                    "Non-identical input files overlap in time. Resolve overlapping exports before replay; no trade IDs exist to safely deduplicate individual rows."
                )
        db.execute("CHECKPOINT")
        total, first, last = db.execute("SELECT count(*),min(t),max(t) FROM ticks").fetchone()
        json_write(output / "input_audit.json", audits)
        return db, {
            "rows": total,
            "first": iso(first),
            "last": iso(last),
            "unique_files": len(seen),
            "duplicate_files": len(audits) - len(seen),
        }
    except Exception:
        db.close()
        raise


def fingerprint(folder, settings):
    files = [
        (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.suffix.lower() in {".csv", ".zip"}
    ]
    payload = {"files": files, "settings": settings, "code": hash_file(Path(__file__))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run_symbol(symbol, source, output_root, settings):
    started = time.perf_counter()
    folder = Path(source) / FOLDERS[symbol]
    output = Path(output_root) / symbol
    output.mkdir(parents=True, exist_ok=True)
    identity = fingerprint(folder, settings)
    done = output / "complete.json"
    if done.exists():
        result = json.loads(done.read_text())
        if result["fingerprint"] != identity:
            raise ValueError(f"{symbol}: inputs/settings/code changed; use a new --output folder")
        print(f"{symbol}: already complete", flush=True)
        return result
    db, coverage = ingest(folder, output, symbol, settings["memory"])
    imported = time.perf_counter()
    limit = settings["benchmark_ticks"]
    states = {m: candle_state() for m in (1, 5)}
    strategies = {sid: strategy_state() for sid, _, _, _ in STRATEGIES}
    ledgers = {sid: Ledger(output, sid, d, settings["capital"]) for sid, d, _, _ in STRATEGIES}
    candle_files, candle_writers = {}, {}
    for minutes in (1, 5):
        f = (output / f"candles_{minutes}m.csv").open("w", newline="", encoding="utf-8")
        candle_files[minutes] = f
        w = csv.writer(f)
        w.writerow(
            [
                "time_utc",
                "open",
                "high",
                "low",
                "close",
                "volume_source_size",
                "ha_open",
                "ha_high",
                "ha_low",
                "ha_close",
                "bb_upper",
                "vwap",
                "complete",
            ]
        )
        candle_writers[minutes] = w
    processed = gaps = equal_times = 0
    largest_gap = 0.0
    previous_t = None
    last_events = {}
    try:
        # ORDER BY spills to this output database's temp area when memory is bounded.
        query = "SELECT t,p,v FROM ticks ORDER BY t,source_id,row_id"
        if limit:
            query += f" LIMIT {int(limit)}"
        cursor = db.execute(query)
        while True:
            frame = cursor.fetch_df_chunk(64)
            if frame.empty:
                break
            ticks = frame.to_numpy(dtype=np.float64)
            times = ticks[:, 0]
            delta = np.diff(np.r_[previous_t, times] if previous_t is not None else times)
            gaps += int(np.sum(delta > 300_000_000))
            equal_times += int(np.sum(delta == 0))
            if len(delta):
                largest_gap = max(largest_gap, float(delta.max()) / 1e6)
            previous_t = times[-1]
            for minutes in (1, 5):
                events, candles = make_events(ticks, minutes, states[minutes])
                last_events[minutes] = events[-1:].copy()
                for row in candles:
                    candle_writers[minutes].writerow([iso(row[0]), *row[1:]])
                for sid, direction, timeframe, rr in STRATEGIES:
                    if timeframe != minutes:
                        continue
                    fills, marks = trade_events(
                        events,
                        strategies[sid],
                        direction,
                        minutes,
                        rr,
                        settings["capital"],
                        settings["unit"],
                        settings["fee"],
                        settings["slippage"],
                    )
                    ledgers[sid].add(fills, marks)
            processed += len(ticks)
            elapsed = time.perf_counter() - imported
            planned = min(coverage["rows"], limit) if limit else coverage["rows"]
            progress = {
                "symbol": symbol,
                "processed": processed,
                "planned": planned,
                "last_time": iso(previous_t),
                "replay_seconds": elapsed,
                "estimated_replay_seconds_remaining": elapsed / processed * (planned - processed),
                "status": "benchmark" if limit else "running",
            }
            json_write(output / "progress.json", progress)
            print(
                f"{symbol}: {processed:,}/{planned:,} ticks; replay ETA {progress['estimated_replay_seconds_remaining'] / 60:.1f} min",
                flush=True,
            )
        if not processed:
            raise ValueError("No ticks to replay")
        for minutes, s in states.items():
            e = snapshot(s, previous_t, 0, s[5], previous_t)
            # Last source bucket is incomplete: export it, do not arm a new signal.
            candle_writers[minutes].writerow([iso(s[1]), *s[2:7], *e[4:8], e[8], e[11], 0])
        for sid, direction, minutes, _rr in STRATEGIES:
            # No duplicate decision at end: use only the final liquidation branch.
            s = strategies[sid]
            if s[0]:
                e = last_events[minutes][0]
                price = e[20] * (1 - direction * settings["slippage"])
                quantity = s[0] * settings["unit"]
                fee = quantity * price * settings["fee"]
                s[4] += direction * (price - s[1]) * quantity - fee
                fills = np.array(
                    [[e[21], -direction * quantity, price, fee, 8, s[11], s[10], s[3]]]
                )
                ledgers[sid].add(fills, np.array([[e[21], s[4]]]))
                s[0] = 0
        summaries = []
        for sid, direction, minutes, rr in STRATEGIES:
            row = ledgers[sid].close(output)
            if not math.isclose(row["net_pnl"], strategies[sid][4], abs_tol=1e-5, rel_tol=1e-9):
                raise AssertionError("Strategy cash and trade ledger do not reconcile")
            summaries.append(
                {
                    "symbol": symbol,
                    "side": "buy" if direction == 1 else "sell",
                    "minutes": minutes,
                    "rr": rr,
                    **row,
                }
            )
        elapsed = time.perf_counter() - imported
        result = {
            "fingerprint": identity,
            "version": VERSION,
            "symbol": symbol,
            "coverage": {
                **coverage,
                "processed": processed,
                "gaps_over_5_minutes": gaps,
                "largest_gap_seconds": largest_gap,
                "equal_timestamp_pairs": equal_times,
            },
            "settings": settings,
            "import_seconds": imported - started,
            "replay_seconds": elapsed,
            "projected_full_replay_seconds": elapsed / processed * coverage["rows"],
            "benchmark_only": bool(limit),
            "strategies": summaries,
        }
        json_write(output / ("benchmark.json" if limit else "complete.json"), result)
        json_write(
            output / "progress.json",
            {"status": "benchmark_complete" if limit else "complete", "processed": processed},
        )
        return result
    finally:
        for f in candle_files.values():
            f.close()
        for ledger in ledgers.values():
            for f in ledger.files:
                f.close()
        db.close()


def report(output, results):
    rows = [row for r in results for row in r["strategies"]]
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    benchmark = any(r["benchmark_only"] for r in results)
    title = (
        "BENCHMARK SAMPLE - NOT FULL RESULTS"
        if benchmark
        else "Four crypto strategies: full supplied data"
    )
    content = [
        f"<!doctype html><meta charset='utf-8'><title>{title}</title>",
        "<style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:16px}td,th{padding:10px;text-align:right;border-bottom:1px solid #ccc}th:first-child,td:first-child{text-align:left}a{color:#165fc0}</style>",
        f"<h1>{title}</h1><p>Independent USD fixed-notional research simulations. Fees and slippage included; funding, tax, margin and liquidation excluded. HA is used for signals; fills use source trade prices.</p>",
        "<p><a href='comparison.csv'>Download comparison CSV</a></p><table><tr><th>Coin / strategy</th><th>Trades</th><th>Net USD</th><th>Fees USD</th><th>Max drawdown USD</th><th>Win %</th></tr>",
    ]
    for r in sorted(rows, key=lambda x: (x["symbol"], -x["net_pnl"])):
        label = html.escape(f"{r['symbol']} / {r['id']} ({r['side']} {r['minutes']}m)")
        content.append(
            f"<tr><td><a href='{r['symbol']}/{r['id']}_trades.csv'>{label}</a></td><td>{r['trades']}</td><td>{r['net_pnl']:,.2f}</td><td>{r['fees']:,.2f}</td><td>{r['max_drawdown']:,.2f}</td><td>{r['win_rate_pct']:.2f}</td></tr>"
        )
    content.append("</table><h2>Source coverage</h2>")
    for r in results:
        c = r["coverage"]
        content.append(
            f"<p>{r['symbol']}: {c['processed']:,}/{c['rows']:,} trades, {c['first']} to {c['last']}. Identical file copies skipped: {c['duplicate_files']}. Gaps over 5 minutes: {c['gaps_over_5_minutes']}. <a href='{r['symbol']}/candles_1m.csv'>1m candles</a> / <a href='{r['symbol']}/candles_5m.csv'>5m candles</a></p>"
        )
    (output / "index.html").write_text("\n".join(content), encoding="utf-8")
    json_write(output / "summary.json", results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="historical_data folder containing btcfut/ethfut/solusd/xautusdfut",
    )
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--symbols", nargs="+", choices=list(FOLDERS), default=list(FOLDERS))
    parser.add_argument("--memory", default="2GB", help="DuckDB memory budget PER worker")
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument(
        "--unit",
        type=float,
        default=0.01,
        help="Research base-asset quantity step, not an exchange contract size",
    )
    parser.add_argument("--fee", type=float, default=0.0005, help="Research fee per fill")
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument(
        "--benchmark-ticks",
        type=int,
        default=0,
        help="Replay first N sorted trades per coin; requires a separate output directory",
    )
    args = parser.parse_args()
    data, output = args.data.resolve(), args.output.resolve()
    if data == output or data in output.parents or output in data.parents:
        parser.error("Data and output must be separate, non-nested folders")
    for value in (args.capital, args.unit):
        if not math.isfinite(value) or value <= 0:
            parser.error("Capital and unit must be positive finite values")
    if not all(math.isfinite(x) and 0 <= x < 0.1 for x in (args.fee, args.slippage)):
        parser.error("Fee/slippage must be between 0 and 0.1")
    if args.benchmark_ticks < 0 or len(args.symbols) != len(set(args.symbols)):
        parser.error("Invalid benchmark size or duplicate symbols")
    for symbol in args.symbols:
        if not (data / FOLDERS[symbol]).is_dir():
            parser.error(f"Missing source folder: {data / FOLDERS[symbol]}")
    output.mkdir(parents=True, exist_ok=True)
    settings = {
        k: getattr(args, k)
        for k in ("memory", "capital", "unit", "fee", "slippage", "benchmark_ticks")
    }
    identity = {
        "version": VERSION,
        "data": str(data),
        "symbols": args.symbols,
        "settings": settings,
        "code_sha256": hash_file(Path(__file__)),
    }
    config_path = output / "run_config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != identity:
        parser.error(
            "Output belongs to different code/settings/data. Select a new --output directory."
        )
    # Windows byte-range lock releases on crashes; the lock file itself may persist.
    lock = (output / "writer.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        json_write(config_path, identity)
        print(f"Output: {output}; {args.workers} CPU workers; GPU unused", flush=True)
        print(f"Free output disk: {shutil.disk_usage(output).free / 1e9:.1f} GB", flush=True)
        results = []
        if args.workers == 1:
            for symbol in args.symbols:
                results.append(run_symbol(symbol, str(data), str(output), settings))
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                futures = [
                    pool.submit(run_symbol, symbol, str(data), str(output), settings)
                    for symbol in args.symbols
                ]
                for future in as_completed(futures):
                    results.append(future.result())
        report(output, results)
        print(f"Finished: {output / 'index.html'}", flush=True)
        if args.benchmark_ticks:
            for r in results:
                print(
                    f"{r['symbol']}: measured import {r['import_seconds'] / 60:.1f} min; projected full replay {r['projected_full_replay_seconds'] / 60:.1f} min (early sample estimate)"
                )
    finally:
        lock.close()


if __name__ == "__main__":
    main()
