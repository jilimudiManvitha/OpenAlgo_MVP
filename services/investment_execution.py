"""Explicit, mode-pinned stock orders from Portfolio. No orders on GET or mode switch."""

import json
import re
from datetime import datetime
from pathlib import Path

from database.investment_execution_db import InvestmentExecution as Execution
from services import investment_service as s
from services.investment_mode import active_mode
from services.report_brokerage import IST, order_cost, tariff


def capabilities(broker, mode):
    # Discover shipped adapters; never attempt an unsupported broker fallback.
    native = (
        bool(re.fullmatch(r"[a-z0-9_]+", broker or ""))
        and (Path(__file__).resolve().parents[1] / "broker" / broker / "api/gtt_api.py").is_file()
    )
    return {"broker": broker, "mode": mode, "orders": True, "gtt": mode == "paper" or native}


def authenticate(user, broker):
    from database.auth_db import db_session, get_order_mode
    from services.market_scanner_provider import ScannerError, credentials

    try:
        if get_order_mode(user) == "semi_auto":
            raise s.InvestmentError(
                "Portfolio order entry requires Auto mode; use Action Center in Semi-Auto mode.",
                409,
            )
        return credentials(user, broker)[0]
    except ScannerError as exc:
        raise s.InvestmentError(str(exc), 401) from None
    finally:
        db_session.remove()


def validate(user, mode, payload, estimating=False):
    with s.transaction() as session:
        asset = s.owned(session, s.Asset, user, payload.get("asset_id"))
        account = s.owned(session, s.Account, user, asset.account_id)
        if account.kind != mode:
            raise s.InvestmentError("The instrument belongs to a different trading mode.", 409)
        if asset.asset_class != "STOCK" or asset.exchange not in ("NSE", "BSE"):
            raise s.InvestmentError("Order entry supports NSE/BSE stocks and ETFs.")
        symbol, exchange = asset.symbol, asset.exchange
    quantity = s.decimal(payload.get("quantity"), "quantity", 0, True)
    if quantity > 1_000_000:
        raise s.InvestmentError("Quantity exceeds the supported order size")
    kind, action = payload.get("kind"), payload.get("action")
    if kind not in ("order", "gtt") or action not in ("BUY", "SELL"):
        raise s.InvestmentError("Choose order/GTT and BUY/SELL")
    price = s.decimal(payload.get("price"), "price", 4 if estimating else 2, True)
    data = {
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "quantity": int(quantity),
        "product": "CNC",
        "pricetype": "LIMIT",
        "price": float(price),
        "trigger_price": 0,
        "disclosed_quantity": 0,
    }
    if kind == "gtt":
        trigger = s.decimal(payload.get("trigger_price"), "trigger price", 2, True)
        reference = s.decimal(payload.get("reference_price"), "reference price", 2, True)
        if trigger == reference:
            raise s.InvestmentError("Trigger must differ from the reference price")
        data.update(trigger_type="SINGLE", reference_price=float(reference))
        data["triggerprice_sl" if trigger < reference else "triggerprice_tg"] = float(trigger)
    return data


def estimate(broker, data, trade_date=None):
    try:
        if trade_date is not None and (
            not isinstance(trade_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", trade_date)
        ):
            raise ValueError("Trade date must be YYYY-MM-DD")
        rates = tariff(broker)
        if rates is None:
            raise ValueError("No verified standard retail tariff for this broker")
        day = (
            datetime.fromisoformat(trade_date).date().isoformat()
            if trade_date
            else datetime.now(IST).date().isoformat()
        )
        costs = order_cost(
            data["quantity"] * data["price"],
            data["action"],
            data["exchange"],
            "delivery",
            day,
            rates,
        )
        return {
            "status": "estimated",
            "total": round(sum(costs.values()), 2),
            "breakdown": costs,
            "broker": broker,
            "version": rates["version"],
        }
    except ValueError as exc:
        return {"status": "unavailable", "message": str(exc), "broker": broker}


def tick_check(data):
    from decimal import Decimal

    from database.symbol import db_session
    from database.token_db import get_symbol_info

    try:
        info = get_symbol_info(data["symbol"], data["exchange"])
        if info is None:
            raise s.InvestmentError("Instrument is absent from the current symbol master")
        tick = Decimal(str(info.tick_size or "0.05"))
        for field in ("price", "triggerprice_sl", "triggerprice_tg"):
            if data.get(field) and Decimal(str(data[field])) % tick:
                raise s.InvestmentError(f"{field} must follow tick size {tick}")
    finally:
        db_session.remove()


def dispatch(user, broker, mode, kind, data, token):
    if mode == "paper":
        from database.sandbox_db import db_session

        try:
            if kind == "gtt":
                from sandbox.gtt_manager import GTTManager

                return GTTManager(user).place_gtt(data, data["reference_price"])
            from sandbox.order_manager import OrderManager

            return OrderManager(user).place_order(data)
        finally:
            db_session.remove()
    if kind == "gtt":
        # This service refuses missing API-key sandbox dispatch if the global
        # switch changes during the request; it can never create a paper fill.
        from services.place_gtt_order_service import place_gtt_order

        return place_gtt_order(data, auth_token=token, broker=broker)
    from services.place_order_service import place_order_with_auth

    return place_order_with_auth(data, token, broker, data, force_live=True)


def submit(user, broker, mode, payload):
    if payload.get("confirm") is not True:
        raise s.InvestmentError("Review and confirm the order first")
    key = payload.get("request_key", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", key):
        raise s.InvestmentError("A stable request key is required")
    if mode != active_mode():
        raise s.InvestmentError("Trading mode changed. Reload before submitting.", 409)
    data = validate(user, mode, payload)
    kind = payload["kind"]
    if not capabilities(broker, mode)["gtt"] and kind == "gtt":
        raise s.InvestmentError(f"Native Live GTT is not supported for {broker}.", 501)
    encoded = json.dumps(data, sort_keys=True)
    # Retry check precedes credentials and quotes. A timeout must never resubmit.
    with s.transaction(True) as session:
        old = session.query(Execution).filter_by(user_id=user, request_key=key).first()
        if old:
            if (old.payload, old.broker, old.mode, old.kind, old.asset_id) != (
                encoded,
                broker,
                mode,
                kind,
                int(payload["asset_id"]),
            ):
                raise s.InvestmentError("Request key belongs to another order", 409)
            return s.serialize(old)
    token = authenticate(user, broker)
    tick_check(data)
    with s.transaction(True) as session:
        # Recheck under the write lock to close simultaneous-submit races.
        if session.query(Execution).filter_by(user_id=user, request_key=key).first():
            raise s.InvestmentError("Request already recorded. Refresh its status.", 409)
        if session.query(Execution).filter_by(user_id=user).count() >= 10000:
            raise s.InvestmentError("Portfolio order history limit reached", 409)
        row = Execution(
            user_id=user,
            asset_id=payload["asset_id"],
            broker=broker,
            mode=mode,
            kind=kind,
            request_key=key,
            payload=encoded,
            status="dispatching",
        )
        session.add(row)
        session.flush()
        record_id = row.id
    data["strategy"] = f"Portfolio_{record_id}"
    try:
        ok, response, code = dispatch(user, broker, mode, kind, data, token)
    except Exception:
        ok, response, code = (
            False,
            {"message": "Outcome unknown. Check order book; do not submit a replacement."},
            500,
        )
    with s.transaction(True) as session:
        row = s.owned(session, Execution, user, record_id)
        external_id = response.get("trigger_id" if kind == "gtt" else "orderid")
        if ok and external_id:
            row.status, row.external_id = "accepted", str(external_id)
        elif code < 500:
            row.status = "rejected"
        else:
            row.status = "unknown"
        row.message = str(response.get("message", "Accepted; check order book for fills."))[:500]
        return s.serialize(row)


def orders(user, broker, mode):
    with s.transaction() as session:
        return [
            s.serialize(row)
            for row in session.query(Execution)
            .filter_by(user_id=user, broker=broker, mode=mode)
            .order_by(Execution.id.desc())
            .limit(1000)
        ]
