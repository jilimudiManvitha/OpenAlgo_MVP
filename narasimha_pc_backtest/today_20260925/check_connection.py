"""Read-only local SDK/history/WebSocket probe; never submits an order."""

import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from database.auth_db import (
        db_session,
        get_api_key_for_tradingview,
        get_auth_token_broker,
        verify_api_key,
    )

    with closing(
        sqlite3.connect((ROOT / "db/market_scanner_live.db").as_uri() + "?mode=ro", uri=True)
    ) as db:
        rows = db.execute("SELECT user FROM scanner_live_accounts WHERE broker='fyers'").fetchall()
    assert len(rows) == 1
    try:
        key = get_api_key_for_tradingview(rows[0][0])
    finally:
        db_session.remove()
    assert key, "No existing API key"
    print("Stored key verifies locally:", bool(verify_api_key(key)), flush=True)
    auth = get_auth_token_broker(key)
    print("Local broker session available:", bool(auth[0]), flush=True)
    if not auth[0]:
        (HERE / "connection_check.json").write_text(
            json.dumps(
                {
                    "status": "WAITING_FOR_BROKER_LOGIN",
                    "api_key_valid_locally": True,
                    "orders_sent": 0,
                },
                indent=2,
            )
        )
        raise RuntimeError("Complete FYERS login in OpenAlgo; the API key itself is valid")
    db_session.remove()
    from openalgo import api

    client = api(
        api_key=key,
        host="http://127.0.0.1:5000",
        ws_url=os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765"),
        verbose=0,
    )
    received = []

    def receive(message):
        if len(received) < 3:
            received.append({k: message.get(k) for k in ["type", "symbol", "exchange", "mode"]})

    try:
        candles = client.history(
            symbol="ADSL",
            exchange="NSE",
            interval="1m",
            start_date="2026-09-25",
            end_date="2026-09-25",
        )
        if not hasattr(candles, "empty") or candles.empty:
            safe = (
                {
                    k: str(candles.get(k, "")).replace(key, "[redacted]")[:400]
                    for k in ["status", "message", "code"]
                }
                if isinstance(candles, dict)
                else {"message": "Empty history DataFrame"}
            )
            (HERE / "connection_check.json").write_text(
                json.dumps({"status": "FAILED", "history": safe, "orders_sent": 0}, indent=2)
            )
            raise RuntimeError(json.dumps(safe))
        connected = client.connect()
        subscribed = (
            client.subscribe_quote(
                [{"symbol": "ADSL", "exchange": "NSE"}], on_data_received=receive
            )
            if connected
            else False
        )
        time.sleep(3)
        result = {
            "history_rows": len(candles),
            "history_last": str(candles.index[-1]),
            "websocket_authenticated": bool(client.authenticated),
            "subscription_sent": bool(subscribed),
            "observed_messages": received,
            "orders_sent": 0,
            "note": "After-hours transport check; live session quote timing remains unverified",
        }
        (HERE / "connection_check.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        try:
            if client.connected:
                client.unsubscribe_quote([{"symbol": "ADSL", "exchange": "NSE"}])
            client.disconnect()
        finally:
            client.close()


if __name__ == "__main__":
    main()
