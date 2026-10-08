"""Read-only history collection and isolated October 7 replay; no order routing."""

import importlib.util
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "log/test/day-review-20261007"
DAY = "2026-10-07"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "previous_review", ROOT / "backtesting/all_scheduled_20261006/run.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.OUT, base.DAY = OUT, DAY


def setup():
    import dotenv

    dotenv.load_dotenv(ROOT / ".env")
    dotenv.load_dotenv = lambda *a, **kw: False
    dotenv.main.load_dotenv = dotenv.load_dotenv
    OUT.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT, 0o700)
    for name in ("openalgo.db", "market_scanner_live.db"):
        target = OUT / name
        if not target.exists():
            with base.readonly("db/" + name) as source, closing(sqlite3.connect(target)) as dest:
                source.backup(dest)
            os.chmod(target, 0o600)
    for key in list(os.environ):
        if key.endswith("DATABASE_URL") or key.endswith("_DB_URL"):
            os.environ[key] = "sqlite:///" + str(OUT / (key.lower() + ".db"))
    os.environ.update(
        DATABASE_URL="sqlite:///" + str(OUT / "openalgo.db"),
        SANDBOX_DATABASE_URL="sqlite:///" + str(OUT / "unused-sandbox.db"),
        LOGS_DATABASE_URL="sqlite:///" + str(OUT / "logs.db"),
        LATENCY_DATABASE_URL="sqlite:///" + str(OUT / "latency.db"),
        SCANNER_LIVE_DB=str(OUT / "market_scanner_live.db"),
        LOG_DIR=str(OUT / "logs"),
        PYTHON_STRATEGY_DATA_DIR=str(OUT / "schedules"),
    )
    from strategies.nifty_options import history

    history.CACHE = OUT / "inputs/options"
    return history


def prepare():
    from database.symbol import SymToken, db_session
    from services.market_scanner_service import rank_rows, validate_options
    from strategies.nifty_options.data_probe import active_login
    from strategies.top_gain_volumes.profiles import nifty500_symbols, weekday_symbols

    owner, token = active_login()
    with closing(
        sqlite3.connect((OUT / "market_scanner_live.db").as_uri() + "?mode=ro", uri=True)
    ) as conn:
        payload = conn.execute(
            "SELECT snapshot FROM scanner_live_accounts WHERE user=? AND broker='fyers'", (owner,)
        ).fetchone()
    snapshot = json.loads(payload[0])
    assert snapshot["session_date"] == DAY, "Scanner snapshot date mismatch"
    allowed = nifty500_symbols()
    rows = [r for r in snapshot["rows"] if r["symbol"] in allowed]

    def selected(short=False):
        source = (
            [
                {**r, "change_percent": -r["change_percent"]}
                for r in rows
                if r.get("change_percent", 0) < 0
            ]
            if short
            else rows
        )
        ranked = rank_rows(source, validate_options({"limit": 50, "positive_only": not short}))
        return sorted({r["symbol"] for g in ("top_gainers", "volume_shockers") for r in ranked[g]})

    longs, shorts = selected(), selected(True)
    watch = sorted(weekday_symbols(owner, date.fromisoformat(DAY)))
    try:
        stocks = {
            r.symbol: {"symbol": r.symbol, "broker_symbol": r.brsymbol, "tick_size": r.tick_size}
            for r in db_session.query(SymToken).filter(
                SymToken.exchange == "NSE", SymToken.instrumenttype == "EQ"
            )
            if r.symbol in set(longs + shorts + watch)
        }
        all_options = list(
            db_session.query(SymToken).filter(
                SymToken.exchange == "NFO",
                SymToken.name == "NIFTY",
                SymToken.instrumenttype.in_(("CE", "PE")),
            )
        )

        def expiry(r):
            return datetime.strptime(r.expiry, "%d-%b-%y").date().isoformat()

        expiries = sorted({expiry(r) for r in all_options if expiry(r) >= DAY})[:2]
        options = [
            {
                "symbol": r.brsymbol,
                "expiry": expiry(r),
                "strike": r.strike,
                "kind": r.instrumenttype,
                "start": DAY,
                "end": DAY,
                "expired": False,
                "lot_size": r.lotsize,
            }
            for r in all_options
            if expiry(r) in expiries
        ]
    finally:
        db_session.remove()
    selection = {
        "scanner": sorted(set(longs + shorts)),
        "longs": longs,
        "shorts": shorts,
        "watchlist": watch,
        "stocks": stocks,
        "snapshot_time": snapshot.get("updated_at"),
        "broker": "fyers",
        "selection_bias": "Latest October 7 snapshot ranked retrospectively; not point-in-time membership. Wednesday watchlist snapshot.",
    }
    base.save("inputs/selection.json", selection)
    return token, selection, expiries, options


def session_history(history, token, symbol):
    """Narrow session bounds; index replay consumes close only, not index volume."""
    import hashlib
    import time
    from urllib.parse import urlencode

    from broker.fyers.api.data import get_api_response

    first = int(datetime.fromisoformat(DAY).replace(hour=9, minute=15, tzinfo=base.IST).timestamp())
    last = first + 385 * 60 - 1
    endpoint = "/data/history?" + urlencode(
        {
            "symbol": symbol,
            "resolution": "1",
            "date_format": "0",
            "range_from": first,
            "range_to": last,
            "cont_flag": "1",
        }
    )
    for attempt in range(4):
        response = get_api_response(endpoint, token)
        if response.get("s") in ("ok", "no_data"):
            break
        if attempt == 3:
            raise RuntimeError("History failed: " + symbol + " code " + str(response.get("code")))
        time.sleep((2, 5, 10)[attempt])
    raw_id = hashlib.sha256(symbol.encode()).hexdigest()
    base.save("inputs/raw/" + raw_id + ".json", response)
    unique, duplicates, index_volume_revisions = {}, 0, 0
    for row in response.get("candles", []):
        if not first <= row[0] <= last:
            continue
        if row[0] in unique:
            old = unique[row[0]]
            if old != row:
                if symbol == "NSE:NIFTY50-INDEX" and old[:5] == row[:5]:
                    index_volume_revisions += 1
                else:
                    raise RuntimeError("Conflicting minute candles: " + symbol)
            duplicates += 1
        unique[row[0]] = row
    converted = [
        dict(zip(("timestamp", "open", "high", "low", "close", "volume", "oi"), r, strict=False))
        for _, r in sorted(unique.items())
    ]
    history.validate_rows(converted, check_ohlc=symbol != "NSE:NIFTY50-INDEX")
    return {
        "broker_symbol": symbol,
        "candles": converted,
        "interval": "1m",
        "start_date": DAY,
        "end_date": DAY,
        "data_status": "ok" if converted else "no_data",
        "duplicates_removed": duplicates,
        "index_volume_revisions": index_volume_revisions,
        "source_file": "inputs/raw/" + raw_id + ".json",
        "index_close_only": symbol == "NSE:NIFTY50-INDEX",
    }


def equities():
    import math

    from strategies.short_equity import runtime as short_runtime
    from strategies.short_equity.profiles import PROFILES as shorts
    from strategies.top_gain_volumes import runtime as long_runtime
    from strategies.top_gain_volumes.history import aggregate_minutes
    from strategies.top_gain_volumes.profiles import PROFILES as longs
    from strategies.top_gain_volumes.replay_four import replay, verify_ledger

    selection = json.loads((OUT / "inputs/selection.json").read_text())
    results = []
    for key, profile in {**longs, **shorts}.items():
        short = key in shorts
        symbols = (
            selection["shorts" if short else "longs"]
            if profile["universe"] == "nifty500"
            else selection["watchlist"]
        )
        for path in ("OLHC", "OHLC"):
            trades, coverage = [], []
            for symbol in symbols:
                source = OUT / "inputs/stocks" / (symbol + ".json")
                info = selection["stocks"].get(symbol)
                if not source.exists() or not info:
                    coverage.append(
                        {"symbol": symbol, "eligible": False, "reason": "missing_history"}
                    )
                    continue
                raw = json.loads(source.read_text())
                tick = info["tick_size"]
                if not short:
                    tt, _, cc = replay(
                        symbol,
                        raw,
                        DAY,
                        tick,
                        profile["trailing"],
                        path,
                        8,
                        profile["timeframe_minutes"],
                    )
                    verify_ledger(tt)
                else:
                    # The installed short runtime provides all signal/fill/exit rules.
                    start = (
                        datetime.fromisoformat(DAY)
                        .replace(hour=9, minute=15, tzinfo=base.IST)
                        .timestamp()
                    )
                    cutoff = start + 360 * 60
                    prior = [
                        r for r in raw if r[0] < start and 555 <= (r[0] + 19800) % 86400 // 60 < 930
                    ]
                    current = [r for r in raw if start <= r[0] <= cutoff]
                    reason = None
                    if len(aggregate_minutes(prior, profile["timeframe_minutes"], start)) < 20:
                        reason = "insufficient_warmup"
                    elif [int(r[0]) for r in current] != list(
                        range(int(start), int(cutoff) + 1, 60)
                    ):
                        reason = "missing_or_duplicate_minutes"
                    elif any(
                        len(r) != 6
                        or not all(math.isfinite(v) for v in r)
                        or min(r[1:5]) <= 0
                        or r[5] < 0
                        or r[2] < max(r[1:5])
                        or r[3] > min(r[1:5])
                        for r in prior + current
                    ):
                        reason = "invalid_ohlcv"
                    tt, cc = [], {"symbol": symbol, "eligible": reason is None}
                    if reason:
                        cc["reason"] = reason
                    else:
                        candle = short_runtime.TickCandles(
                            prior, start, timeframe_minutes=profile["timeframe_minutes"]
                        )
                        position = used_signal = None
                        cumulative = 0.0
                        for stamp, op, high, low, close, volume in current:
                            vertices = (
                                (op, low, high, close) if path == "OLHC" else (op, high, low, close)
                            )
                            samples = [(0.0, op)]
                            if stamp < cutoff:
                                samples.extend(
                                    (
                                        (leg + step / 8) / 3,
                                        vertices[leg]
                                        + (vertices[leg + 1] - vertices[leg]) * step / 8,
                                    )
                                    for leg in range(3)
                                    for step in range(1, 9)
                                )
                            for fraction, price in samples:
                                observed = stamp + fraction * 59.999
                                qualifies = candle.tick(
                                    observed, price, cumulative + fraction * volume
                                )
                                if position is not None:
                                    if short_runtime.exit_trade(
                                        position,
                                        observed,
                                        price,
                                        tick,
                                        915,
                                        profile["trailing"],
                                        candle.middle,
                                    ):
                                        position = None
                                elif (
                                    qualifies and stamp < cutoff and candle.signal[0] != used_signal
                                ):
                                    position = short_runtime.enter(
                                        symbol, observed, price, candle, tick
                                    )
                                    used_signal = candle.signal[0]
                                    if position:
                                        position.update(path=path, signal_high=candle.signal[1])
                                        tt.append(position)
                            cumulative += volume
                        last = 0
                        for t in tt:
                            assert (
                                t["exit_ts"] is not None and t["exit_ts"] >= t["entry_ts"] >= last
                            )
                            assert t["entry"] * t["quantity"] <= 10000 + 1e-6
                            assert t["stop"] >= t["signal_high"] * 1.0003 - 1e-7
                            assert t["target"] <= t["entry"] - 3 * (t["stop"] - t["entry"]) + 1e-7
                            assert (
                                t["signal_ts"] + candle.interval
                                <= t["entry_ts"]
                                < t["signal_ts"] + 2 * candle.interval
                            )
                            assert (
                                abs(t["gross_pnl"] - (t["entry"] - t["exit"]) * t["quantity"])
                                < 1e-6
                            )
                            last = t["exit_ts"]
                trades.extend(tt)
                coverage.append(cc)
            results.append(
                {
                    "strategy": key,
                    "name": profile["name"],
                    "family": "Equity short" if short else "Equity long",
                    "path": path,
                    "trades": trades,
                    "coverage": coverage,
                    "universe_size": len(symbols),
                    "timeframe_minutes": profile["timeframe_minutes"],
                }
            )
            print(
                json.dumps(
                    {
                        "strategy": key,
                        "path": path,
                        "trades": len(trades),
                        "eligible": sum(c["eligible"] for c in coverage),
                        "universe": len(symbols),
                    }
                ),
                flush=True,
            )
    base.save("stocks.json", results)


def options(history):
    from services.report_brokerage import order_cost, tariff
    from strategies.nifty_options import replay as engine

    original_fill = engine.estimated_fill

    def retail_fill(price, side, quantity, **kwargs):
        fill, _ = original_fill(price, side, quantity)
        parts = order_cost(
            fill * quantity, "BUY" if side > 0 else "SELL", "NFO", "options", DAY, tariff("fyers")
        )
        return fill, round(sum(parts.values()), 2)

    engine.estimated_fill = retail_fill
    archive = engine.Archive(OUT / "inputs/manifest.json")
    base.save(
        "inputs/calendar.json",
        archive.verify_calendar(date.fromisoformat(DAY), date.fromisoformat(DAY)),
    )
    for path in ("OLHC", "OHLC"):
        states, trades, curves, skipped = engine.replay(
            archive, date.fromisoformat(DAY), date.fromisoformat(DAY), path
        )
        for key, profile in engine.PROFILES.items():
            engine.verify_vectorbt(trades[key], profile.capital)
        base.save(
            "options/" + path + "/details.json",
            {"states": states, "trades": trades, "curves": curves, "skipped": skipped},
        )
    base.save("inputs/option_source_hashes.json", archive.sources)


if __name__ == "__main__":
    history = setup()
    base.prepare = prepare
    base.session_history = session_history
    try:
        stage = sys.argv[1]
        if stage == "prepare":
            _, selection, expiries, contracts = prepare()
            print(
                json.dumps(
                    {
                        "longs": len(selection["longs"]),
                        "shorts": len(selection["shorts"]),
                        "watchlist": len(selection["watchlist"]),
                        "stocks": len(selection["stocks"]),
                        "options": len(contracts),
                        "expiries": expiries,
                        "snapshot": selection["snapshot_time"],
                    }
                )
            )
        elif stage == "fetch":
            base.fetch(history)
        elif stage == "stocks":
            equities()
        elif stage == "options":
            options(history)
    finally:
        from utils.httpx_client import cleanup_httpx_client

        cleanup_httpx_client()
