"""October 6 review: read-only source snapshots, broker history, offline replay.

Never invokes a strategy runner, schedule installer, order API or Reports writer.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DAY = "2026-10-06"
IST = ZoneInfo("Asia/Kolkata")
sys.path.insert(0, str(ROOT))


def save(name, data):
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, allow_nan=False, default=str))


def readonly(path):
    return closing(sqlite3.connect((ROOT / path).resolve().as_uri() + "?mode=ro", uri=True))


def setup():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    private = ROOT / "log/test/day-review-20261006"
    private.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    snapshot = private / "openalgo.db"
    if not snapshot.exists():
        with readonly("db/openalgo.db") as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        os.chmod(snapshot, 0o600)
    os.environ.update(
        DATABASE_URL="sqlite:///" + str(snapshot),
        SANDBOX_DATABASE_URL="sqlite:///" + str(private / "unused-sandbox.db"),
        LOGS_DATABASE_URL="sqlite:///" + str(private / "logs.db"),
        LATENCY_DATABASE_URL="sqlite:///" + str(private / "latency.db"),
        LOG_DIR=str(private / "logs"),
        PYTHON_STRATEGY_DATA_DIR=str(private / "schedules"),
    )
    from strategies.nifty_options import history

    history.CACHE = OUT / "inputs/options"
    return history


def audit():
    configs = json.loads((ROOT / "strategies/strategy_configs.json").read_text())
    scheduled = {k: v for k, v in configs.items() if v.get("is_scheduled")}
    assert len(scheduled) == 20
    with readonly("db/scanner_strategy_reports.db") as conn:
        reports = [
            json.loads(row[0])
            for row in conn.execute("SELECT payload FROM reports WHERE day=?", (DAY,))
        ]
    save("inputs/paper_reports.json", reports)
    review = []
    for ident, conf in scheduled.items():
        matches = sorted((ROOT / "log/strategies").glob(ident + "_20261006*"))
        lines = matches[-1].read_text(errors="replace").splitlines() if matches else []
        counts = {
            "handshake_timeouts": sum(
                "Error in WebSocket connection: timed out during opening handshake" in line
                for line in lines
            ),
            "capacity_rejections": sum("Maximum capacity reached" in line for line in lines),
            "history_connection_resets": sum(
                "HTTP error during API request: [Errno 54]" in line for line in lines
            ),
            "subscription_ack_timeouts": sum(
                "Subscribe timed out waiting for proxy ack" in line for line in lines
            ),
            "hsm_connection_failures": sum(
                "Failed to connect to HSM WebSocket" in line for line in lines
            ),
        }
        examples = []
        for no, line in enumerate(lines, 1):
            if any(
                word in line
                for word in (
                    "Maximum capacity reached",
                    "Error in WebSocket connection",
                    "HTTP error during API request",
                    "Failed to connect to HSM WebSocket",
                )
            ):
                if not any(e["message"] == line[:300] for e in examples):
                    examples.append({"line": no, "message": line[:300]})
        review.append(
            {
                "schedule_id": ident,
                "name": conf["name"],
                "file": conf["file_name"],
                "started": conf.get("last_started"),
                "stopped": conf.get("last_stopped"),
                "log": str(matches[-1].relative_to(ROOT)) if matches else None,
                "log_sha256": hashlib.sha256(matches[-1].read_bytes()).hexdigest()
                if matches
                else None,
                "counts": counts,
                "examples": examples[:5],
            }
        )
    app_counts, first, last = Counter(), None, None
    for line in (ROOT / "log/errors.jsonl").read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        stamp = row.get("ts", "")
        if not stamp.startswith(DAY):
            continue
        first = min(first or stamp, stamp)
        last = max(last or stamp, stamp)
        app_counts[(row.get("logger"), row.get("message", "")[:240])] += 1
    with readonly("db/sandbox.db") as conn:
        conn.row_factory = sqlite3.Row
        orders = [
            dict(r)
            for r in conn.execute(
                "SELECT orderid,strategy,symbol,exchange,action,quantity,order_status,average_price,filled_quantity,product,order_timestamp FROM sandbox_orders WHERE order_timestamp LIKE ? ORDER BY order_timestamp",
                (DAY + "%",),
            )
        ]
        positions = [
            dict(r)
            for r in conn.execute(
                "SELECT symbol,product,quantity FROM sandbox_positions WHERE quantity != 0"
            )
        ]
    with readonly("db/nifty_options/state.sqlite3") as conn:
        events = [
            {"strategy": a, "kind": b, "count": c}
            for a, b, c in conn.execute(
                "SELECT strategy,kind,count(*) FROM events WHERE timestamp LIKE ? GROUP BY strategy,kind",
                (DAY + "%",),
            )
        ]
    result = {
        "day": DAY,
        "strategies": review,
        "application_errors": [
            {"logger": a, "message": b, "count": n} for (a, b), n in app_counts.most_common()
        ],
        "error_log_range": [first, last],
        "orders": orders,
        "remaining_sandbox_positions": positions,
        "option_events": events,
        "schedule_sha256": hashlib.sha256(
            (ROOT / "strategies/strategy_configs.json").read_bytes()
        ).hexdigest(),
    }
    save("audit.json", result)
    print(
        json.dumps(
            {
                "audit_strategies": len(review),
                "paper_reports": len(reports),
                "orders": len(orders),
                "nonzero_positions": len(positions),
            }
        ),
        flush=True,
    )


def prepare():
    from database.symbol import SymToken, db_session
    from services.market_scanner_service import rank_rows, validate_options
    from strategies.nifty_options.data_probe import active_login
    from strategies.top_gain_volumes.profiles import nifty500_symbols, weekday_symbols

    owner, token = active_login()
    with readonly("db/market_scanner_live.db") as conn:
        row = conn.execute(
            "SELECT snapshot FROM scanner_live_accounts WHERE user=? AND broker='fyers'", (owner,)
        ).fetchone()
    snapshot = json.loads(row[0])
    assert snapshot["session_date"] == DAY
    allowed = nifty500_symbols()
    ranked = rank_rows(
        [r for r in snapshot["rows"] if r["symbol"] in allowed],
        validate_options({"limit": 50, "positive_only": True}),
    )
    selected = sorted(
        {r["symbol"] for group in ("top_gainers", "volume_shockers") for r in ranked[group]}
    )
    watch = sorted(weekday_symbols(owner, date.fromisoformat(DAY)))
    try:
        stocks = {
            r.symbol: {"symbol": r.symbol, "broker_symbol": r.brsymbol, "tick_size": r.tick_size}
            for r in db_session.query(SymToken).filter(
                SymToken.exchange == "NSE", SymToken.instrumenttype == "EQ"
            )
            if r.symbol in set(selected + watch)
        }
        all_options = list(
            db_session.query(SymToken).filter(
                SymToken.exchange == "NFO",
                SymToken.name == "NIFTY",
                SymToken.instrumenttype.in_(("CE", "PE")),
            )
        )
        expiries = sorted(
            {
                datetime.strptime(r.expiry, "%d-%b-%y").date().isoformat()
                for r in all_options
                if datetime.strptime(r.expiry, "%d-%b-%y").date() >= date.fromisoformat(DAY)
            }
        )[:2]
        options = [
            {
                "symbol": r.brsymbol,
                "expiry": datetime.strptime(r.expiry, "%d-%b-%y").date().isoformat(),
                "strike": r.strike,
                "kind": r.instrumenttype,
                "start": DAY,
                "end": DAY,
                "expired": False,
            }
            for r in all_options
            if datetime.strptime(r.expiry, "%d-%b-%y").date().isoformat() in expiries
        ]
    finally:
        db_session.remove()
    selection = {
        "scanner": selected,
        "watchlist": watch,
        "snapshot_time": snapshot.get("updated_at"),
        "stocks": stocks,
        "selection_bias": "End-of-day ranked Nifty500 basket/current Tuesday watchlist applied retrospectively; not a point-in-time scanner replay",
    }
    save("inputs/selection.json", selection)
    return token, selection, expiries, options


def fetch(history):
    from strategies.nifty_options.data_probe import active_login
    from strategies.top_gain_volumes.replay_four import replay

    token, selection, expiries, options = prepare()
    spot_path = history.cache_file("NSE:NIFTY50-INDEX", DAY, DAY)
    if not spot_path.exists():
        history.write_candles(spot_path, session_history(history, token, "NSE:NIFTY50-INDEX"))
    manifest = {
        "start": DAY,
        "end": DAY,
        "expiries": expiries,
        "contracts": options,
        "spot_files": [str(spot_path.relative_to(ROOT))],
        "source": "FYERS actual current contract master and history; completed October 6 session",
        "historical_greeks": False,
    }
    save("inputs/manifest.json", manifest)
    print(
        json.dumps(
            {
                "history_plan": {
                    "stocks": len(selection["stocks"]),
                    "options": len(options),
                    "expiries": expiries,
                }
            }
        ),
        flush=True,
    )
    failures = []
    from urllib.parse import urlencode

    from broker.fyers.api.data import get_api_response

    opening = int(datetime.fromisoformat(DAY).replace(tzinfo=IST).timestamp())
    for i, (symbol, info) in enumerate(selection["stocks"].items()):
        target = OUT / "inputs/stocks" / (symbol + ".json")
        if not target.exists():
            raw = []
            for first, last in (
                (opening - 7 * 86400, opening - 1),
                (opening + 555 * 60, opening + 930 * 60 - 1),
            ):
                endpoint = "/data/history?" + urlencode(
                    {
                        "symbol": info["broker_symbol"],
                        "resolution": "1",
                        "date_format": "0",
                        "range_from": first,
                        "range_to": last,
                        "cont_flag": "1",
                    }
                )
                response = get_api_response(endpoint, token)
                if response.get("s") not in ("ok", "no_data"):
                    raise RuntimeError(
                        "Stock history failed: " + symbol + " code " + str(response.get("code"))
                    )
                raw.extend(r for r in response.get("candles", []) if first <= r[0] <= last)
                time.sleep(0.45)
            save("inputs/stocks/" + symbol + ".json", raw)
        if (i + 1) % 10 == 0:
            print(
                json.dumps({"stocks_done": i + 1, "stocks_total": len(selection["stocks"])}),
                flush=True,
            )
    for i, contract in enumerate(options):
        target = history.cache_file(contract["symbol"], DAY, DAY)
        if not target.exists():
            try:
                data = session_history(history, token, contract["symbol"])
                history.write_candles(target, data)
            except RuntimeError as exc:
                failures.append({"symbol": contract["symbol"], "error": str(exc)[:250]})
            time.sleep(0.45)
        if (i + 1) % 25 == 0:
            save(
                "progress.json",
                {
                    "status": "fetching",
                    "completed_options": i + 1,
                    "total_options": len(options),
                    "failures": failures,
                },
            )
            print(
                json.dumps(
                    {
                        "options_done": i + 1,
                        "options_total": len(options),
                        "failures": len(failures),
                    }
                ),
                flush=True,
            )
    save(
        "progress.json",
        {
            "status": "downloaded" if not failures else "incomplete",
            "failures": failures,
            "total_options": len(options),
        },
    )


def session_history(history, token, symbol):
    """Use exact epoch bounds; retain source response and reject conflicting duplicates."""
    from urllib.parse import urlencode

    from broker.fyers.api.data import get_api_response

    first = int(datetime.fromisoformat(DAY).replace(tzinfo=IST).timestamp())
    last = first + 86400 - 1
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
            raise RuntimeError(
                "History request failed for " + symbol + " code " + str(response.get("code"))
            )
        time.sleep((2, 5, 10)[attempt])
    rows = response.get("candles", [])
    raw_id = hashlib.sha256(symbol.encode()).hexdigest()
    save("inputs/raw/" + raw_id + ".json", response)
    unique = {}
    duplicates = 0
    for row in rows:
        if not first <= row[0] <= last:
            continue
        if row[0] in unique:
            if unique[row[0]] != row:
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
        "data_status": "ok" if rows else "no_data",
        "identical_duplicates_removed": duplicates,
        "source_file": "inputs/raw/" + raw_id + ".json",
        "index_close_only": symbol == "NSE:NIFTY50-INDEX",
    }


def backtest(history, stage="backtest"):
    from services.scanner_strategy_reports import metrics
    from strategies.top_gain_volumes.profiles import PROFILES as stocks
    from strategies.top_gain_volumes.replay_four import replay, verify_ledger

    selection = json.loads((OUT / "inputs/selection.json").read_text())
    if stage != "options":
        results = []
        for key, profile in stocks.items():
            symbols = (
                selection["scanner"]
                if profile["universe"] == "nifty500"
                else selection["watchlist"]
            )
            for path in ("OLHC", "OHLC"):
                trades = []
                coverage = []
                hashes = {}
                for symbol in symbols:
                    source = OUT / "inputs/stocks" / (symbol + ".json")
                    info = selection["stocks"].get(symbol)
                    if not source.exists() or not info or not info["tick_size"]:
                        coverage.append(
                            {
                                "symbol": symbol,
                                "eligible": False,
                                "reason": "missing_history_or_tick",
                            }
                        )
                        continue
                    raw = json.loads(source.read_text())
                    tt, _, cc = replay(
                        symbol,
                        raw,
                        DAY,
                        info["tick_size"],
                        profile["trailing"],
                        path,
                        8,
                        profile["timeframe_minutes"],
                    )
                    trades.extend(tt)
                    coverage.append(cc)
                    hashes[symbol] = hashlib.sha256(source.read_bytes()).hexdigest()
                result = {
                    "strategy": key,
                    "name": profile["name"],
                    "family": "Stocks",
                    "path": path,
                    "trades": trades,
                    "metrics": metrics(trades),
                    "coverage": coverage,
                    "source_hashes": hashes,
                    "verification": verify_ledger(trades),
                }
                results.append(result)
                print(
                    json.dumps(
                        {
                            "replayed": key,
                            "path": path,
                            "trades": len(trades),
                            "net_pnl": result["metrics"]["net_pnl"],
                        }
                    ),
                    flush=True,
                )
        save("stocks.json", results)
    if stage == "stocks":
        return
    from strategies.nifty_options import replay as options_replay

    archive = options_replay.Archive(OUT / "inputs/manifest.json")
    day = date.fromisoformat(DAY)
    save("inputs/calendar.json", archive.verify_calendar(day, day))
    summaries = []
    for path in ("OLHC", "OHLC"):
        states, trades, curves, skipped = options_replay.replay(archive, day, day, path)
        summaries.extend(
            options_replay.export_run(OUT / "options", path, states, trades, curves, skipped)
        )
        save(
            "options/" + path + "/details.json",
            {"states": states, "trades": trades, "curves": curves, "skipped": skipped},
        )
    save("options/summary.json", summaries)
    save("inputs/option_source_hashes.json", archive.sources)
    print(json.dumps({"option_scenarios": len(summaries)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["audit", "fetch", "backtest", "stocks", "options"])
    args = parser.parse_args()
    if args.stage == "audit":
        audit()
    else:
        h = setup()
        try:
            fetch(h) if args.stage == "fetch" else backtest(h, args.stage)
        finally:
            from utils.httpx_client import cleanup_httpx_client

            cleanup_httpx_client()
