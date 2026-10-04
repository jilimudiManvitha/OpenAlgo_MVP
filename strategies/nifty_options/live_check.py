"""Read-only checks of the installed schedules, symbol master and quote proxy."""

import json
import time
from datetime import datetime
from types import SimpleNamespace

from dotenv import load_dotenv

from .engine import IST
from .execution import cleanup_sessions
from .history import atomic_json
from .profiles import PROFILES, ROOT
from .runtime import broker_margin, instruments
from .schedule import verify


def main():
    load_dotenv(ROOT / ".env")
    from database.auth_db import get_api_key_for_tradingview
    from services.websocket_client import WebSocketClient

    saved = json.loads((ROOT / "strategies/strategy_configs.json").read_text())
    owners = {v["user_id"] for k, v in saved.items() if k.startswith("Nifty12_")}
    if len(owners) != 1:
        raise RuntimeError("Expected one installed strategy owner")
    owner = owners.pop()
    try:
        key = get_api_key_for_tradingview(owner)
    finally:
        cleanup_sessions()
    if not key:
        raise RuntimeError("No authenticated scheduler key")
    contracts, expiries = instruments(datetime.now(IST).date())
    if len(expiries) < 2 or not contracts:
        raise RuntimeError("Current and next NIFTY contracts unavailable")
    selected = min(contracts, key=lambda c: abs(c["strike"] - 24000))
    expiry = str(expiries[0])
    sample_legs = []
    for kind, strike, side in (
        ("CE", 24000, -1),
        ("PE", 24000, -1),
        ("CE", 24200, 1),
        ("PE", 23800, 1),
    ):
        c = next(
            c
            for c in contracts
            if c["expiry"] == expiry and c["kind"] == kind and c["strike"] == strike
        )
        sample_legs.append((SimpleNamespace(symbol=c["symbol"], lot_size=c["lot_size"]), side))
    sample_margin = broker_margin(owner, sample_legs, PROFILES["iron_condor_intraday_current_week"])
    client = WebSocketClient(key)
    messages = []

    def receive(message):
        if len(messages) < 10:
            messages.append(message.get("symbol"))

    client.register_callback("market_data", receive)
    try:
        if not client.connect():
            raise RuntimeError("Quote proxy connection/authentication failed")
        response = client.subscribe(
            [
                {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
                {"symbol": selected["symbol"], "exchange": "NFO"},
            ],
            "Quote",
        )
        if response.get("status") != "success":
            raise RuntimeError("Read-only quote subscription failed")
        time.sleep(2)
        result = {
            "schedules_verified": len(verify()),
            "catalogue_contracts": len(contracts),
            "current_expiry": str(expiries[0]),
            "next_expiry": str(expiries[1]),
            "websocket_authenticated": client.authenticated,
            "subscription_accepted": True,
            "sample_messages": len(messages),
            "orders_submitted": 0,
            "broker_sample_basket_margin_inr": sample_margin,
            "limitation": "Outside market hours: fresh live ticks and market-hour order fills remain unverified.",
        }
    finally:
        client.unregister_callback("market_data", receive)
        client.disconnect()
        cleanup_sessions()
    atomic_json(ROOT / "backtest/nifty_options/verification/live_checks.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
