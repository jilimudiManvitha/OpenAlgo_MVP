"""Read only the supplied archives and construct causal trade snapshots."""

import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

from backtesting.ha_bb_vwap_v1_20260911.replay import Maker
from strategies.ha_bb_vwap_v1.models import Candle

SOURCE = Path("D:/Personal/OpenAlgo_Crypto/historical_data/ethfut")
HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
# time(us), bucket(us), complete, raw close, HA OHLC, 12 indicators,
# executable price, execution time(us). Completed-bar orders fill at next source trade.
WIDTH = 22


def read_ticks():
    frames, audit = [], []
    for path in sorted(SOURCE.rglob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".csv"):
                    continue
                frame = pl.read_csv(archive.read(name)).with_columns(
                    pl.col("timestamp").str.to_datetime(time_unit="us").dt.replace_time_zone("UTC")
                )
                if frame.filter(
                    (pl.col("product_symbol") != "ETHUSD")
                    | (pl.col("price") <= 0)
                    | (pl.col("size") <= 0)
                    | pl.any_horizontal(pl.all().is_null())
                ).height:
                    raise ValueError(f"Invalid source rows: {path}")
                audit.append(
                    {
                        "file": str(path),
                        "member": name,
                        "rows": frame.height,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
                frames.append(frame)
    if not frames:
        raise ValueError("No trade archives found")
    frame = pl.concat(frames).sort("timestamp", maintain_order=True)
    # Identical trades are retained: no trade IDs exist to prove duplication.
    t = frame["timestamp"].cast(pl.Int64).to_numpy()
    p, v = frame["price"].to_numpy(), frame["size"].to_numpy()
    gaps = np.diff(t) / 1e6
    audit = {
        "files": audit,
        "rows": len(t),
        "first": frame["timestamp"][0].isoformat(),
        "last": frame["timestamp"][-1].isoformat(),
        "timezone_assumption": "UTC",
        "equal_timestamp_pairs": int(np.sum(gaps == 0)),
        "gaps_over_5_minutes": int(np.sum(gaps > 300)),
        "largest_gap_seconds": float(gaps.max()),
        "empty_years": [2025, 2026],
    }
    return t, p, v, audit


def prepare(minutes, ticks, output):
    t, p, v = ticks
    buckets = t // (minutes * 60_000_000) * (minutes * 60_000_000)
    count = len(t) + int(np.sum(buckets[1:] != buckets[:-1]))
    target = output / f"events_{minutes}m.npy"
    events = np.lib.format.open_memmap(target, mode="w+", dtype="float64", shape=(count, WIDTH))
    maker = Maker([])
    active = None
    row = 0
    day = None

    def save(bar, executable, execution_time):
        nonlocal row
        snap = maker.preview(bar)
        values = snap.indicators
        events[row] = [
            bar.observed_at.timestamp() * 1e6,
            bar.start.timestamp() * 1e6,
            bar.complete,
            bar.close,
            snap.ha_open,
            snap.ha_high,
            snap.ha_low,
            snap.ha_close,
            *vars(values).values(),
            executable,
            execution_time,
        ]
        row += 1

    for i in range(len(t)):
        start = datetime.fromtimestamp(int(buckets[i]) / 1e6, UTC)
        now = datetime.fromtimestamp(int(t[i]) / 1e6, UTC)
        if active is not None and active.start != start:
            final = Candle(
                active.start,
                active.start + timedelta(minutes=minutes),
                active.open,
                active.high,
                active.low,
                active.close,
                active.volume,
                True,
            )
            save(final, p[i], t[i])
            maker.commit(final)
            # Continuous HA seed and UTC VWAP totals survive; indicators use at most
            # 600 completed bars + the forming bar, matching the prior research warmup.
            maker.ha = maker.ha[-600:]
            maker.raw = maker.raw[-600:]
            maker.array = maker.array[-600:]
            active = None
        active = Candle(
            start,
            now,
            active.open if active else p[i],
            max(active.high, p[i]) if active else p[i],
            min(active.low, p[i]) if active else p[i],
            p[i],
            (active.volume if active else 0) + v[i],
            False,
        )
        save(active, p[i], t[i])
        if now.date() != day:
            day = now.date()
            print(f"{minutes}m snapshots: {day}, {i:,}/{len(t):,} source trades", flush=True)
    assert row == count
    events.flush()
    return target


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8")
