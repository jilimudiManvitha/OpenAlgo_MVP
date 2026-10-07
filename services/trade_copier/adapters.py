"""Account-scoped transports. No ambient BROKER_API_KEY for child execution.

POST/PUT/DELETE are issued once. A timeout/5xx/malformed ACK is UNKNOWN,
never grounds for an automatic resend. Broker messages are not persisted: they
can echo submitted secrets. Native transports use fixed HTTPS broker origins.
"""

import json
import re
from urllib.parse import urlsplit

from services.trade_copier.domain import CopierError
from utils.httpx_client import get_httpx_client


class BrokerFailure(CopierError):
    def __init__(self, state="DEGRADED", message="Broker request failed"):
        super().__init__(message)
        self.state = state


def reply(status, orderid="", message=""):
    return {"status": status, "orderid": str(orderid), "message": message}


def http(method, url, headers, payload=None, form=False, mutation=False):
    try:
        kwargs = {"data" if form else "json": payload} if payload is not None else {}
        response = get_httpx_client().request(
            method, url, headers=headers, timeout=4.0, follow_redirects=False, **kwargs
        )
        code = response.status_code
        if code in (401, 403):
            raise BrokerFailure("AUTH_REQUIRED", "Broker authentication required")
        if code == 429:
            raise BrokerFailure("RATE_LIMITED", "Broker rate limit reached; no retry sent")
        if code >= 500 or code < 200 or code >= 300:
            raise BrokerFailure(
                "UNKNOWN" if mutation and code >= 500 else "REJECTED", f"Broker HTTP {code}"
            )
        return response.json()
    except BrokerFailure:
        raise
    except Exception:
        raise BrokerFailure(
            "UNKNOWN" if mutation else "DEGRADED",
            "Broker response unavailable; reconcile before continuing",
        ) from None


def gateway_url(value):
    u = urlsplit(value)
    if u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise CopierError("Use only the child OpenAlgo origin, without credentials or a path")
    # Localhost is intentional for local independent child installations. No LAN HTTP.
    if u.scheme != "https" and not (
        u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise CopierError("Child OpenAlgo requires HTTPS, or HTTP on localhost")
    if not u.hostname or u.hostname in ("169.254.169.254", "metadata.google.internal"):
        raise CopierError("Invalid child OpenAlgo origin")
    return value.rstrip("/")


class Native:
    def __init__(self, broker, secret):
        self.broker, self.secret = broker, secret
        token = secret["access_token"]
        app = secret.get("app_id", "")
        if broker == "fyers":
            self.origin = "https://api-t1.fyers.in/api/v3"
            self.headers = {"Authorization": f"{app}:{token}"}
        elif broker == "zerodha":
            self.origin = "https://api.kite.trade"
            self.headers = {"Authorization": f"token {app}:{token}", "X-Kite-Version": "3"}
        elif broker == "dhan":
            self.origin = "https://api.dhan.co/v2"
            self.headers = {"access-token": token, "client-id": secret["client_id"]}
        else:
            raise CopierError("Use an OpenAlgo child connection for this broker")

    def request(self, method, path, payload=None, mutation=False):
        data = http(
            method,
            self.origin + path,
            self.headers,
            payload,
            form=self.broker == "zerodha",
            mutation=mutation,
        )
        if isinstance(data, dict) and (
            data.get("s") == "error" or data.get("status") == "error" or data.get("errorType")
        ):
            raise BrokerFailure(
                "REJECTED", "Broker rejected the request; check the child broker orderbook"
            )
        return data

    def profile_identity(self):
        if self.broker == "fyers":
            data = self.request("GET", "/profile")
            identity = data.get("data", {}).get("fy_id")
        elif self.broker == "zerodha":
            data = self.request("GET", "/user/profile")
            identity = data.get("data", {}).get("user_id")
        else:
            data = self.request("GET", "/profile")
            identity = data.get("dhanClientId")
        if not identity:
            raise BrokerFailure("AUTH_REQUIRED", "Broker profile identity unavailable")
        return str(identity)

    def verify(self):
        identity = self.profile_identity()
        if identity != self.secret["client_id"]:
            raise BrokerFailure("AUTH_REQUIRED", "Token does not match the child client ID")
        return identity

    def instrument(self, o):
        key = f"{o['exchange']}:{o['symbol']}"
        mapping = self.secret.get("instruments", {}).get(key)
        if mapping:
            return mapping
        if o["exchange"] in ("NSE", "BSE") and re.fullmatch(r"[A-Z0-9&._-]+", o["symbol"]):
            if self.broker == "fyers" and o["exchange"] == "NSE":
                return f"{o['exchange']}:{o['symbol']}-EQ"
            if self.broker == "zerodha":
                return o["symbol"]
        raise BrokerFailure(
            "REJECTED", f"Add a verified {self.broker} instrument mapping for {key}"
        )

    def execute(self, action, o, tag, orderid=""):
        if orderid and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", orderid):
            raise CopierError("Invalid broker order ID")
        b = self.broker
        if b == "fyers":
            payload = {
                "symbol": self.instrument(o),
                "qty": o["quantity"],
                "type": {"LIMIT": 1, "MARKET": 2, "SL-M": 3, "SL": 4}[o["pricetype"]],
                "side": 1 if o["action"] == "BUY" else -1,
                "productType": {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}[o["product"]],
                "limitPrice": o["price"],
                "stopPrice": o["trigger_price"],
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0,
                "orderTag": tag,
            }
            if action == "MODIFY":
                payload = {k: payload[k] for k in ("qty", "type", "limitPrice", "stopPrice")}
                payload["id"] = orderid
            elif action == "CANCEL":
                payload = {"id": orderid}
            data = self.request(
                {"PLACE": "POST", "MODIFY": "PATCH", "CANCEL": "DELETE"}[action],
                "/orders/sync",
                payload,
                True,
            )
            oid = data.get("id")
        elif b == "zerodha":
            payload = {
                "tradingsymbol": self.instrument(o),
                "exchange": o["exchange"],
                "transaction_type": o["action"],
                "quantity": o["quantity"],
                "order_type": o["pricetype"],
                "product": o["product"],
                "price": o["price"],
                "trigger_price": o["trigger_price"],
                "validity": "DAY",
                "tag": tag,
                "market_protection": -1,
            }
            if o["exchange"] == "MCX":
                raise BrokerFailure(
                    "REJECTED",
                    "Zerodha MCX units require a contract conversion; use the OpenAlgo child connection",
                )
            if action == "MODIFY":
                payload = {
                    k: payload[k]
                    for k in ("quantity", "order_type", "price", "trigger_price", "validity")
                }
            if action == "CANCEL":
                payload = None
            data = self.request(
                {"PLACE": "POST", "MODIFY": "PUT", "CANCEL": "DELETE"}[action],
                "/orders/regular" + (f"/{orderid}" if action != "PLACE" else ""),
                payload,
                True,
            )
            oid = data.get("data", {}).get("order_id")
        else:
            # Native Dhan SL-M emulation depends on broker-specific tick/MPP rules;
            # reject rather than silently turn a resting stop into a market order.
            if o["pricetype"] == "SL-M" and action != "CANCEL":
                raise BrokerFailure(
                    "REJECTED",
                    "Use SL with a limit price, or the Dhan OpenAlgo child connection for SL-M",
                )
            payload = {
                "dhanClientId": self.secret["client_id"],
                "correlationId": tag,
                "transactionType": o["action"],
                "exchangeSegment": {
                    "NSE": "NSE_EQ",
                    "BSE": "BSE_EQ",
                    "NFO": "NSE_FNO",
                    "BFO": "BSE_FNO",
                    "MCX": "MCX_COMM",
                    "CDS": "NSE_CURRENCY",
                    "BCD": "BSE_CURRENCY",
                }[o["exchange"]],
                "productType": {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}[o["product"]],
                "orderType": {
                    "MARKET": "MARKET",
                    "LIMIT": "LIMIT",
                    "SL": "STOP_LOSS",
                    "SL-M": "STOP_LOSS_MARKET",
                }[o["pricetype"]],
                "validity": "DAY",
                "securityId": self.instrument(o),
                "quantity": o["quantity"],
                "price": o["price"],
                "triggerPrice": o["trigger_price"],
            }
            if action == "MODIFY":
                payload = {
                    k: payload[k]
                    for k in (
                        "dhanClientId",
                        "orderType",
                        "quantity",
                        "price",
                        "triggerPrice",
                        "validity",
                    )
                }
                payload["orderId"] = orderid
            if action == "CANCEL":
                payload = None
            data = self.request(
                {"PLACE": "POST", "MODIFY": "PUT", "CANCEL": "DELETE"}[action],
                "/orders" + (f"/{orderid}" if action != "PLACE" else ""),
                payload,
                True,
            )
            oid = data.get("orderId")
        if not oid:
            return reply(
                "UNKNOWN", message="Missing broker acknowledgement; reconcile before continuing"
            )
        return reply("ACKNOWLEDGED", oid)

    def orders(self):
        data = self.request("GET", "/orders")
        if self.broker == "fyers":
            rows = data.get("orderBook")
            result = [
                {
                    "orderid": str(r["id"]),
                    "tag": str(r.get("orderTag") or "").removeprefix("1:"),
                    "status": {1: "cancelled", 2: "complete", 5: "rejected", 6: "open"}.get(
                        r["status"], "open"
                    ),
                    "filled": int(r.get("filledQty", 0)),
                    "average_price": float(r.get("tradedPrice", 0)),
                }
                for r in rows or []
            ]
        elif self.broker == "zerodha":
            rows = data.get("data")
            result = [
                {
                    "orderid": str(r["order_id"]),
                    "tag": r.get("tag", ""),
                    "status": r["status"].lower(),
                    "filled": int(r.get("filled_quantity", 0)),
                    "average_price": float(r.get("average_price", 0)),
                }
                for r in rows or []
            ]
        else:
            rows = data if isinstance(data, list) else None
            result = [
                {
                    "orderid": str(r["orderId"]),
                    "tag": r.get("correlationId", ""),
                    "status": {
                        "TRADED": "complete",
                        "CANCELLED": "cancelled",
                        "REJECTED": "rejected",
                        "EXPIRED": "expired",
                    }.get(r["orderStatus"], "open"),
                    "filled": int(r.get("filledQty", 0)),
                    "average_price": float(r.get("averageTradedPrice", 0)),
                }
                for r in rows or []
            ]
        if not isinstance(rows, list):
            raise BrokerFailure(message="Invalid broker orderbook")
        return result

    def risk(self):
        path = "/portfolio/positions" if self.broker == "zerodha" else "/positions"
        data = self.request("GET", path)
        if self.broker == "fyers":
            rows = data.get("netPositions")
            pnl = data.get("overall", {}).get("pl_total")
        elif self.broker == "zerodha":
            rows = data.get("data", {}).get("net")
            pnl = sum(float(r["pnl"]) for r in rows) if isinstance(rows, list) else None
        else:
            rows = data if isinstance(data, list) else None
            pnl = (
                sum(float(r["realizedProfit"]) + float(r["unrealizedProfit"]) for r in rows)
                if isinstance(rows, list)
                else None
            )
        if not isinstance(rows, list) or pnl is None:
            raise BrokerFailure(message="Position/loss snapshot unavailable")
        # Sum absolute account-wide exposure: conservative across instruments/products.
        qty = sum(abs(int(r.get("netQty", r.get("quantity", 0)))) for r in rows)
        return {"pnl": float(pnl), "quantity": qty}


class Paper:
    def __init__(self, user):
        self.user = user

    def verify(self):
        return self.user

    def execute(self, action, o, tag, orderid=""):
        from database.sandbox_db import db_session
        from sandbox.order_manager import OrderManager

        try:
            manager = OrderManager(self.user)
            payload = dict(o, price_type=o["pricetype"], strategy=tag)
            if action == "PLACE":
                ok, data, code = manager.place_order(payload)
            elif action == "MODIFY":
                ok, data, code = manager.modify_order(orderid, payload)
            else:
                ok, data, code = manager.cancel_order(orderid)
            return reply(
                "ACKNOWLEDGED" if ok else ("UNKNOWN" if code >= 500 else "REJECTED"),
                data.get("orderid", orderid),
                "" if ok else "Sandbox rejected the request; inspect sandbox orderbook",
            )
        finally:
            db_session.remove()

    def orders(self):
        from database.sandbox_db import db_session
        from sandbox.order_manager import OrderManager

        try:
            ok, data, _ = OrderManager(self.user).get_orderbook()
            if not ok:
                raise BrokerFailure(message="Sandbox orderbook unavailable")
            return [
                dict(
                    r,
                    tag=r.get("strategy", ""),
                    status=r["order_status"],
                    filled=r["filled_quantity"],
                )
                for r in data["data"]["orders"]
            ]
        finally:
            db_session.remove()

    def risk(self):
        from database.sandbox_db import SandboxPositions, db_session

        try:
            rows = SandboxPositions.query.filter_by(user_id=self.user).all()
            return {
                "pnl": sum(
                    float(r.today_realized_pnl or 0) + (float(r.pnl or 0) if r.quantity else 0)
                    for r in rows
                ),
                "quantity": sum(abs(int(r.quantity)) for r in rows),
            }
        finally:
            db_session.remove()


class Gateway:
    """Versioned, mode-explicit bridge on a separate OpenAlgo child installation."""

    def __init__(self, secret, mode, broker):
        self.origin = gateway_url(secret["url"])
        self.secret, self.mode, self.broker = secret, mode, broker

    def call(self, operation, **data):
        result = http(
            "POST",
            self.origin + "/trade-copier/bridge",
            {},
            dict(
                apikey=self.secret["api_key"],
                mode=self.mode,
                broker=self.broker,
                operation=operation,
                **data,
            ),
            mutation=operation == "execute",
        )
        if result.get("status") != "success":
            raise BrokerFailure("DEGRADED", "Child OpenAlgo bridge rejected the request")
        return result["data"]

    def verify(self):
        data = self.call("health")
        if (
            data.get("version") != 1
            or data.get("broker") != self.broker
            or data.get("mode") != self.mode
        ):
            raise BrokerFailure(
                message="Child needs the compatible Trade Copier bridge and matching broker/mode"
            )
        return data["identity"]

    def execute(self, action, o, tag, orderid=""):
        return self.call("execute", action=action, order=o, key=tag, orderid=orderid)

    def orders(self):
        return self.call("orders")

    def risk(self):
        return self.call("risk")
