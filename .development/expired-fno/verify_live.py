"""Read-only discovery/futures/options smoke check using the existing FYERS login.

Run from the repository root: .venv/bin/python .development/expired-fno/verify_live.py
Never prints credentials or changes the app's processes, schedules or databases.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ["LOG_DIR"] = str(ROOT / "log" / "expired-fno-verification")

from database.auth_db import Auth, db_session
from services.expired_data_service import get_expired_data
from services.market_scanner_provider import credentials


def main():
    try:
        users = (
            db_session.query(Auth.name)
            .filter(Auth.broker == "fyers", Auth.is_revoked.is_(False))
            .all()
        )
    finally:
        db_session.remove()
    if len(users) != 1:
        print(
            json.dumps({"verified": False, "reason": "Exactly one active FYERS login is required"})
        )
        return 1
    try:
        token, _ = credentials(users[0][0], "fyers")
    except Exception:
        print(json.dumps({"verified": False, "reason": "A current FYERS login is required"}))
        return 1

    def call(operation, payload):
        ok, result, status = get_expired_data(operation, payload, auth_token=token, broker="fyers")
        if not ok:
            print(
                json.dumps(
                    {
                        "verified": False,
                        "operation": operation,
                        "http_status": status,
                        "code": result.get("code"),
                        "message": result.get("message"),
                    }
                )
            )
            raise SystemExit(1)
        return result["data"]

    dates = call(
        "expiry-dates",
        {"broker_symbol": "NSE:SBIN-EQ", "start_date": "2025-03-01", "end_date": "2025-03-31"},
    )
    available = dates["expiry_dates"]["futures"]
    if not available:
        print(
            json.dumps({"verified": False, "reason": "No futures expiries returned", "data": dates})
        )
        return 1
    expiry = available[-1]
    contracts = call("contracts", {"broker_symbol": "NSE:SBIN-EQ", "expiry_date": expiry})
    futures = contracts["contracts"]["futures"]
    if not futures:
        print(json.dumps({"verified": False, "reason": "No futures contracts returned"}))
        return 1
    history = call(
        "history",
        {
            "broker_symbol": futures[0],
            "interval": "5m",
            "start_date": expiry,
            "end_date": expiry,
            "include_oi": True,
        },
    )
    options = contracts["contracts"]["options"]
    if not options:
        print(json.dumps({"verified": False, "reason": "No options contracts returned"}))
        return 1
    option = next(
        (value for value in options if value.endswith("760CE")), options[len(options) // 2]
    )
    option_history = call(
        "history",
        {
            "broker_symbol": option,
            "interval": "5m",
            "start_date": expiry,
            "end_date": expiry,
            "include_oi": True,
        },
    )
    verified = bool(history["candles"] and option_history["candles"])
    print(
        json.dumps(
            {
                "verified": verified,
                "expiry_date": expiry,
                "contract": futures[0],
                "futures_count": len(futures),
                "options_count": len(contracts["contracts"]["options"]),
                "candle_count": len(history["candles"]),
                "first_candle": history["candles"][:1],
                "data_status": history["data_status"],
                "option_contract": option,
                "option_candle_count": len(option_history["candles"]),
                "option_first_candle": option_history["candles"][:1],
            },
            indent=2,
        )
    )
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
