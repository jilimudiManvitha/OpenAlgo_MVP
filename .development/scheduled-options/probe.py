"""Read-only schedule/log inventory and one owned quote connection; no orders."""
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ["LOG_DIR"] = str(ROOT / "log/test")
from database.auth_db import db_session, get_api_key_for_tradingview
from services.websocket_client import WebSocketClient
from strategies.nifty_options.engine import IST
from strategies.nifty_options.runtime import instruments

raw = (ROOT / "strategies/strategy_configs.json").read_bytes()
saved = json.loads(raw)
print(json.dumps({"schedules": len(saved), "enabled": sum(bool(c.get("is_scheduled")) for c in saved.values()), "sha256": hashlib.sha256(raw).hexdigest()}))
assert len(saved) >= 20
owner = next(c["user_id"] for c in saved.values() if c["name"] == "premium_positional_next_week")
try:
    key = get_api_key_for_tradingview(owner)
finally:
    db_session.remove()
contracts, _ = instruments(datetime.now(IST).date())
client = WebSocketClient(key, host="127.0.0.1")
try:
    assert client.connect(), "Proxy authentication failed"
    specs = [{"symbol": c["symbol"], "exchange": "NFO"} for c in contracts]
    specs.append({"symbol": "NIFTY", "exchange": "NSE_INDEX"})
    for offset in range(0, len(specs), 50):
        reply = client.subscribe(specs[offset:offset+50], "Quote")
        print(json.dumps({"offset": offset, "status": reply.get("status"), "message": reply.get("message"), "results": dict(Counter(r.get("status") for r in reply.get("subscriptions", []))), "errors": [r for r in reply.get("subscriptions", []) if r.get("status") != "success"]}), flush=True)
        if reply.get("status") != "success":
            break
finally:
    client.disconnect()
assert (ROOT / "strategies/strategy_configs.json").read_bytes() == raw
