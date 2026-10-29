"""Read-only FYERS historical capability probe; artifacts stay under backtesting/."""

import argparse
import json
import os
import time
from datetime import UTC, datetime

from .profiles import BACKTEST_ROOT, ROOT


def active_login():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("LOG_DIR", str(ROOT / "log" / "nifty-options"))
    from database.auth_db import Auth, db_session
    from services.market_scanner_provider import credentials

    try:
        rows = (
            db_session.query(Auth.name)
            .filter(Auth.broker == "fyers", Auth.is_revoked.is_(False))
            .all()
        )
    finally:
        db_session.remove()
    if len(rows) != 1:
        raise RuntimeError("Exactly one active FYERS login is required")
    token, _ = credentials(rows[0][0], "fyers")
    return rows[0][0], token


def expired_call(token, operation, payload):
    from services.expired_data_service import get_expired_data

    for attempt in range(4):
        ok, result, status = get_expired_data(operation, payload, auth_token=token, broker="fyers")
        if ok or status not in {429, 500, 502, 503, 504} or attempt == 3:
            break
        delay = max((5, 15, 30)[attempt], float(result.get("retry_after", 0)))
        if delay > 300:
            raise RuntimeError(
                "FYERS expired-history budget unavailable for more than five minutes"
            )
        time.sleep(delay + 0.1)
    if not ok:
        # Do not serialize tokens, exception reprs, or authenticated request objects.
        raise RuntimeError(
            f"Expired history {operation} failed: HTTP {status}, code {result.get('code')}"
        )
    return result["data"]


def probe(start, end):
    _, token = active_login()
    dates = expired_call(
        token,
        "expiry-dates",
        {
            "broker_symbol": "NSE:NIFTY50-INDEX",
            "start_date": start,
            "end_date": end,
        },
    )
    expiries = dates["expiry_dates"]["options"]
    result = {"expiry_discovery": dates, "historical_greeks": False}
    if not expiries:
        raise RuntimeError("Provider returned no NIFTY option expiries")
    expiry = expiries[-1]
    contracts = expired_call(
        token,
        "contracts",
        {
            "broker_symbol": "NSE:NIFTY50-INDEX",
            "expiry_date": expiry,
        },
    )
    result["contracts"] = contracts
    options = contracts["contracts"]["options"]
    if not options:
        raise RuntimeError("Provider returned no NIFTY option contracts")
    symbol = options[len(options) // 2]
    candles = expired_call(
        token,
        "history",
        {
            "broker_symbol": symbol,
            "interval": "1m",
            "start_date": expiry,
            "end_date": expiry,
            "include_oi": True,
        },
    )
    result["sample"] = candles
    result["verified"] = bool(candles["candles"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    folder = BACKTEST_ROOT / "data_probe" / f"{args.start}_{args.end}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        result = probe(args.start, args.end)
    except Exception as exc:
        result = {
            "verified": False,
            "error": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
        }
    result.update(start=args.start, end=args.end, checked_at=datetime.now(UTC).isoformat())
    (folder / "status.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"sample", "contracts", "expiry_discovery"}
            },
            indent=2,
        )
    )
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
