"""September 29, 2026 Nifty 500 volume-shocker and top-gainer backtest.

Read-only against the live scanner snapshot and the broker history API. Reuses
the unchanged engine, indicators, cost model and independent verifier from
narasimha_pc_backtest. No orders are sent and no existing report is overwritten.

Run from the repository root:
    .\\.venv\\Scripts\\python.exe narasimha_pc_backtest/today_20260929_nifty500/run_nifty500.py
"""

import csv
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "narasimha_pc_backtest"))

import run as engine_run
import verify_results

IST = ZoneInfo("Asia/Kolkata")
DAY = "2026-09-29"
LIMIT = 50
NIFTY_CSV = ROOT / "Stock_Symbols" / "ind_nifty500list.csv"
CACHE = ROOT / "db" / "scanner_backtest_cache" / f"{DAY}-nifty500"
OUT = HERE / "output"


def read_snapshot():
    """Completed FYERS scanner snapshot for today, read inside one transaction."""
    last = None
    for attempt in range(20):
        try:
            with closing(
                sqlite3.connect("file:db/market_scanner_live.db?mode=ro", uri=True)
            ) as conn:
                conn.execute("BEGIN")
                rows = conn.execute(
                    "SELECT user, broker, snapshot FROM scanner_live_accounts"
                ).fetchall()
            if rows:
                for user, broker, payload in rows:
                    if broker == "fyers":
                        snap = json.loads(payload)
                        if snap.get("session_date") == DAY and snap.get("state") == "completed":
                            return user, snap
                        raise RuntimeError(
                            f"Scanner snapshot is {snap.get('state')} for {snap.get('session_date')}"
                        )
        except sqlite3.OperationalError as exc:  # live writer holds the WAL
            last = exc
        time.sleep(0.5 + attempt * 0.2)
    raise RuntimeError(f"Could not read the scanner snapshot: {last}")


def nifty_symbols():
    with NIFTY_CSV.open(newline="", encoding="utf-8-sig") as fh:
        entries = list(csv.DictReader(fh))
    symbols = {e["Symbol"].strip() for e in entries if (e.get("Symbol") or "").strip()}
    if len(symbols) != 500:
        raise RuntimeError(f"Expected 500 Nifty 500 symbols, read {len(symbols)}")
    return symbols


def freeze(owner, snap):
    """Freeze today's Nifty 500 selection once; never re-select mid-run."""
    path = HERE / "selection.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    nifty = nifty_symbols()
    rows = snap["rows"]
    kept = [r for r in rows if r["symbol"] in nifty]
    missing = sorted(nifty - {r["symbol"] for r in rows})
    if len(kept) < 400:
        raise RuntimeError(f"Only {len(kept)} Nifty 500 rows in the snapshot")

    from services.market_scanner_service import rank_rows, validate_options

    ranked = rank_rows(kept, validate_options({"limit": LIMIT, "positive_only": True}))
    selection = {
        "day": DAY,
        "source": "Narasimha's completed local FYERS scanner snapshot",
        "universe_file": str(NIFTY_CSV.relative_to(ROOT)).replace("\\", "/"),
        "universe_size": len(nifty),
        "snapshot_updated_at": snap["updated_at"],
        "snapshot_valid_quotes": snap.get("valid_quotes"),
        "snapshot_total": snap.get("total"),
        "nifty_rows_in_snapshot": len(kept),
        "nifty_missing_from_snapshot": missing,
        "limit_per_group": LIMIT,
        "baseline_days": 5,
        "rvol_threshold_exclusive": 1,
        "positive_only": True,
        "selection_bias": (
            "Retrospective fixed end-of-day snapshot restricted to the Nifty 500 list. "
            "NOT historical real-time scanner membership."
        ),
        "volume_shockers": ranked["volume_shockers"],
        "top_gainers": ranked["top_gainers"],
        "matching_counts": ranked["matching_counts"],
        "symbols": sorted({r["symbol"] for r in ranked["volume_shockers"] + ranked["top_gainers"]}),
    }
    path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    print(f"Froze selection: {len(selection['symbols'])} unique symbols", flush=True)
    return selection


def selection_table(selection):
    shockers = {r["symbol"] for r in selection["volume_shockers"]}
    gainers = {r["symbol"] for r in selection["top_gainers"]}
    rows = []
    for r in selection["volume_shockers"] + selection["top_gainers"]:
        rows.append(
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "ltp": r.get("ltp"),
                "change_percent": r.get("change_percent"),
                "volume": r.get("volume"),
                "average_volume": r.get("average_volume"),
                "rvol": r.get("rvol"),
                "volume_shocker": r["symbol"] in shockers,
                "top_gainer": r["symbol"] in gainers,
            }
        )
    table = pd.DataFrame(rows).drop_duplicates("symbol").sort_values("symbol")
    table.to_csv(HERE / "selection_table.csv", index=False)
    return table


def download(owner, selection):
    from services.market_scanner_provider import (
        FyersScannerProvider,
        get_fyers_token,
        load_universe,
    )

    CACHE.mkdir(parents=True, exist_ok=True)
    provider = FyersScannerProvider(get_fyers_token(owner))
    universe = {r["symbol"]: r for r in load_universe()}
    start = (datetime.fromisoformat(DAY) - timedelta(days=30)).date().isoformat()
    for index, symbol in enumerate(selection["symbols"], 1):
        dest = CACHE / f"{symbol}.json"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        params = urlencode(
            {
                "symbol": universe[symbol]["broker_symbol"],
                "resolution": "1",
                "date_format": "1",
                "range_from": start,
                "range_to": DAY,
                "cont_flag": "1",
            }
        )
        candles = provider._request("/data/history?" + params).get("candles")
        if not isinstance(candles, list) or not candles:
            raise RuntimeError(f"No candles returned for {symbol}")
        dest.write_text(json.dumps(candles), encoding="utf-8")
        print(f"Downloaded {index}/{len(selection['symbols'])}: {symbol} ({len(candles)} candles)", flush=True)
        time.sleep(0.6)


def build_source(selection, path):
    frames = []
    for symbol in selection["symbols"]:
        frame = pd.DataFrame(
            json.loads((CACHE / f"{symbol}.json").read_text(encoding="utf-8")),
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        frame["symbol"], frame["exchange"], frame["interval"] = symbol, "NSE", "1m"
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if path.exists():
        path.unlink()
    with duckdb.connect(str(path)) as conn:
        conn.register("candles", combined)
        conn.execute("CREATE TABLE market_data AS SELECT * FROM candles")
    return combined


def prewarm_candles(combined, symbol, candles, out, asof):
    """Re-attach pre-session HA/BB warmup so the independent verifier can recheck signals."""
    raw = combined.loc[
        combined.symbol.eq(symbol), ["timestamp", "open", "high", "low", "close", "volume"]
    ].to_numpy(dtype=float)
    minute = (raw[:, 0] + 19800) % 86400 // 60
    valid = (
        (minute >= 555)
        & (minute < 930)
        & (raw[:, 0] + 60 <= asof)
        & np.isfinite(raw).all(axis=1)
        & (raw[:, 1:5] > 0).all(axis=1)
        & (raw[:, 5] >= 0)
        & (raw[:, 2] >= raw[:, [1, 3, 4]].max(axis=1))
        & (raw[:, 3] <= raw[:, [1, 2, 4]].min(axis=1))
    )
    raw = np.ascontiguousarray(raw[valid])
    all_candles = pd.DataFrame(
        np.column_stack([raw, engine_run.indicators(raw)]),
        columns=["timestamp", "open", "high", "low", "close", "volume"] + engine_run.HA_COLS,
    )
    warmup = all_candles[all_candles.timestamp < engine_run.stamp(DAY)].copy()
    warmup["eligible_session"] = False
    pd.concat([warmup, candles]).to_parquet(out / "candles" / f"{symbol}.parquet", index=False)


def main():
    print(f"Target session: {DAY}  (now {datetime.now(IST).isoformat()})", flush=True)
    owner, snap = read_snapshot()
    selection = freeze(owner, snap)
    table = selection_table(selection)
    print(
        f"Selection: {len(selection['volume_shockers'])} shockers, "
        f"{len(selection['top_gainers'])} gainers, "
        f"{len(selection['symbols'])} unique",
        flush=True,
    )

    download(owner, selection)

    if OUT.exists():
        import shutil

        shutil.rmtree(OUT)
    for name in ("candles", "ledgers", "coverage", "rejected"):
        (OUT / name).mkdir(parents=True)
    source = HERE / "candles.duckdb"
    combined = build_source(selection, source)
    asof = int(time.time())

    cfg = {
        "source": str(source),
        "start": DAY,
        "end": DAY,
        "symbols": selection["symbols"],
        "capital": 100000,
        "rr": 3,
        "stop_offset": 0.10,
        "fee_bps": 5,
        "slippage_bps": 5,
        "steps": 32,
        "asof_timestamp": asof,
    }
    meta = engine_run.metadata(selection["symbols"])
    cfg["metadata"] = meta

    trades, coverage, audits, charts = [], [], [], {}
    for index, symbol in enumerate(selection["symbols"], 1):
        audits.append(engine_run.worker(symbol, cfg, meta[symbol], OUT))
        ledger = pd.read_csv(OUT / "ledgers" / f"{symbol}.csv")
        if len(ledger):
            trades.extend(json.loads(ledger.to_json(orient="records")))
        cov = pd.read_csv(OUT / "coverage" / f"{symbol}.csv")
        coverage.extend(json.loads(cov.to_json(orient="records")))
        candles = pd.read_parquet(OUT / "candles" / f"{symbol}.parquet")
        prewarm_candles(combined, symbol, candles, OUT, asof)
        charts[symbol] = json.loads(candles.to_json(orient="records"))
        print(f"Replayed {index}/{len(selection['symbols'])}: {symbol}", flush=True)

    ledger = pd.DataFrame(trades)
    ledger.to_csv(OUT / "trades.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    ledger.groupby("path", as_index=False).net_pnl.sum().to_csv(OUT / "daily.csv", index=False)
    pd.DataFrame(audits).to_csv(OUT / "audit.csv", index=False)

    manifest = {
        "status": "COMPLETE_AVAILABLE_DATA",
        "config": cfg,
        "source_sha256": engine_run.digest(source),
        "summary": [
            {
                "path": p,
                "trades": int(ledger.path.eq(p).sum()),
                "net_pnl": float(ledger.loc[ledger.path.eq(p), "net_pnl"].sum()),
            }
            for p in ("OLHC", "OHLC")
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    verify_results.HERE = HERE
    verify_results.main()

    report = {
        "day": DAY,
        "universe": "Nifty 500 (Stock_Symbols/ind_nifty500list.csv)",
        "selection": selection,
        "config": cfg,
        "trades": trades,
        "coverage": coverage,
        "audit": audits,
        "summary": summarize(ledger, coverage, selection),
    }
    (HERE / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2), flush=True)


def summarize(ledger, coverage, selection):
    shockers = [r["symbol"] for r in selection["volume_shockers"]]
    gainers = [r["symbol"] for r in selection["top_gainers"]]
    cov = pd.DataFrame(coverage)
    eligible = set(cov.loc[cov.eligible, "symbol"])
    out = {
        "day": DAY,
        "selected": {
            "volume_shockers": len(shockers),
            "top_gainers": len(gainers),
            "unique": len(selection["symbols"]),
        },
        "excluded_no_quote": selection["nifty_missing_from_snapshot"],
        "buckets": {},
    }
    for name, symbols in (
        ("Volume shockers", shockers),
        ("Top gainers", gainers),
        ("Deduplicated union", selection["symbols"]),
    ):
        elig = [s for s in symbols if s in eligible]
        entry = {
            "selected": len(symbols),
            "eligible": len(elig),
            "excluded_incomplete": len(symbols) - len(elig),
        }
        for path in ("OLHC", "OHLC"):
            sub = ledger[(ledger.path == path) & (ledger.symbol.isin(symbols))]
            entry[path] = {
                "trades": int(len(sub)),
                "winners": int((sub.net_pnl > 0).sum()),
                "net_pnl": round(float(sub.net_pnl.sum()), 2),
            }
        out["buckets"][name] = entry
    first = ledger[ledger.path == "OLHC"]
    out["overall_OLHC"] = {
        "trades": int(len(first)),
        "winners": int((first.net_pnl > 0).sum()),
        "win_rate_pct": round(float((first.net_pnl > 0).mean() * 100), 2) if len(first) else None,
        "gross_pnl": round(float(first.gross_pnl.sum()), 2),
        "fees": round(float(first.fees.sum()), 2),
        "net_pnl": round(float(first.net_pnl.sum()), 2),
        "profit_factor": round(
            float(first.loc[first.net_pnl > 0, "net_pnl"].sum()
                  / abs(first.loc[first.net_pnl < 0, "net_pnl"].sum())), 3
        )
        if (first.net_pnl < 0).any() and (first.net_pnl > 0).any() else None,
        "best": round(float(first.net_pnl.max()), 2) if len(first) else None,
        "worst": round(float(first.net_pnl.min()), 2) if len(first) else None,
    }
    return out


if __name__ == "__main__":
    main()
