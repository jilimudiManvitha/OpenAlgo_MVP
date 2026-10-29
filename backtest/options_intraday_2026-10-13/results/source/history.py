"""Resumable FYERS NIFTY archive. No report database writes or synthetic candles."""

import argparse
import gzip
import hashlib
import json
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from .data_probe import active_login, expired_call
from .profiles import BACKTEST_ROOT, ROOT

CACHE = BACKTEST_ROOT / "cache"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False))
    temp.replace(path)


def cache_file(symbol, start, end):
    key = hashlib.sha256(f"{symbol}|{start}|{end}|1m".encode()).hexdigest()
    return CACHE / "candles" / (key + ".json.gz")


def existing_cache_file(symbol, start, end):
    """Read old archives without relocating or overwriting the accepted backtest."""
    path = cache_file(symbol, start, end)
    legacy = ROOT / "backtest/nifty_options/cache/candles" / path.name
    return path if path.exists() or not legacy.exists() else legacy


def write_candles(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with gzip.open(temp, "wt", encoding="utf-8") as stream:
        json.dump(data, stream, separators=(",", ":"), allow_nan=False)
    temp.replace(path)


def read_candles(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def regular_history(token, symbol, start, end):
    from broker.fyers.api.data import get_api_response

    endpoint = "/data/history?" + urlencode(
        {
            "symbol": symbol,
            "resolution": "1",
            "date_format": "1",
            "range_from": start,
            "range_to": end,
            "cont_flag": "1",
        }
    )
    for attempt in range(4):
        result = get_api_response(endpoint, token)
        limited = str(result.get("code")) in {"429", "-429"}
        if (not result.get("retryable") and not limited) or attempt == 3:
            break
        delay = max((5, 15, 30)[attempt], float(result.get("retry_after", 0)))
        if delay > 300:
            raise RuntimeError("FYERS history budget unavailable for more than five minutes")
        time.sleep(delay + 0.1)
    if result.get("s") not in {"ok", "no_data"}:
        raise RuntimeError("FYERS regular history failed, code " + str(result.get("code")))
    # Validate below without importing a separate strategy's private helpers.
    rows = result.get("candles")
    if not isinstance(rows, list):
        raise RuntimeError("Malformed historical candles")
    if result.get("s") == "no_data" and rows:
        raise RuntimeError("Contradictory no-data response with candles")
    converted = [
        dict(zip(("timestamp", "open", "high", "low", "close", "volume", "oi"), row, strict=False))
        for row in rows
    ]
    # The NIFTY index is used only as a close-price benchmark / ATM reference.
    # Preserve bad source OHLC unchanged and disclose it; do not use its opens
    # or extremes to manufacture an option execution path.
    index_only = symbol == "NSE:NIFTY50-INDEX"
    anomalies = [
        r
        for r in converted
        if not r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]
    ]
    validate_rows(converted, check_ohlc=not index_only)
    return {
        "broker_symbol": symbol,
        "candles": converted,
        "interval": "1m",
        "start_date": start,
        "end_date": end,
        "data_status": "ok" if rows else "no_data",
        "source_ohlc_anomalies": anomalies,
        "index_close_only": index_only,
    }


def validate_rows(rows, check_ohlc=True):
    import math

    previous = None
    for row in rows:
        if any(
            not isinstance(row.get(k), (int, float)) or not math.isfinite(row[k])
            for k in ("timestamp", "open", "high", "low", "close", "volume")
        ):
            raise RuntimeError("Malformed or non-finite historical candle")
        if previous is not None and row["timestamp"] <= previous:
            raise RuntimeError("Unsorted or duplicate historical candle")
        previous = row["timestamp"]
        if row["close"] <= 0 or row["volume"] < 0:
            raise RuntimeError("Nonpositive price or negative volume")
        if check_ohlc and (
            row["low"] < 0
            or not row["low"]
            <= min(row["open"], row["close"])
            <= max(row["open"], row["close"])
            <= row["high"]
        ):
            raise RuntimeError("Inconsistent OHLC: " + json.dumps(row))


def current_contracts():
    """Current master is used only for contracts that have not expired."""
    from database.symbol import SymToken, db_session

    found = {}
    try:
        rows = (
            db_session.query(SymToken)
            .filter(SymToken.exchange == "NFO", SymToken.name == "NIFTY")
            .all()
        )
        for row in rows:
            if row.instrumenttype not in {"CE", "PE"}:
                continue
            expiry = datetime.strptime(row.expiry, "%d-%b-%y").date()
            if expiry < date.today():
                continue
            found.setdefault(expiry.isoformat(), []).append(row.brsymbol)
    finally:
        db_session.remove()
    return found


def discover(token, start, end, folder):
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    expiry_set = set()
    day = start - timedelta(days=21)
    upper = min(date.today() - timedelta(days=1), end + timedelta(days=21))
    while day <= upper:
        last = min(day + timedelta(days=365), upper)
        payload = {
            "broker_symbol": "NSE:NIFTY50-INDEX",
            "start_date": str(day),
            "end_date": str(last),
        }
        expiry_set.update(expired_call(token, "expiry-dates", payload)["expiry_dates"]["options"])
        day = last + timedelta(days=1)
    live = current_contracts()
    expiry_set.update(live)
    expiries = sorted(e for e in expiry_set if date.fromisoformat(e) <= end + timedelta(days=15))
    entries = []
    for index, expiry in enumerate(expiries):
        if expiry < str(start):
            continue
        begin = (
            max(start, date.fromisoformat(expiries[index - 2]) + timedelta(days=1))
            if index >= 2
            else start
        )
        finish = min(end, date.fromisoformat(expiry))
        if begin > finish:
            continue
        catalogue_path = CACHE / "contracts" / (expiry + ".json")
        if catalogue_path.exists():
            symbols = json.loads(catalogue_path.read_text())["symbols"]
        elif expiry in live:
            symbols = live[expiry]
            atomic_json(catalogue_path, {"source": "current_master", "symbols": symbols})
        else:
            data = expired_call(
                token, "contracts", {"broker_symbol": "NSE:NIFTY50-INDEX", "expiry_date": expiry}
            )
            symbols = data["contracts"]["options"]
            atomic_json(catalogue_path, {"source": "fyers_expired_contracts", "symbols": symbols})
        for symbol in symbols:
            match = re.fullmatch(
                r"NSE:NIFTY\d{2}(?:[A-Z]{3}|[1-9OND]\d{2})(\d+(?:\.\d+)?)(CE|PE)", symbol
            )
            if not match:
                raise RuntimeError("Unsupported provider option identifier: " + symbol)
            entries.append(
                {
                    "symbol": symbol,
                    "expiry": expiry,
                    "strike": float(match[1]),
                    "kind": match[2],
                    "start": str(begin),
                    "end": str(finish),
                    "expired": expiry < str(date.today()),
                }
            )
        print(json.dumps({"catalogue_expiry": expiry, "options": len(symbols)}), flush=True)
        time.sleep(0.35)
    result = {
        "start": str(start),
        "end": str(end),
        "expiries": expiries,
        "contracts": entries,
        "source": "FYERS actual listed contracts",
        "interval": "1m",
        "historical_greeks": False,
    }
    atomic_json(manifest_path, result)
    return result


def download(start, end, catalogue_only=False):
    _, token = active_login()
    folder = BACKTEST_ROOT / f"{start}_{end}"
    folder.mkdir(parents=True, exist_ok=True)
    progress = {"status": "discovering", "start": str(start), "end": str(end), "completed": 0}
    try:
        manifest = discover(token, start, end, folder)
        progress.update(status="catalogued", contracts=len(manifest["contracts"]))
        atomic_json(folder / "download_status.json", progress)
        if catalogue_only:
            return folder
        day = start
        spot_files = []
        while day <= end:
            last = min(day + timedelta(days=99), end)
            path = cache_file("NSE:NIFTY50-INDEX", day, last)
            if not path.exists():
                write_candles(
                    path, regular_history(token, "NSE:NIFTY50-INDEX", str(day), str(last))
                )
                time.sleep(0.4)
            spot_files.append(str(path.relative_to(ROOT)))
            day = last + timedelta(days=1)
        manifest["spot_files"] = spot_files
        atomic_json(folder / "manifest.json", manifest)
        for i, contract in enumerate(manifest["contracts"]):
            symbol, first, last = contract["symbol"], contract["start"], contract["end"]
            path = cache_file(symbol, first, last)
            cached = path.exists()
            if not cached:
                if contract["expired"]:
                    data = expired_call(
                        token,
                        "history",
                        {
                            "broker_symbol": symbol,
                            "interval": "1m",
                            "start_date": first,
                            "end_date": last,
                            "include_oi": True,
                        },
                    )
                else:
                    data = regular_history(token, symbol, first, last)
                validate_rows(data["candles"])
                write_candles(path, data)
                time.sleep(0.4)  # Leave headroom below provider's per-minute ceiling.
            progress.update(
                status="downloading",
                completed=i + 1,
                current_expiry=contract["expiry"],
                updated_at=datetime.now(UTC).isoformat(),
            )
            if (i + 1) % 10 == 0:
                atomic_json(folder / "download_status.json", progress)
                if not cached:
                    print(json.dumps(progress), flush=True)
        progress["status"] = "download_complete"
        atomic_json(folder / "download_status.json", progress)
        return folder
    except BaseException as exc:
        progress.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "blocked",
            error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
            updated_at=datetime.now(UTC).isoformat(),
        )
        atomic_json(folder / "download_status.json", progress)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--catalogue-only", action="store_true")
    args = parser.parse_args()
    if args.start > args.end or args.end >= date.today():
        parser.error("Choose a completed historical date range")
    from strategies.top_gain_volumes.coordination import dispatch_lock

    with dispatch_lock(CACHE / "download.lock", timeout=1):
        print(download(args.start, args.end, args.catalogue_only))


if __name__ == "__main__":
    main()
