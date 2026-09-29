"""Today's positive scanner basket replay, saved inside the application report DB.

Run: uv run python -m strategies.top_gain_volumes.backtest
Internal downloads are resumable; all generated research intermediates are temporary.
"""

import json
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "narasimha_pc_backtest"))
import run as engine_run

from services.scanner_strategy_reports import ReportStore

IST = ZoneInfo("Asia/Kolkata")


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from services.market_scanner_provider import (
        FyersScannerProvider,
        get_fyers_token,
        load_universe,
    )
    from services.market_scanner_service import rank_rows, validate_options

    day = datetime.now(IST).date().isoformat()
    with closing(sqlite3.connect("file:db/market_scanner_live.db?mode=ro", uri=True)) as conn:
        accounts = conn.execute(
            "SELECT user,snapshot FROM scanner_live_accounts WHERE broker='fyers'"
        ).fetchall()
    if len(accounts) != 1:
        raise RuntimeError("Exactly one FYERS scanner account is required")
    owner, payload = accounts[0]
    snapshot = json.loads(payload)
    if snapshot.get("session_date") != day or snapshot.get("state") != "completed":
        raise RuntimeError("A completed scanner snapshot from today is required")
    cache = ROOT / "db" / "scanner_backtest_cache" / day
    cache.mkdir(parents=True, exist_ok=True)
    selection_path = cache / "selection.json"
    if selection_path.exists():
        selected = json.loads(selection_path.read_text())
    else:
        ranked = rank_rows(snapshot["rows"], validate_options({"limit": 50, "positive_only": True}))
        selected = {
            "day": day,
            "snapshot_time": snapshot["updated_at"],
            "symbols": sorted(
                {r["symbol"] for g in ("volume_shockers", "top_gainers") for r in ranked[g]}
            ),
            "groups": {
                g: [r["symbol"] for r in ranked[g]] for g in ("volume_shockers", "top_gainers")
            },
        }
        selection_path.write_text(json.dumps(selected), encoding="utf-8")
    print(json.dumps(selected), flush=True)
    provider = FyersScannerProvider(get_fyers_token(owner))
    universe = {r["symbol"]: r for r in load_universe()}
    for i, symbol in enumerate(selected["symbols"]):
        dest = cache / f"{symbol}.json"
        if dest.exists():
            continue
        params = urlencode(
            {
                "symbol": universe[symbol]["broker_symbol"],
                "resolution": "1",
                "date_format": "1",
                "range_from": (datetime.fromisoformat(day) - timedelta(days=30)).date().isoformat(),
                "range_to": day,
                "cont_flag": "1",
            }
        )
        candles = provider._request("/data/history?" + params).get("candles")
        if not isinstance(candles, list) or not candles:
            raise RuntimeError(f"No candles for {symbol}")
        dest.write_text(json.dumps(candles), encoding="utf-8")
        print(f"Downloaded {i + 1}/{len(selected['symbols'])}: {symbol}", flush=True)
        time.sleep(0.6)
    with tempfile.TemporaryDirectory(prefix="scanner-replay-") as tmp:
        folder = Path(tmp)
        source = folder / "candles.duckdb"
        frames = []
        for symbol in selected["symbols"]:
            frame = pd.DataFrame(
                json.loads((cache / f"{symbol}.json").read_text()),
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            frame["symbol"], frame["exchange"], frame["interval"] = symbol, "NSE", "1m"
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True)
        with duckdb.connect(str(source)) as conn:
            conn.register("candles", combined)
            conn.execute("CREATE TABLE market_data AS SELECT * FROM candles")
        out = folder / "output"
        for name in ("candles", "ledgers", "coverage", "rejected"):
            (out / name).mkdir(parents=True)
        cfg = {
            "source": str(source),
            "start": day,
            "end": day,
            "symbols": selected["symbols"],
            "capital": 100000,
            "rr": 3,
            "stop_offset": 0.10,
            "fee_bps": 5,
            "slippage_bps": 5,
            "steps": 32,
            "asof_timestamp": int(time.time()),
        }
        meta = engine_run.metadata(selected["symbols"])
        cfg["metadata"] = meta
        trades, charts, coverage = [], {}, []
        for symbol in selected["symbols"]:
            engine_run.worker(symbol, cfg, meta[symbol], out)
            ledger = pd.read_csv(out / "ledgers" / f"{symbol}.csv")
            trades.extend(json.loads(ledger.to_json(orient="records")))
            cov = pd.read_csv(out / "coverage" / f"{symbol}.csv")
            coverage.extend(json.loads(cov.to_json(orient="records")))
            candles = pd.read_parquet(out / "candles" / f"{symbol}.parquet")
            charts[symbol] = json.loads(candles.to_json(orient="records"))
            # The independent entry verifier needs the pre-session HA/BB warmup.
            raw = combined.loc[
                combined.symbol.eq(symbol), ["timestamp", "open", "high", "low", "close", "volume"]
            ].to_numpy(dtype=float)
            minute = (raw[:, 0] + 19800) % 86400 // 60
            valid = (
                (minute >= 555)
                & (minute < 930)
                & (raw[:, 0] + 60 <= cfg["asof_timestamp"])
                & np.isfinite(raw).all(axis=1)
                & (raw[:, 1:5] > 0).all(axis=1)
                & (raw[:, 5] >= 0)
                & (raw[:, 2] >= raw[:, [1, 3, 4]].max(axis=1))
                & (raw[:, 3] <= raw[:, [1, 2, 4]].min(axis=1))
            )
            raw = np.ascontiguousarray(raw[valid])
            all_candles = pd.DataFrame(
                np.column_stack([raw, engine_run.indicators(raw)]),
                columns=["timestamp", "open", "high", "low", "close", "volume"]
                + engine_run.HA_COLS,
            )
            warmup = all_candles[all_candles.timestamp < engine_run.stamp(day)].copy()
            warmup["eligible_session"] = False
            pd.concat([warmup, candles]).to_parquet(
                out / "candles" / f"{symbol}.parquet", index=False
            )
        ledger = pd.DataFrame(trades)
        ledger.to_csv(out / "trades.csv", index=False)
        daily = ledger.groupby("path", as_index=False).net_pnl.sum()
        daily.to_csv(out / "daily.csv", index=False)
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
        (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        import verify_results

        verify_results.HERE = folder
        verify_results.main()
        report = {
            "id": f"backtest-{day}",
            "day": day,
            "kind": "Backtest",
            "status": "complete",
            "paths": ["OLHC", "OHLC"],
            "trades": trades,
            "candles": charts,
            "selection": selected,
            "coverage": coverage,
            "config": cfg,
            "verification": json.loads((out / "verification.json").read_text()),
            "source_sha256": manifest["source_sha256"],
            "note": "Historical exit times: 15:05 F&O / 15:20 other stocks. "
            "The live forward test uses 15:05 for all stocks from September 29. "
            "Retrospective afternoon basket: selection bias, not historical live scanner membership. "
            "1-minute OHLC paths approximate ticks; 5 bps slippage and 5 bps fees per fill are illustrative. "
            "Incomplete sessions excluded. Drawdown uses realized exits, not intratrade equity. "
            "₹1 lakh per trade; no total portfolio cap. Scenario results must not be added.",
        }
        store = ReportStore()
        try:
            store.save(owner, report)
        finally:
            store.close()
        print(json.dumps(report["metrics"], indent=2), flush=True)


if __name__ == "__main__":
    main()
