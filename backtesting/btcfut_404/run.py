"""Bounded-memory, checkpointed replay of the supplied 2024-2026 BTC archives."""

import argparse
import hashlib
import json
import os
import pickle
import shutil
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from backtesting.btcfut_404.engine import parameters, replay
from backtesting.btcfut_404.report import report, summarize
from backtesting.ethfut_404.data import write_json
from backtesting.ha_bb_vwap_v1_20260911.replay import Maker, definitions
from strategies.ha_bb_vwap_v1.models import Candle

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
SOURCE = Path("D:/Personal/OpenAlgo_Crypto/historical_data/btcfut")
UNIT = 0.01  # Research sizing, same granularity as the ETH comparison, now in BTC.


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_month(path):
    with zipfile.ZipFile(path) as archive:
        names = [x for x in archive.namelist() if x.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected one CSV: {path}")
        frame = pl.read_csv(archive.read(names[0])).with_columns(
            pl.col("timestamp").str.to_datetime(time_unit="us").dt.replace_time_zone("UTC")
        )
    if not frame.height or frame.filter(
        (pl.col("product_symbol") != "BTCUSD")
        | (pl.col("price") <= 0)
        | (pl.col("size") <= 0)
        | ~pl.col("price").is_finite()
        | ~pl.col("size").is_finite()
        | pl.any_horizontal(pl.all().is_null())
    ).height:
        raise ValueError(f"Invalid BTC data: {path}")
    frame = frame.sort("timestamp", maintain_order=True)
    return (
        frame["timestamp"].cast(pl.Int64).to_numpy(),
        frame["price"].to_numpy(),
        frame["size"].to_numpy(),
    )


def snapshots(minutes, ticks, maker, active):
    """Same causal Maker as ETH, preserving its state between bounded batches."""
    t, prices, volumes = ticks
    rows = []

    def save(bar, px, at):
        snap = maker.preview(bar)
        rows.append([
            bar.observed_at.timestamp() * 1e6, bar.start.timestamp() * 1e6,
            bar.complete, bar.close, snap.ha_open, snap.ha_high, snap.ha_low,
            snap.ha_close, *vars(snap.indicators).values(), px, at,
        ])

    for at, px, volume in zip(t, prices, volumes, strict=True):
        bucket = int(at) // (minutes * 60_000_000) * (minutes * 60_000_000)
        start = datetime.fromtimestamp(bucket / 1e6, UTC)
        now = datetime.fromtimestamp(int(at) / 1e6, UTC)
        if active is not None and active.start != start:
            bar = Candle(active.start, active.start + timedelta(minutes=minutes),
                         active.open, active.high, active.low, active.close,
                         active.volume, True)
            save(bar, px, at)
            maker.commit(bar)
            maker.ha, maker.raw, maker.array = maker.ha[-600:], maker.raw[-600:], maker.array[-600:]
            active = None
        active = Candle(start, now, active.open if active else px,
                        max(active.high, px) if active else px,
                        min(active.low, px) if active else px, px,
                        (active.volume if active else 0) + volume, False)
        save(active, px, at)
    return np.asarray(rows, dtype=float), active


def blank_stats():
    return {"daily": {}, "peak": 0.0, "dd": 0.0, "dd_pct": 0.0, "min": 0.0, "fills": 0}


def accumulate(stats, marks, fills):
    curve = marks[:, 1]
    peaks = np.maximum.accumulate(np.r_[stats["peak"], curve])[1:]
    stats["peak"] = float(peaks[-1])
    stats["dd"] = max(stats["dd"], float(np.max(peaks - curve)))
    stats["dd_pct"] = max(stats["dd_pct"], float(np.max((peaks - curve) / (100000 + peaks)) * 100))
    stats["min"] = min(stats["min"], float(curve.min()))
    days = marks[:, 0].astype(np.int64) // 86_400_000_000
    ends = np.r_[np.flatnonzero(days[1:] != days[:-1]), len(days) - 1]
    for i in ends:
        stats["daily"][int(days[i])] = float(curve[i])
    stats["fills"] += len(fills)


def checkpoint(state):
    temporary = OUT / "checkpoint.tmp"
    with temporary.open("wb") as stream:
        pickle.dump(state, stream, protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(OUT / "checkpoint.pkl")
    write_json(OUT / "progress.json", {
        "state": "running", "timeframe_minutes": state["minutes"],
        "archive_index": state["month"], "total_archives": len(state["manifest"]["sources"]),
        "ticks_in_archive": state["cursor"], "events_this_timeframe": state["offset"],
        "last_source_time": state.get("last_source_time"),
        "completed_timeframes": state["done"], "completed_versions": len(state["done"]) * 202,
        "updated_utc": datetime.now(UTC).isoformat(),
    })


def make_manifest(paths, defs):
    dependencies = [*HERE.glob("*.py"),
                    Path("backtesting/ethfut_404/data.py"),
                    Path("backtesting/ha_bb_vwap_v1_20260911/replay.py"),
                    *Path("strategies/ha_bb_vwap_v1").glob("*.py"),
                    *[Path(f) for _, _, f in defs]]
    return {
        "sources": [{"file": str(p), "bytes": p.stat().st_size, "sha256": digest(p)} for p in paths],
        "code": {str(p): digest(p) for p in dependencies},
        "configs": [{"id": f"S{i+1:03d}", "config": asdict(c)} for i, (c, _, _) in enumerate(defs)],
        "assumptions": {"capital_usd": 100000, "unit_btc": UNIT, "fee_per_side": 0.0005,
                        "slippage_per_side": 0.0005, "funding_included": False,
                        "tax_included": False, "vwap_reset": "UTC midnight", "trading": "24/7"},
    }


def audit_month(state, month, ticks):
    t, p, _ = ticks
    audit = state["audit"]
    previous = audit.get("last_us")
    if previous is not None and t[0] < previous:
        raise ValueError("Monthly archives overlap or are out of chronological order")
    gaps = np.diff(np.r_[previous, t] if previous is not None else t) / 1e6
    audit["rows"] += len(t)
    audit["gaps_over_5_minutes"] += int(np.sum(gaps > 300))
    audit["largest_gap_seconds"] = max(audit["largest_gap_seconds"], float(gaps.max(initial=0)))
    audit["equal_timestamp_pairs"] += int(np.sum(gaps == 0))
    audit.setdefault("first", datetime.fromtimestamp(int(t[0]) / 1e6, UTC).isoformat())
    audit["last"] = datetime.fromtimestamp(int(t[-1]) / 1e6, UTC).isoformat()
    audit["last_us"] = int(t[-1])
    audit["months"].append({"archive_index": month, "rows": len(t), "first": int(t[0]), "last": int(t[-1])})
    # Benchmark uses the actual BTC ticks, same research costs and sizing.
    b = state["bench"]
    if not b:
        entry = float(p[0] * 1.0005)
        q = float(np.floor(100000 / (entry * UNIT)) * UNIT)
        b.update(entry=entry, quantity=q, entry_fee=q * entry * 0.0005, stats=blank_stats())
    curve = b["quantity"] * (p - b["entry"]) - b["entry_fee"]
    if month == len(state["manifest"]["sources"]) - 1:
        exit_price = p[-1] * 0.9995
        b["exit_fee"] = float(b["quantity"] * exit_price * 0.0005)
        curve[-1] = b["quantity"] * (exit_price - b["entry"]) - b["entry_fee"] - b["exit_fee"]
    accumulate(b["stats"], np.column_stack((t, curve)), [])


def finish(state, defs):
    import pandas as pd

    summaries, daily = [], {}
    for i, (cfg, _, _) in enumerate(defs):
        sid = f"S{i+1:03d}"
        stats = state["stats"][sid]
        path = OUT / f"{sid}_fills.bin"
        fills = np.memmap(path, dtype="float64", mode="r", shape=(stats["fills"], 9)) if stats["fills"] else np.empty((0, 9))
        marks = np.array([[(day + 1) * 86_400_000_000 - 1, value] for day, value in sorted(stats["daily"].items())])
        summary, days = summarize(sid, cfg, fills, marks, OUT)
        summary.update(max_drawdown=stats["dd"], max_drawdown_pct=stats["dd_pct"], min_reference_equity=100000 + stats["min"])
        summaries.append(summary)
        daily[sid] = days
        print(f"Final reconciliation {i+1}/404 {sid}: net USD {summary['net_pnl']:,.2f}", flush=True)
    b = state["bench"]
    bs = b["stats"]
    series = pd.Series(bs["daily"]).sort_index()
    series.index = pd.to_datetime(series.index.to_numpy(), unit="D", utc=True)
    series = series.resample("1D").last().ffill()
    returns = series.diff().fillna(series.iloc[0]) / 100000
    downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2))
    bench = {"net_pnl": float(series.iloc[-1]), "return_pct": float(series.iloc[-1] / 1000),
             "max_drawdown": bs["dd"], "max_drawdown_pct": bs["dd_pct"],
             "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(365)) if returns.std(ddof=1) else None,
             "sortino": float(returns.mean() / downside * np.sqrt(365)) if downside else None,
             "fees": b["entry_fee"] + b["exit_fee"], "btc": b["quantity"],
             "daily": [{"date": str(k.date()), "cumulative_pnl": float(v)} for k, v in series.items()]}
    for src in state["manifest"]["sources"]:
        if digest(Path(src["file"])) != src["sha256"]:
            raise ValueError("Source changed during replay")
    write_json(OUT / "source_audit.json", state["audit"])
    write_json(OUT / "validation.json", {"completed": 404, "total": 404,
        "all_fill_ledgers_reconciled_with_vectorbt": True, "all_positions_closed": True,
        "source_sha256_rechecked": True, "drawdown": "Every source-derived replay observation",
        "completed_at": datetime.now(UTC).isoformat()})
    report(summaries, daily, state["audit"], bench, OUT)
    write_json(OUT / "progress.json", {"state": "complete", "completed_versions": 404, "total": 404})
    print(f"COMPLETE: {OUT / 'index.html'}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("batch-size must be positive")
    OUT.mkdir(exist_ok=True)
    # OS file lock is released automatically after a crash; stale lock files are harmless.
    import msvcrt
    lock = (OUT / "writer.lock").open("a+b")
    lock.seek(0)
    if lock.read(1) == b"":
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    paths = sorted(p for p in SOURCE.rglob("*.zip") if p.parent.name in {"2024", "2025", "2026"})
    if not paths:
        raise ValueError("No BTC archives found")
    defs = definitions()
    manifest = make_manifest(paths, defs)
    saved = OUT / "checkpoint.pkl"
    if saved.exists():
        if not args.resume:
            raise ValueError("Existing run found; use --resume")
        with saved.open("rb") as stream:
            state = pickle.load(stream)  # Only our locally produced checkpoint.
        if state["manifest"] != manifest:
            raise ValueError("Source/config/code fingerprint changed; cannot resume")
        for sid, stats in state["stats"].items():
            path = OUT / f"{sid}_fills.bin"
            if path.exists():
                with path.open("r+b") as stream:
                    stream.truncate(stats["fills"] * 9 * 8)
            elif stats["fills"]:
                raise ValueError(f"Missing committed ledger: {sid}")
    else:
        state = {"manifest": manifest, "minutes": 1, "month": 0, "cursor": 0, "offset": 0,
                 "maker": Maker([]), "active": None, "engines": {}, "stats": {}, "done": [],
                 "bench": {}, "audit": {"rows": 0, "gaps_over_5_minutes": 0,
                 "largest_gap_seconds": 0.0, "equal_timestamp_pairs": 0, "months": [],
                 "timezone_assumption": "UTC", "files": manifest["sources"]}}
        write_json(OUT / "manifest.json", manifest)
        checkpoint(state)
    for minutes in (1, 5):
        if minutes in state["done"]:
            continue
        selected = [(f"S{i+1:03d}", cfg) for i, (cfg, _, _) in enumerate(defs) if cfg.timeframe_minutes == minutes]
        for month in range(state["month"], len(paths)):
            print(f"Loading {minutes}m {paths[month].name}", flush=True)
            ticks = load_month(paths[month])
            if minutes == 1 and len(state["audit"]["months"]) <= month:
                audit_month(state, month, ticks)
            for start in range(state["cursor"], len(ticks[0]), args.batch_size):
                if shutil.disk_usage(OUT).free < 5 * 1024**3:
                    raise RuntimeError("Under 5 GiB free; stopped before next batch. Resume after freeing space.")
                end = min(start + args.batch_size, len(ticks[0]))
                final = month == len(paths) - 1 and end == len(ticks[0])
                events, state["active"] = snapshots(minutes, tuple(x[start:end] for x in ticks), state["maker"], state["active"])
                for sid, cfg in selected:
                    fills, marks, updated = replay(events, *parameters(cfg), unit=UNIT,
                        state=state["engines"].get(sid), final=final, offset=state["offset"])
                    state["engines"][sid] = updated
                    stats = state["stats"].setdefault(sid, blank_stats())
                    accumulate(stats, marks, fills)
                    with (OUT / f"{sid}_fills.bin").open("ab") as stream:
                        fills.tofile(stream)
                state.update(cursor=end, month=month, offset=state["offset"] + len(events),
                             last_source_time=datetime.fromtimestamp(int(ticks[0][end-1]) / 1e6, UTC).isoformat())
                checkpoint(state)
                print(f"{minutes}m archive {month+1}/{len(paths)}: {end:,}/{len(ticks[0]):,} ticks; 202 versions checkpointed through {state['last_source_time']}", flush=True)
            state.update(month=month + 1, cursor=0)
            checkpoint(state)
        state["done"].append(minutes)
        state.update(minutes=5, month=0, cursor=0, offset=0, maker=Maker([]), active=None)
        checkpoint(state)
    finish(state, defs)


if __name__ == "__main__":
    main()
