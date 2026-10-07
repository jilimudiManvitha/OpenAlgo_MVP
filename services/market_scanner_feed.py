"""Account-owned Quote subscription to OpenAlgo's shared broker WebSocket proxy."""

import math
import os
import time
from datetime import datetime

from services.market_scanner_service import IST, quote_time
from utils.real_threading import Event, Lock, Thread


def stream_limit(broker):
    """Leave FYERS pool capacity for scheduled equities, both option weeks and tools.

    The scanner still refreshes its full universe through the existing REST pass.
    FYERS has 3,000 shared slots; an unconstrained scanner formerly consumed 2,679.
    """
    requested = max(1, min(5000, int(os.environ.get("SCANNER_STREAM_LIMIT", "5000"))))
    return min(requested, 1000) if broker == "fyers" else requested


def merge_quote(row, message, now):
    """Only complete, newer, timestamped Quote ticks may refresh a scanner row."""
    if message.get("mode") not in (2, "2", "Quote", "QUOTE"):
        return row
    quote = message.get("data", {})
    try:
        received = quote_time(quote.get("timestamp"))
        traded = quote_time(quote.get("last_traded_time") or quote.get("last_trade_time"))
        price = float(quote["ltp"])
        volume = float(quote["volume"])
        previous = float(row["previous_close"])
        if not all(math.isfinite(v) for v in (price, volume, previous)):
            return row
        if price <= 0 or previous <= 0 or volume < 0:
            return row
        if (
            not 0 <= (now - received).total_seconds() <= 30
            or traded.date() != now.date()
            or traded > now
        ):
            return row
        previous_stamp = datetime.fromisoformat(row["quote_fetched_at"])
        if received < previous_stamp:
            return row
        if received == previous_stamp and price == row["ltp"] and volume == row.get("volume"):
            return row
        # An old tick cannot rewind cumulative volume within a session.
        if row.get("volume") is not None and volume < row["volume"]:
            return row
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return row
    result = dict(
        row,
        ltp=price,
        volume=volume,
        change=price - previous,
        change_percent=(price / previous - 1) * 100,
        quote_fetched_at=received.isoformat(),
        last_trade_at=traded.isoformat(),
        quote_source="shared_websocket",
    )
    baseline = result.get("average_volume")
    result["rvol"] = volume / baseline if baseline and baseline > 0 else None
    return result


class ScannerFeed:
    """One proxy connection per elected account, never per browser or row.

    The proxy shares the existing broker adapter. Owning our proxy connection
    lets disconnect release only scanner subscriptions, preserving other tools.
    Unsubscribed/refused symbols continue through the full-universe REST pass.
    """

    def __init__(self, user, broker, store, owner):
        self.user, self.broker, self.store, self.owner = user, broker, store, owner
        self.stop_event = Event()
        self.lock = Lock()
        self.client = None
        self.thread = None
        self.subscribed = 0
        self.status = "polling_fallback"
        self.limit = stream_limit(broker)

    def start(self):
        self.thread = Thread(target=self._run, daemon=True, name="scanner-shared-feed")
        self.thread.start()

    def _run(self):
        from database.auth_db import db_session, get_api_key_for_tradingview
        from services.market_scanner_provider import credentials, universe_for
        from services.websocket_client import WebSocketClient

        delay = 5
        while not self.stop_event.is_set() and self.store.owns(self.owner):
            client = None
            try:
                credentials(self.user, self.broker)
                try:
                    key = get_api_key_for_tradingview(self.user)
                finally:
                    db_session.remove()
                if not key:
                    self.stop_event.wait(60)
                    continue
                client = WebSocketClient(
                    key,
                    host=os.environ.get("WEBSOCKET_HOST", "localhost"),
                    port=int(os.environ.get("WEBSOCKET_PORT", "8765")),
                )
                if not client.connect():
                    raise ConnectionError("Shared proxy unavailable")
                universe = universe_for(self.broker)[: self.limit]
                for offset in range(0, len(universe), 50):
                    if self.stop_event.is_set() or not self.store.owns(self.owner):
                        break
                    reply = client.subscribe(
                        [
                            {"symbol": i["symbol"], "exchange": "NSE"}
                            for i in universe[offset : offset + 50]
                        ],
                        "Quote",
                    )
                    if reply.get("status") == "error":
                        break
                with self.lock:
                    self.client = client
                self.subscribed = client.get_subscriptions()["count"]
                self.status = (
                    "shared_websocket_and_polling" if self.subscribed else "polling_fallback"
                )
                delay = 5
                while not self.stop_event.wait(5):
                    if not self.store.owns(self.owner):
                        return
                    credentials(self.user, self.broker)
                    if not client.connected or not client.authenticated:
                        break
            except Exception:
                self.status = "polling_fallback"
            finally:
                with self.lock:
                    self.client = None
                if client is not None:
                    client.disconnect()
                self.subscribed = 0
            self.stop_event.wait(delay)
            delay = min(120, delay * 2)

    def merge(self, rows, now):
        with self.lock:
            client = self.client
        if client is None:
            return rows
        cached = client.get_market_data()
        return [merge_quote(row, cached.get(f"NSE:{row['symbol']}", {}), now) for row in rows]

    def close(self):
        self.stop_event.set()
        # The loop owns disconnect and releases it on every error/reconnect path.
        if self.thread:
            self.thread.join(timeout=1)
