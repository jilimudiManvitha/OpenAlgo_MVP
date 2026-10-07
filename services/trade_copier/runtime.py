"""Opt-in wiring to the current OpenAlgo session. No production startup side effects."""

import atexit
import hashlib
import importlib
import os
import threading
from pathlib import Path

from services.trade_copier.adapters import BrokerFailure, Native, Paper
from services.trade_copier.domain import CopierError, digest, order

_lock = threading.Lock()
_engine = None
_lock_file = None


def active_mode():
    from database.settings_db import db_session, get_analyze_mode

    try:
        return "paper" if get_analyze_mode() else "live"
    finally:
        db_session.remove()


def credentials(owner, broker):
    from services.market_scanner_provider import credentials as read

    try:
        return read(owner, broker)[0]
    except Exception:
        raise CopierError("Master broker session needs login") from None


def context(owner, mode, broker, expected_identity=None):
    try:
        if mode != active_mode():
            return False
        token = credentials(owner, broker)
        if expected_identity:
            import json

            if token_identity(broker, token) not in json.loads(expected_identity):
                return False
        return True
    except CopierError:
        return False


def token_identity(broker, token):
    return broker + ":" + hashlib.sha256(token.encode()).hexdigest()


def source(owner, mode, broker):
    token = credentials(owner, broker)
    identities = [token_identity(broker, token)]
    if mode == "paper":
        rows = Paper(owner).orders()
    else:
        from database.auth_db import db_session
        from services.orderbook_service import get_orderbook_with_auth

        try:
            ok, data, _ = get_orderbook_with_auth(token, broker)
            if not ok:
                raise CopierError("Master orderbook unavailable")
            rows = data["data"]["orders"]
            from collections import defaultdict

            from services.tradebook_service import get_tradebook_with_auth

            fills = defaultdict(lambda: [0, 0.0])
            ok, trades, _ = get_tradebook_with_auth(token, broker)
            if not ok:
                raise CopierError("Master fills unavailable; cannot reconcile safely")
            for trade in trades["data"]:
                qty = int(trade["quantity"])
                price = float(trade.get("average_price", trade.get("price", 0)))
                bucket = fills[str(trade["orderid"])]
                bucket[0] += qty
                bucket[1] += qty * price
            for row in rows:
                qty, total = fills[str(row["orderid"])]
                row["filled_quantity"] = max(int(row.get("filled_quantity", 0)), qty)
                if row["order_status"] == "complete":
                    row["filled_quantity"] = int(row["quantity"])
                row["average_price"] = total / qty if qty else float(row.get("average_price", 0))
            if broker in ("fyers", "zerodha", "dhan"):
                native = Native(
                    broker,
                    {
                        "app_id": os.getenv("BROKER_API_KEY", ""),
                        "access_token": token,
                        "client_id": "",
                    },
                )
                identities.append(native.profile_identity())
        finally:
            db_session.remove()
    return [order(r) for r in rows], identities


def instrument(o, broker, owner):
    from database.symbol import db_session
    from database.token_db import get_symbol_info

    try:
        info = get_symbol_info(o["symbol"], o["exchange"])
        if not info:
            raise CopierError("Master instrument is missing from the symbol database")
        price = max(o["price"], o["average_price"], o["trigger_price"])
        if not price:
            from services.quotes_service import get_quotes_with_auth

            token = credentials(owner, broker)
            ok, data, _ = get_quotes_with_auth(token, None, broker, o["symbol"], o["exchange"])
            if not ok:
                raise CopierError("Reference quote unavailable; order value cannot be checked")
            price = float(data["data"]["ltp"])
        return {"lot": int(info.lotsize or 1), "price": price, "tick": float(info.tick_size or 0)}
    finally:
        db_session.remove()


def get_engine():
    global _engine, _lock_file
    if os.getenv("TRADE_COPIER_ENABLED", "FALSE").upper() != "TRUE":
        raise CopierError(
            "Trade Copier is installed but not enabled. Enable it on the isolated/local installation before connecting accounts."
        )
    with _lock:
        if _engine:
            return _engine
        # Local deployment only: fail if another worker owns this database.
        # Cloud deployment needs distributed leader fencing, not this file lock.
        import fcntl

        from sqlalchemy.engine import make_url

        from database.auth_db import decrypt_token, encrypt_token
        from services.trade_copier.engine import Engine
        from utils.event_bus import bus

        url = os.getenv("TRADE_COPIER_DATABASE_URL", "sqlite:///db/trade_copier.db")
        parsed = make_url(url)
        if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:":
            raise CopierError("Local copier requires a file-backed SQLite database")
        path = Path(parsed.database).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(str(path) + ".lock", "a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            engine = Engine(url, encrypt_token, decrypt_token, source, context, instrument)
            # Invalidate arming synchronously on every actual mode transition,
            # including Live -> Sandbox -> Live between monitor ticks.
            from sqlalchemy import event

            from database.settings_db import Settings

            def mode_changed(_target, value, old, _initiator):
                if value != old:
                    with engine.lock, engine.sessions.begin() as s:
                        from services.trade_copier.models import Control

                        for c in s.query(Control).all():
                            c.armed = False
                            c.generation += 1
                            c.note = "Live/Sandbox mode changed; review and arm again"

            event.listen(Settings.analyze_mode, "set", mode_changed)
            engine.start(bus)
        except Exception:
            handle.close()
            raise CopierError(
                "Copier could not start, or another local worker owns this database"
            ) from None
        _engine, _lock_file = engine, handle

        def close():
            try:
                engine.close()
            finally:
                event.remove(Settings.analyze_mode, "set", mode_changed)
                handle.close()

        atexit.register(close)
        return engine


class LocalBridge:
    """Dedicated child installation: explicit live transport bypasses global mode routing.

    Only its own broker plugin sees its own environment/symbol database. This is
    what permits all installed OpenAlgo brokers without mutating master globals.
    """

    def __init__(self, owner, mode, broker, api_key=""):
        self.owner, self.mode, self.broker = owner, mode, broker
        self.token = credentials(owner, broker)
        self.api_key = api_key

    def verify(self):
        if self.broker in ("fyers", "zerodha", "dhan"):
            return Native(
                self.broker,
                {
                    "app_id": os.getenv("BROKER_API_KEY", ""),
                    "access_token": self.token,
                    "client_id": "",
                },
            ).profile_identity()
        from database.auth_db import get_user_id

        client_id = get_user_id(self.owner)
        return str(client_id) if client_id else token_identity(self.broker, self.token)

    def execute(self, action, o, tag, orderid=""):
        if not context(self.owner, self.mode, self.broker):
            raise CopierError("Child mode/session changed")
        if self.mode == "paper":
            return Paper(self.owner).execute(action, o, tag, orderid)
        module = importlib.import_module(f"broker.{self.broker}.api.order_api")
        # These direct plugin calls do not re-read analyze mode. The caller has
        # already authenticated, checked exact broker/mode, and durably claimed key.
        payload = dict(o, strategy=tag, orderid=orderid, apikey=self.api_key)
        if action == "PLACE":
            response, data, oid = module.place_order_api(payload, self.token)
            code = getattr(response, "status", getattr(response, "status_code", 500))
        elif action == "MODIFY":
            data, code = module.modify_order(payload, self.token)
            oid = data.get("orderid", orderid)
        else:
            data, code = module.cancel_order(orderid, self.token)
            oid = data.get("orderid", orderid)
        if code == 200 and oid:
            return {"status": "ACKNOWLEDGED", "orderid": str(oid)}
        return {
            "status": "UNKNOWN" if code >= 500 else "REJECTED",
            "orderid": "",
            "message": "Child broker did not acknowledge; inspect its orderbook",
        }

    def orders(self):
        rows, _ = source(self.owner, self.mode, self.broker)
        return [
            {
                "orderid": r["orderid"],
                "status": r["order_status"],
                "filled": r["filled_quantity"],
                "average_price": r["average_price"],
                "tag": "",
            }
            for r in rows
        ]

    def risk(self):
        if self.mode == "paper":
            return Paper(self.owner).risk()
        from services.positionbook_service import get_positionbook_with_auth

        ok, data, _ = get_positionbook_with_auth(self.token, self.broker)
        if not ok or not isinstance(data.get("data"), list):
            raise BrokerFailure(message="Child positions unavailable")
        rows = data["data"]
        return {
            "pnl": sum(float(r["pnl"]) for r in rows),
            "quantity": sum(abs(int(r["quantity"])) for r in rows),
        }
