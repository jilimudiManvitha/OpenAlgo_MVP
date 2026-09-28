"""Freeze today's local scanner selection and fetch research candles only."""

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
IST = ZoneInfo("Asia/Kolkata")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--reselect", action="store_true")
    parser.add_argument(
        "--today-only",
        action="store_true",
        help="Merge today's fresh candles into existing warmup downloads",
    )
    args = parser.parse_args()
    day = "2026-09-25"
    if datetime.now(IST).date().isoformat() != day:
        raise ValueError("This collector is pinned to September 25, 2026")
    with closing(
        sqlite3.connect((ROOT / "db/market_scanner_live.db").as_uri() + "?mode=ro", uri=True)
    ) as db:
        accounts = db.execute(
            "SELECT user,snapshot FROM scanner_live_accounts WHERE broker='fyers'"
        ).fetchall()
    if len(accounts) != 1:
        raise ValueError("Exactly one Fyers scanner account is required")
    user, raw = accounts[0]
    selection_file = HERE / "selection.json"
    if not selection_file.exists() or args.reselect:
        snapshot = json.loads(raw)
        if snapshot["session_date"] != day:
            raise ValueError("Scanner snapshot is not today's")
        if snapshot.get("state") != "completed":
            raise ValueError("Wait for the scanner baseline pass to complete before selecting")
        if selection_file.exists():
            backup = HERE / f"selection_superseded_{time.time_ns()}.json"
            backup.write_bytes(selection_file.read_bytes())
        rows = snapshot["rows"]
        shockers = sorted(
            [r for r in rows if r.get("rvol") is not None and r["rvol"] > 1],
            key=lambda r: (-r["rvol"], -r["change_percent"], r["symbol"]),
        )[: args.limit]
        gainers = sorted(
            [r for r in rows if r["change_percent"] > 0],
            key=lambda r: (-r["change_percent"], r["symbol"]),
        )[: args.limit]
        selection = {
            "date": day,
            "selected_at": datetime.now(IST).isoformat(),
            "snapshot_updated_at": snapshot["updated_at"],
            "snapshot_state": snapshot["state"],
            "valid_quotes": snapshot["valid_quotes"],
            "universe": snapshot["total"],
            "limit_per_group": args.limit,
            "baseline_days": 5,
            "rvol_threshold_exclusive": 1,
            "selection_bias": "Retrospective fixed intraday snapshot; NOT historical real-time scanner membership",
            "volume_shockers": shockers,
            "top_gainers": gainers,
            "symbols": sorted({r["symbol"] for r in shockers + gainers}),
        }
        selection_file.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {k: selection[k] for k in ["selected_at", "valid_quotes", "universe", "symbols"]}
        ),
        flush=True,
    )
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from services.market_scanner_provider import (
        FyersScannerProvider,
        get_fyers_token,
        load_universe,
    )

    provider = FyersScannerProvider(get_fyers_token(user))
    universe = {row["symbol"]: row for row in load_universe()}
    folder = HERE / "downloads"
    folder.mkdir(exist_ok=True)
    start = (datetime.fromisoformat(day) - timedelta(days=30)).date().isoformat()
    for index, symbol in enumerate(selection["symbols"], 1):
        dest = folder / f"{symbol}.json"
        if dest.exists() and not args.refresh:
            continue
        instrument = universe[symbol]
        params = urlencode(
            {
                "symbol": instrument["broker_symbol"],
                "resolution": "1",
                "date_format": "1",
                "range_from": day if args.today_only else start,
                "range_to": day,
                "cont_flag": "1",
            }
        )
        response = provider._request("/data/history?" + params)
        candles = response.get("candles")
        if not isinstance(candles, list):
            raise ValueError(f"Missing candle array for {symbol}")
        if args.today_only:
            previous = json.loads(dest.read_text())
            midnight = int(datetime.fromisoformat(day).replace(tzinfo=IST).timestamp())
            candles = [c for c in previous["candles"] if c[0] < midnight] + candles
        dest.write_text(
            json.dumps(
                {"symbol": symbol, "fetched_at": datetime.now(IST).isoformat(), "candles": candles}
            ),
            encoding="utf-8",
        )
        print(f"{index}/{len(selection['symbols'])} {symbol}: {len(candles)} candles", flush=True)
        time.sleep(0.6)


if __name__ == "__main__":
    main()
