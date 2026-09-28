"""Read-only DuckDB research runner. Run from any working directory."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from engine import indicators, replay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
IST = timezone(timedelta(hours=5, minutes=30))
COLS = [
    "signal_ts",
    "entry_ts",
    "exit_ts",
    "entry",
    "exit",
    "quantity",
    "stop",
    "target",
    "gross_pnl",
    "fees",
    "net_pnl",
    "reason_code",
    "entry_reference",
    "exit_reference",
    "slippage_cost",
    "signal_index",
    "entry_index",
    "exit_index",
]
HA_COLS = ["ha_open", "ha_high", "ha_low", "ha_close", "bb_upper", "bb_middle", "bb_lower", "vwap"]


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=IST).timestamp())


def connect(path):
    return duckdb.connect(str(path), read_only=True, config={"threads": 2, "memory_limit": "2GB"})


def metadata(symbols):
    db = sqlite3.connect((ROOT / "db/openalgo.db").as_uri() + "?mode=ro", uri=True)
    try:
        fo = {x[0] for x in db.execute("SELECT DISTINCT name FROM symtoken WHERE exchange='NFO'")}
        result = {}
        for symbol in symbols:
            row = db.execute(
                "SELECT tick_size FROM symtoken WHERE exchange='NSE' AND symbol=?", [symbol]
            ).fetchone()
            if not row or not row[0] or row[0] <= 0:
                raise ValueError(f"Missing tick metadata: {symbol}")
            result[symbol] = {
                "tick": row[0],
                "is_fo": symbol in fo,
                "provenance": "current local symtoken snapshot; not historical membership",
            }
        return result
    finally:
        db.close()


def validate(raw, cutoff, start_ts, end_ts):
    if not np.isfinite(raw).all():
        raise ValueError("Nonfinite source data")
    if len(raw) and (np.any(np.diff(raw[:, 0]) <= 0) or np.any(raw[:, 0] % 60)):
        raise ValueError("Duplicate/unordered/non-minute timestamps")
    if np.any(raw[:, 1:5] <= 0) or np.any(raw[:, 5] < 0):
        raise ValueError("Invalid source price/volume")
    if np.any(raw[:, 2] < np.max(raw[:, [1, 3, 4]], axis=1)) or np.any(
        raw[:, 3] > np.min(raw[:, [1, 2, 4]], axis=1)
    ):
        raise ValueError("Invalid source OHLC")
    days = ((raw[:, 0] + 19800) // 86400).astype(np.int64)
    mins = ((raw[:, 0] + 19800) % 86400 // 60).astype(np.int64)
    allowed = np.zeros(len(raw), dtype=np.bool_)
    coverage = []
    for day in np.unique(days):
        ix = np.flatnonzero(days == day)
        if raw[ix[-1], 0] < start_ts or raw[ix[0], 0] >= end_ts:
            continue
        observed = set(mins[ix].tolist())
        missing = len(set(range(555, cutoff + 1)) - observed)
        okay = missing == 0
        allowed[ix] = okay
        coverage.append(
            {
                "date": datetime.fromtimestamp(day * 86400, UTC).date().isoformat(),
                "rows": len(ix),
                "missing_to_cutoff": missing,
                "missing_regular_minutes": 375 - len(observed),
                "eligible": okay,
                "zero_volume_minutes": int((raw[ix, 5] == 0).sum()),
            }
        )
    return allowed, coverage


def worker(symbol, config, meta, out):
    started = time.perf_counter()
    cutoff = 905 if meta["is_fo"] else 920
    start_ts, end_ts = stamp(config["start"]), stamp(config["end"]) + 86400
    with connect(config["source"]) as db:
        df = db.execute(
            """SELECT timestamp,open,high,low,close,volume FROM market_data
            WHERE symbol=? AND exchange='NSE' AND interval='1m' AND timestamp>=? AND timestamp<?
            ORDER BY timestamp""",
            [symbol, start_ts - 30 * 86400, end_ts],
        ).fetchdf()
        if df.empty:
            raise ValueError(f"No data for {symbol}")
        raw_all = df.to_numpy(dtype=np.float64)
        minutes = (raw_all[:, 0] + 19800) % 86400 // 60
        regular = (minutes >= 555) & (minutes < 930)
        # Do not use an unfinished current minute from the live download.
        complete = raw_all[:, 0] + 60 <= config["asof_timestamp"]
        candidate = raw_all[regular & complete]
        valid = (
            np.isfinite(candidate).all(axis=1)
            & (candidate[:, 1:5] > 0).all(axis=1)
            & (candidate[:, 5] >= 0)
            & (candidate[:, 2] >= np.max(candidate[:, [1, 3, 4]], axis=1))
            & (candidate[:, 3] <= np.min(candidate[:, [1, 2, 4]], axis=1))
        )
        rejected = candidate[~valid]
        pd.DataFrame(rejected, columns=df.columns).to_csv(
            out / "rejected" / f"{symbol}.csv", index=False
        )
        bad_days = set(((rejected[:, 0] + 19800) // 86400).astype(np.int64).tolist())
        raw = np.ascontiguousarray(candidate[valid])
        allowed, coverage = validate(raw, cutoff, start_ts, end_ts)
        for row in coverage:
            day = (stamp(row["date"]) + 19800) // 86400
            row["invalid_source_rows"] = int((((rejected[:, 0] + 19800) // 86400) == day).sum())
            if day in bad_days:
                row["eligible"] = False
        allowed[np.isin((raw[:, 0] + 19800) // 86400, list(bad_days))] = False
        ha = indicators(raw)
        frames = []
        for p, name in enumerate(["OLHC", "OHLC"]):
            trades = replay(
                raw,
                ha,
                allowed,
                cutoff,
                p,
                meta["tick"],
                config["slippage_bps"] / 10000,
                config["fee_bps"] / 10000,
                config["capital"],
                config["rr"],
                config["stop_offset"],
                config["steps"],
            )
            f = pd.DataFrame(trades, columns=COLS)
            f["symbol"], f["path"] = symbol, name
            for field in ["signal", "entry", "exit"]:
                f[field + "_time"] = (
                    pd.to_datetime(f[field + "_ts"], unit="s", utc=True)
                    .dt.tz_convert("Asia/Kolkata")
                    .dt.strftime("%Y-%m-%d %H:%M:%S.%f")
                )
            f["date"] = f.entry_time.str[:10]
            f["reason"] = f.reason_code.map({1: "STOP", 2: "TARGET", 3: "SQUARE_OFF"})
            f["notional"] = f.entry * f.quantity
            f["raw_reference_pnl"] = (f.exit_reference - f.entry_reference) * f.quantity
            f["entry_final_has_lower_wick"] = [
                bool(ha[int(i), 2] < ha[int(i), 0] - 1e-9) for i in f.entry_index
            ]
            frames.append(f)
        candles = pd.DataFrame(np.column_stack([raw, ha]), columns=list(df.columns) + HA_COLS)
        candles["timestamp"] = candles.timestamp.astype(np.int64)
        candles["eligible_session"] = allowed
        candles = candles[candles.timestamp >= start_ts]
        db.register("converted", candles)
        # DuckDB parameter binding works for COPY destination paths.
        db.execute(
            "COPY converted TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(out / "candles" / f"{symbol}.parquet")],
        )
        pd.concat(frames, ignore_index=True).to_csv(out / "ledgers" / f"{symbol}.csv", index=False)
        cov = pd.DataFrame(coverage)
        cov["symbol"] = symbol
        cov.to_csv(out / "coverage" / f"{symbol}.csv", index=False)
        return {
            "symbol": symbol,
            "source_rows": len(raw_all),
            "rejected_invalid_rows": len(rejected),
            "regular_completed_rows": len(raw),
            "outside_session_rows": int((~regular).sum()),
            "incomplete_minute_rows": int((~complete & regular).sum()),
            "first": datetime.fromtimestamp(raw[0, 0], IST).isoformat(),
            "last": datetime.fromtimestamp(raw[-1, 0], IST).isoformat(),
            "eligible_sessions": int(cov.eligible.sum()),
            "excluded_sessions": int((~cov.eligible).sum()),
            "input_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
            "trades": {
                f.path.iloc[0] if len(f) else name: len(f)
                for f, name in zip(frames, ["OLHC", "OHLC"], strict=True)
            },
            "seconds": time.perf_counter() - started,
        }


def summarize(out, config, audits):
    trades = pd.concat(
        [pd.read_csv(out / "ledgers" / f"{s}.csv") for s in config["symbols"]], ignore_index=True
    )
    trades = trades.sort_values(["path", "entry_ts", "symbol"]).reset_index(drop=True)
    trades["id"] = np.arange(len(trades))
    trades.to_csv(out / "trades.csv", index=False)
    cov = pd.concat(
        [pd.read_csv(out / "coverage" / f"{s}.csv") for s in config["symbols"]], ignore_index=True
    )
    # Include absent symbol-days on the union of dates observed in this source.
    # This is not an authoritative exchange calendar.
    grid = pd.MultiIndex.from_product(
        [config["symbols"], sorted(cov.date.unique())], names=["symbol", "date"]
    ).to_frame(index=False)
    cov = grid.merge(cov, how="left", on=["symbol", "date"])
    cov["status"] = np.where(
        cov.rows.isna(),
        "NO_SOURCE_SESSION",
        np.where(
            cov.invalid_source_rows.gt(0),
            "INVALID_SOURCE_CANDLE",
            np.where(cov.eligible.eq(True), "ELIGIBLE", "INCOMPLETE_TO_CUTOFF"),
        ),
    )
    cov.to_csv(out / "coverage.csv", index=False)
    daily = trades.groupby(["path", "date"], as_index=False).agg(
        net_pnl=("net_pnl", "sum"),
        gross_pnl=("gross_pnl", "sum"),
        fees=("fees", "sum"),
        trades=("id", "size"),
    )
    calendar = pd.MultiIndex.from_product(
        [["OLHC", "OHLC"], sorted(cov.date.unique())], names=["path", "date"]
    ).to_frame(index=False)
    daily = calendar.merge(daily, how="left", on=["path", "date"]).fillna(0)
    daily["cumulative"] = daily.groupby("path").net_pnl.cumsum()
    daily["drawdown"] = daily.cumulative - daily.groupby("path").cumulative.cummax().clip(lower=0)
    daily.to_csv(out / "daily.csv", index=False)
    summary = []
    for path in ["OLHC", "OHLC"]:
        f, d = trades[trades.path == path], daily[daily.path == path]
        wins, losses = f.loc[f.net_pnl > 0, "net_pnl"].sum(), -f.loc[f.net_pnl < 0, "net_pnl"].sum()
        events = [(r.entry_ts, 1, r.notional) for r in f.itertuples()] + [
            (r.exit_ts, -1, -r.notional) for r in f.itertuples()
        ]
        current = peak = 0.0
        open_count = peak_count = 0
        for _, delta, amount in sorted(events):
            current += amount
            open_count += delta
            peak, peak_count = max(peak, current), max(peak_count, open_count)
        summary.append(
            {
                "path": path,
                "trades": len(f),
                "gross_pnl": float(f.gross_pnl.sum()),
                "fees": float(f.fees.sum()),
                "net_pnl": float(f.net_pnl.sum()),
                "slippage_cost": float(f.slippage_cost.sum()),
                "win_rate": float((f.net_pnl > 0).mean() * 100) if len(f) else 0,
                "profit_factor": float(wins / losses) if losses else None,
                "daily_close_max_drawdown": float(-d.drawdown.min()),
                "peak_simultaneous_notional": peak,
                "peak_simultaneous_positions": peak_count,
                "best_trade": float(f.net_pnl.max()) if len(f) else 0,
                "worst_trade": float(f.net_pnl.min()) if len(f) else 0,
            }
        )
    pd.DataFrame(summary).to_csv(out / "summary.csv", index=False)
    for group, filename in [
        ("symbol", "by_symbol.csv"),
        ("year", "by_year.csv"),
        ("month", "by_month.csv"),
    ]:
        trades["year"], trades["month"] = trades.date.str[:4], trades.date.str[:7]
        trades.groupby(["path", group]).agg(
            trades=("id", "size"),
            gross_pnl=("gross_pnl", "sum"),
            fees=("fees", "sum"),
            net_pnl=("net_pnl", "sum"),
        ).to_csv(out / filename)
    payload = {
        "config": config,
        "summary": summary,
        "audits": audits,
        "coverage_status": cov.status.value_counts().to_dict(),
        "daily": json.loads(daily.to_json(orient="records")),
        "trades": json.loads(
            trades.drop(columns=["signal_index", "entry_index", "exit_index"]).to_json(
                orient="records"
            )
        ),
    }
    (out / "report-data.js").write_text(
        "window.REPORT=" + json.dumps(payload, allow_nan=False) + ";", encoding="utf-8"
    )
    from plotly.offline import get_plotlyjs

    (out / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    shutil.copyfile(HERE / "dashboard.html", out / "index.html")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "db/historify.duckdb")
    parser.add_argument("--output", type=Path, default=HERE / "output")
    parser.add_argument("--start", default="2021-09-25")
    parser.add_argument("--end", default="2026-09-25")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--fee-bps", type=float, default=5)
    parser.add_argument("--slippage-bps", type=float, default=5)
    args = parser.parse_args()
    if (
        args.workers < 1
        or args.steps < 1
        or min(args.fee_bps, args.slippage_bps) < 0
        or args.start > args.end
    ):
        parser.error("Invalid workers, steps, costs or date range")
    source = args.source.resolve()
    wal = Path(str(source) + ".wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError(
            "Source has a nonempty WAL. Use a checkpointed snapshot; do not delete WAL."
        )
    symbols = [
        x.split(",")[0].strip()
        for x in (ROOT / "nifty50_symbols_For_HistoricData.txt").read_text().splitlines()
        if x.strip()
    ]
    if args.symbols:
        if not set(args.symbols) <= set(symbols):
            raise ValueError("Only requested Nifty list symbols are accepted")
        symbols = args.symbols
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("Output must be empty; preserve prior runs and choose a new --output")
    for folder in ["candles", "ledgers", "coverage", "rejected"]:
        (out / folder).mkdir()
    config = {
        "strategy": "BUY_HA1m_BB20x2_VWAP_NoLowerWick_SLsignalLowMinus0.10_TP3R_OnePerDay",
        "source": str(source),
        "start": args.start,
        "end": args.end,
        "symbols": symbols,
        "capital": 100000,
        "rr": 3,
        "stop_offset": 0.10,
        "fee_bps": args.fee_bps,
        "slippage_bps": args.slippage_bps,
        "steps": args.steps,
        "workers": args.workers,
        "asof_timestamp": int(time.time()),
        "metadata": metadata(symbols),
    }
    start = time.perf_counter()
    manifest = {
        "status": "RUNNING",
        "config": config,
        "code_sha256": {p.name: digest(p) for p in HERE.glob("*.py")},
    }
    manifest_path = out / "manifest.json"
    try:
        # Hold a read-only source connection for the complete experiment.
        with connect(source):
            manifest["source_sha256"] = digest(source)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            # Compile once before launching independent Numba nogil CPU threads.
            raw = np.array(
                [[stamp("2021-09-27") + 33300 + i * 60, 100, 101, 99, 100, 100] for i in range(25)],
                dtype=float,
            )
            ha = indicators(raw)
            replay(
                raw,
                ha,
                np.zeros(25, dtype=np.bool_),
                905,
                0,
                0.05,
                0.0005,
                0.0005,
                100000.0,
                3.0,
                0.1,
                args.steps,
            )
            audits = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(worker, s, config, config["metadata"][s], out): s for s in symbols
                }
                for future in as_completed(futures):
                    result = future.result()
                    audits.append(result)
                    print(
                        f"{len(audits)}/{len(symbols)} {result['symbol']}: {result['trades']} ({result['seconds']:.1f}s)",
                        flush=True,
                    )
                    (out / "progress.json").write_text(
                        json.dumps(audits, indent=2), encoding="utf-8"
                    )
            if digest(source) != manifest["source_sha256"]:
                raise ValueError("Source content changed during the run")
            summary = summarize(out, config, sorted(audits, key=lambda x: x["symbol"]))
        manifest.update(
            status="COMPLETE_AVAILABLE_DATA",
            seconds=time.perf_counter() - start,
            audits=audits,
            summary=summary,
        )
        print(
            json.dumps({"seconds": manifest["seconds"], "summary": summary}, indent=2), flush=True
        )
    except BaseException as exc:
        manifest.update(status="FAILED_OR_INTERRUPTED", error=str(exc))
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
