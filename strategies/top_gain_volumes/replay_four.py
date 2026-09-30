"""Replay the eight scheduled variants on dated inputs without placing orders.

Two explicitly modeled OHLC paths; no future candles or final-candle wick tests
are used at entry. An afternoon-selected scanner basket remains selection-biased.
"""

import argparse
import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from strategies.top_gain_volumes.profiles import PROFILES, ROOT, nifty500_symbols, weekday_symbols
from strategies.top_gain_volumes.runtime import IST, TickCandles, enter, exit_trade


def replay(symbol, raw, day, tick, trailing=False, path="OLHC", steps=8, timeframe_minutes=1):
    start = datetime.fromisoformat(day).replace(hour=9, minute=15, tzinfo=IST).timestamp()
    cutoff = start + (900 - 555) * 60
    prior = [r for r in raw if r[0] < start and 555 <= (r[0] + 19800) % 86400 // 60 < 930]
    current = [r for r in raw if start <= r[0] <= cutoff]
    from strategies.top_gain_volumes.history import aggregate_minutes

    if len(aggregate_minutes(prior, timeframe_minutes, start)) < 20:
        return [], [], {"symbol": symbol, "eligible": False, "reason": "insufficient_warmup"}
    expected = list(range(int(start), int(cutoff) + 1, 60))
    if [int(r[0]) for r in current] != expected:
        return (
            [],
            [],
            {"symbol": symbol, "eligible": False, "reason": "missing_or_duplicate_minutes"},
        )
    if any(
        len(r) != 6
        or not all(math.isfinite(v) for v in r)
        or min(r[1:5]) <= 0
        or r[5] < 0
        or r[2] < max(r[1:5])
        or r[3] > min(r[1:5])
        for r in prior + current
    ):
        return [], [], {"symbol": symbol, "eligible": False, "reason": "invalid_ohlcv"}
    candle = TickCandles(prior, start, strict_vwap=trailing, timeframe_minutes=timeframe_minutes)
    trades, position, used_signal = [], None, None
    cumulative = 0.0
    for row in current:
        stamp, op, high, low, close, volume = row
        vertices = (op, low, high, close) if path == "OLHC" else (op, high, low, close)
        samples = [(0.0, op)]
        if stamp < cutoff:
            samples.extend(
                (
                    (leg + step / steps) / 3,
                    vertices[leg] + (vertices[leg + 1] - vertices[leg]) * step / steps,
                )
                for leg in range(3)
                for step in range(1, steps + 1)
            )
        for fraction, price in samples:
            observed = stamp + fraction * 59.999
            qualifies = candle.tick(observed, price, cumulative + fraction * volume)
            if position is not None:
                if exit_trade(position, observed, price, tick, 900, trailing, candle.middle):
                    position = None
            elif qualifies and stamp < cutoff and candle.signal[0] != used_signal:
                position = enter(symbol, observed, price, candle, tick)
                used_signal = candle.signal[0]
                if position:
                    position["path"] = path
                    position["signal_low"] = candle.signal[2]
                    trades.append(position)
        cumulative += volume
    assert all(t["exit_ts"] is not None for t in trades), "Complete replay must close positions"
    return trades, list(candle.chart), {"symbol": symbol, "eligible": True}


def verify_ledger(trades):
    last_exit = {}
    seen = set()
    for trade in sorted(trades, key=lambda t: (t["path"], t["symbol"], t["entry_ts"])):
        key = (trade["path"], trade["symbol"])
        assert trade["entry"] * trade["quantity"] <= 10000 + 1e-6
        assert trade["quantity"] > 0 and int(trade["quantity"]) == trade["quantity"]
        interval = trade.get("timeframe_minutes", 1) * 60
        assert (
            trade["signal_ts"] + interval <= trade["entry_ts"] < trade["signal_ts"] + 2 * interval
        )
        assert trade["entry_ts"] >= last_exit.get(key, 0)
        assert (key, trade["signal_ts"]) not in seen
        seen.add((key, trade["signal_ts"]))
        assert trade["exit_ts"] >= trade["entry_ts"]
        assert trade["stop"] <= trade["signal_low"] * 0.9997 + 1e-7
        assert trade["target"] >= trade["entry"] + 3 * (trade["entry"] - trade["stop"]) - 1e-7
        assert (
            abs(
                trade["net_pnl"]
                - ((trade["exit"] - trade["entry"]) * trade["quantity"] - trade["fees"])
            )
            < 1e-6
        )
        if trade["reason"] == "BB_MIDDLE":
            assert trade["trail_armed"] and trade["trail_armed_at"] <= trade["exit_ts"]
        last_exit[key] = trade["exit_ts"]
    return {"ledger_rows_checked": len(trades), "passed": True}


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from database.symbol import SymToken, db_session
    from services.market_scanner_provider import load_universe
    from services.market_scanner_service import rank_rows, validate_options
    from services.scanner_strategy_reports import ReportStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", default=datetime.now(IST).date().isoformat())
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--profile", choices=list(PROFILES), action="append")
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument(
        "--retry-invalid",
        action="store_true",
        help="Retry excluded history with non-overlapping epoch ranges",
    )
    args = parser.parse_args()
    day = args.day
    universe = {r["symbol"]: r for r in load_universe()}
    with closing(sqlite3.connect("file:db/market_scanner_live.db?mode=ro", uri=True)) as c:
        rows = c.execute(
            "SELECT user,snapshot FROM scanner_live_accounts WHERE broker='fyers'"
        ).fetchall()
    if len(rows) != 1:
        raise RuntimeError("Exactly one FYERS scanner account is needed")
    owner, payload = rows[0]
    snapshot = json.loads(payload)
    allowed = nifty500_symbols()
    if snapshot.get("session_date") == day:
        ranked = rank_rows(
            [r for r in snapshot["rows"] if r["symbol"] in allowed],
            validate_options({"limit": 50, "positive_only": True}),
        )
        scanner_symbols = sorted(
            {r["symbol"] for g in ("top_gainers", "volume_shockers") for r in ranked[g]}
        )
    else:
        saved_selection = (
            ROOT / "db/scanner_backtest_cache" / (day + "-ind_nifty500list") / "selection.json"
        )
        selection = json.loads(saved_selection.read_text())
        if selection["day"] != day:
            raise RuntimeError("No matching dated scanner selection")
        scanner_symbols = sorted(set(selection["symbols"]) & allowed)
        snapshot = {"updated_at": selection.get("snapshot_time")}
    watch = sorted(weekday_symbols(owner, datetime.fromisoformat(day).date()))
    caches = [
        ROOT / "db/scanner_backtest_cache" / (day + suffix)
        for suffix in ("-four-strategies", "-ind_nifty500list", "-nifty500", "")
    ]
    caches[0].mkdir(parents=True, exist_ok=True)
    (caches[0] / "selection.json").write_text(
        json.dumps(
            {
                "day": day,
                "snapshot_time": snapshot.get("updated_at"),
                "scanner_symbols": scanner_symbols,
                "watchlist_symbols": watch,
                "watchlist_day": datetime.fromisoformat(day).strftime("%a"),
                "selection_bias": "Final snapshot/current watchlist applied retrospectively",
            },
            indent=2,
        )
    )
    if not 1 <= args.steps <= 128:
        parser.error("--steps must be between 1 and 128")
    if args.fetch_missing or args.retry_invalid:
        from datetime import timedelta
        from urllib.parse import urlencode

        from services.market_scanner_provider import (
            FyersScannerProvider,
            get_fyers_token,
            load_universe,
        )

        provider = FyersScannerProvider(get_fyers_token(owner))
        universe = {r["symbol"]: r for r in load_universe()}
        caches[0].mkdir(parents=True, exist_ok=True)
        try:
            for symbol in sorted(set(watch + scanner_symbols)):
                source = next(
                    (p / (symbol + ".json") for p in caches if (p / (symbol + ".json")).is_file()),
                    None,
                )
                if source is not None:
                    if (
                        not args.retry_invalid
                        or replay(symbol, json.loads(source.read_text()), day, 0.01)[2]["eligible"]
                    ):
                        continue
                if symbol not in universe:
                    continue
                opening = int(datetime.fromisoformat(day).replace(tzinfo=IST).timestamp())
                raw = []
                for first, last in (
                    (opening - 7 * 86400, opening - 1),
                    (opening + 555 * 60, opening + 930 * 60 - 1),
                ):
                    fetched = (
                        provider._request(
                            "/data/history?"
                            + urlencode(
                                {
                                    "symbol": universe[symbol]["broker_symbol"],
                                    "resolution": "1",
                                    "date_format": "0",
                                    "range_from": str(first),
                                    "range_to": str(last),
                                    "cont_flag": "1",
                                }
                            )
                        ).get("candles")
                        or []
                    )
                    # Respect exact request bounds even if the broker includes
                    # a boundary day's extra rows in both responses.
                    raw.extend(r for r in fetched if first <= r[0] <= last)
                if not raw:
                    print(f"No history: {symbol}", flush=True)
                    continue
                if not replay(symbol, raw, day, 0.01)[2]["eligible"]:
                    (caches[0] / (symbol + ".retry-invalid.json")).write_text(json.dumps(raw))
                    print(f"Still excluded after narrow-range retry: {symbol}", flush=True)
                    continue
                target = caches[0] / (symbol + ".json")
                if target.exists():
                    backup = target.with_suffix(
                        ".original-"
                        + hashlib.sha256(target.read_bytes()).hexdigest()[:12]
                        + ".json"
                    )
                    if not backup.exists():
                        backup.write_bytes(target.read_bytes())
                (caches[0] / (symbol + ".json")).write_text(json.dumps(raw))
                print(f"Downloaded validated history: {symbol}", flush=True)
        finally:
            from utils.httpx_client import cleanup_httpx_client

            cleanup_httpx_client()
    try:
        ticks = {
            s: float(t)
            for s, t in db_session.query(SymToken.symbol, SymToken.tick_size)
            .filter(SymToken.exchange == "NSE")
            .all()
            if t and t > 0
        }
    finally:
        db_session.remove()
    store = ReportStore()
    try:
        for profile_id, profile in PROFILES.items():
            if args.profile and profile_id not in args.profile:
                continue
            selected = scanner_symbols if profile["universe"] == "nifty500" else watch
            report = {
                "id": f"backtest-{day}-{profile_id}",
                "day": day,
                "kind": "Backtest · " + profile["name"],
                "strategy_id": profile_id,
                "status": "complete" if selected else "empty weekday watchlist",
                "paths": ["OLHC", "OHLC"],
                "trades": [],
                "candles": {},
                "coverage": [],
                "capital_per_trade": 10000,
                "timeframe_minutes": profile["timeframe_minutes"],
                "selection": {
                    "symbols": selected,
                    "snapshot_time": snapshot.get("updated_at"),
                    "universe": profile["universe"],
                },
                "input_hashes": {},
                "steps": args.steps,
                "note": "₹10,000 per trade; 09:15–15:00 IST; repeated fresh signals, one open position/symbol. "
                "Stop: 0.03% below signal HA low, rounded down to instrument tick. "
                "Two alternative modeled OHLC paths, not exchange ticks. 5 bps adverse slippage and "
                "5 bps illustrative fee per fill. Actual Sandbox fills/fees differ. "
                "Afternoon scanner selection/current watchlist applied retrospectively: selection bias. "
                "Incomplete/missing inputs excluded. Realized drawdown is not intratrade drawdown. "
                "No total portfolio capital cap; scenario results must not be added.",
            }
            for i, symbol in enumerate(selected):
                if symbol not in universe:
                    report["coverage"].append(
                        {
                            "symbol": symbol,
                            "eligible": False,
                            "reason": "outside_scheduled_EQ_universe",
                        }
                    )
                    continue
                source = next(
                    (p / (symbol + ".json") for p in caches if (p / (symbol + ".json")).is_file()),
                    None,
                )
                if source is None or symbol not in ticks:
                    report["coverage"].append(
                        {
                            "symbol": symbol,
                            "eligible": False,
                            "reason": "missing_history_or_tick_size",
                        }
                    )
                    continue
                raw = json.loads(source.read_text())
                report["input_hashes"][symbol] = hashlib.sha256(source.read_bytes()).hexdigest()
                for path in report["paths"]:
                    trades, chart, coverage = replay(
                        symbol,
                        raw,
                        day,
                        ticks[symbol],
                        profile["trailing"],
                        path,
                        args.steps,
                        timeframe_minutes=profile["timeframe_minutes"],
                    )
                    report["trades"].extend(trades)
                    if path == "OLHC":
                        report["coverage"].append(coverage)
                        report["candles"][symbol] = chart
                if (i + 1) % 10 == 0:
                    print(f"{profile_id}: {i + 1}/{len(selected)}", flush=True)
            report["verification"] = verify_ledger(report["trades"])
            if selected and any(not c["eligible"] for c in report["coverage"]):
                report["status"] = "complete with exclusions"
            store.save(owner, report)
            print(
                json.dumps(
                    {
                        "id": report["id"],
                        "coverage": report["coverage"],
                        "metrics": report["metrics"],
                    }
                ),
                flush=True,
            )
    finally:
        store.close()


if __name__ == "__main__":
    main()
