"""Explicit portfolio GTTs in the existing Sandbox, with durable idempotent linkage.

Never imports a live order service. The existing Sandbox monitor owns triggering,
freshness, margin, fills and restart recovery. This module reconciles bookkeeping.
"""

import json
import re
from decimal import ROUND_HALF_UP, Decimal

from database.investment_db import InvestmentPaperFill as Fill
from database.investment_db import InvestmentPaperOrder as Link
from database.investment_db import InvestmentWatchItem as Item
from database.investment_db import InvestmentWatchlist as Watchlist
from services import investment_service as s


def tag(record_id):
    return f"InvestmentGTT_{record_id}"


def sandbox_snapshot(user, record_id):
    from database.sandbox_db import SandboxGTT, SandboxOrders, SandboxTrades, db_session

    try:
        rows = db_session.query(SandboxGTT).filter_by(user_id=user, strategy=tag(record_id)).all()
        if len(rows) > 1:
            raise s.InvestmentError("Multiple sandbox triggers match; reconcile manually", 409)
        if not rows:
            return None
        gtt = rows[0]
        orders = (
            db_session.query(SandboxOrders).filter_by(user_id=user, strategy=tag(record_id)).all()
        )
        fills = []
        for order in orders:
            if order.order_status != "complete":
                continue
            trades = (
                db_session.query(SandboxTrades).filter_by(user_id=user, orderid=order.orderid).all()
            )
            if not trades or sum(t.quantity for t in trades) != order.quantity:
                raise s.InvestmentError(
                    "Sandbox fill detail is incomplete; retry reconciliation", 409
                )
            fills.append(
                {
                    "order_id": order.orderid,
                    "symbol": order.symbol,
                    "exchange": order.exchange,
                    "action": order.action,
                    "quantity": order.quantity,
                    "price": str(
                        (
                            sum(Decimal(str(t.price)) * t.quantity for t in trades) / order.quantity
                        ).quantize(Decimal(".0001"), rounding=ROUND_HALF_UP)
                    ),
                    "timestamp": max(t.trade_timestamp for t in trades),
                    "product": order.product,
                }
            )
        return {
            "gtt_id": gtt.gtt_id,
            "status": gtt.gtt_status,
            "margin_blocked": str(gtt.margin_blocked),
            "fills": fills,
        }
    finally:
        db_session.remove()


def dispatch(user, data):
    from database.sandbox_db import db_session
    from database.symbol import db_session as symbols
    from database.token_db import get_symbol_info
    from sandbox.gtt_manager import GTTManager

    try:
        info = get_symbol_info(data["symbol"], data["exchange"])
        if not info:
            return False, {"message": "Instrument is absent from the current symbol master"}, 400
        tick = Decimal(str(info.tick_size or "0.05"))
        for field in ("price", "triggerprice_sl", "triggerprice_tg"):
            if data.get(field) and Decimal(str(data[field])) % tick:
                return False, {"message": f"{field} must follow tick size {tick}"}, 400
        return GTTManager(user).place_gtt(data, data["reference_price"])
    finally:
        db_session.remove()
        symbols.remove()


def place(user, payload):
    request_key = payload.get("request_key", "")
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", request_key):
        raise s.InvestmentError("A stable request_key of 8–64 letters/numbers is required")
    with s.transaction(True) as session:
        asset = s.owned(session, s.Asset, user, payload.get("asset_id"))
        account = s.owned(session, s.Account, user, asset.account_id)
        watch = s.owned(session, Watchlist, user, payload.get("watchlist_id"))
        if account.kind != "paper" or asset.asset_class != "STOCK":
            raise s.InvestmentError(
                "Paper GTTs require a paper account and an NSE/BSE stock or ETF"
            )
        if not session.query(Item).filter_by(watchlist_id=watch.id, asset_id=asset.id).first():
            raise s.InvestmentError("Add this instrument to the selected watchlist first")
        quantity = s.decimal(payload.get("quantity"), "quantity", 0, True)
        if quantity > 1_000_000:
            raise s.InvestmentError("Quantity exceeds the supported order size")
        action, direction = payload.get("action"), payload.get("direction")
        if action not in ("BUY", "SELL") or direction not in ("above", "below"):
            raise s.InvestmentError("Choose BUY/SELL and above/below")
        trigger = s.decimal(payload.get("trigger_price"), "trigger_price", 2, True)
        limit = s.decimal(payload.get("limit_price"), "limit_price", 2, True)
        reference = s.decimal(payload.get("reference_price"), "reference_price", 2, True)
        if (direction == "above" and trigger <= reference) or (
            direction == "below" and trigger >= reference
        ):
            raise s.InvestmentError("Trigger must be on the chosen side of the reference price")
        data = {
            "symbol": asset.symbol,
            "exchange": asset.exchange,
            "product": "CNC",
            "trigger_type": "SINGLE",
            "action": action,
            "quantity": int(quantity),
            "pricetype": "LIMIT",
            "price": str(limit),
            "reference_price": str(reference),
            "triggerprice_tg" if direction == "above" else "triggerprice_sl": str(trigger),
        }
        encoded = json.dumps(data, sort_keys=True)
        existing = session.query(Link).filter_by(user_id=user, request_key=request_key).first()
        if existing:
            if (
                existing.payload != encoded
                or existing.asset_id != asset.id
                or existing.watchlist_id != watch.id
            ):
                raise s.InvestmentError("request_key already belongs to another order", 409)
            return s.serialize(existing)
        if session.query(Link).filter_by(user_id=user).count() >= 1000:
            raise s.InvestmentError("Maximum 1,000 portfolio paper triggers", 409)
        if action == "SELL":
            available = s.replay(s.records(session, asset.id))["quantity"]
            reserved = sum(
                (
                    Decimal(json.loads(r.payload)["quantity"])
                    for r in session.query(Link).filter_by(user_id=user, asset_id=asset.id)
                    if r.status in ("dispatching", "active", "triggered")
                    and json.loads(r.payload)["action"] == "SELL"
                ),
                s.ZERO,
            )
            if quantity > available - reserved:
                raise s.InvestmentError(
                    "Sell quantity exceeds unreserved portfolio units; reconcile fills first", 409
                )
        link = Link(
            user_id=user,
            asset_id=asset.id,
            watchlist_id=watch.id,
            request_key=request_key,
            payload=encoded,
            status="dispatching",
        )
        session.add(link)
        session.flush()
        record_id = link.id
    # The intent commits first. An ambiguous result is never automatically resubmitted.
    try:
        ok, response, code = dispatch(user, {**data, "strategy": tag(record_id)})
    except Exception:
        ok, response, code = (
            False,
            {"message": "Dispatch outcome unknown; reconcile before retrying"},
            500,
        )
    with s.transaction(True) as session:
        link = s.owned(session, Link, user, record_id)
        if ok and response.get("mode") == "analyze":
            link.gtt_id, link.status = response["trigger_id"], "active"
        elif code < 500:
            link.status = "rejected"
        link.message = str(response.get("message", ""))[:500]
        return s.serialize(link)


def orders(user):
    with s.transaction() as session:
        return [
            s.serialize(row)
            for row in session.query(Link)
            .filter_by(user_id=user)
            .order_by(Link.id.desc())
            .limit(1000)
        ]


def reconcile(user):
    updated, imported, errors = 0, 0, []
    # Recover earlier purchase intents before later sale intents after a restart.
    for record in reversed(orders(user)):
        try:
            snapshot = sandbox_snapshot(user, record["id"])
            if snapshot is None:
                if record["status"] != "rejected":
                    errors.append(
                        f"Trigger {record['id']}: no sandbox record; dispatch outcome unknown"
                    )
                continue
            record_imports = 0
            with s.transaction(True) as session:
                link = s.owned(session, Link, user, record["id"])
                asset = s.owned(session, s.Asset, user, link.asset_id)
                intent = json.loads(link.payload)
                for fill in sorted(snapshot["fills"], key=lambda f: f["timestamp"]):
                    if (
                        session.query(Fill)
                        .filter_by(user_id=user, order_id=fill["order_id"])
                        .first()
                    ):
                        continue
                    if (
                        fill["symbol"],
                        fill["exchange"],
                        fill["product"],
                        fill["action"],
                        fill["quantity"],
                    ) != (
                        asset.symbol,
                        asset.exchange,
                        "CNC",
                        intent["action"],
                        intent["quantity"],
                    ):
                        raise s.InvestmentError("Sandbox fill identity mismatch", 409)
                    if (
                        session.query(s.Transaction).filter_by(asset_id=asset.id).count()
                        >= s.MAX_TRANSACTIONS
                    ):
                        raise s.InvestmentError("Maximum transactions reached for this asset", 409)
                    asset.is_watch_only = False
                    stamp = fill["timestamp"]  # Existing sandbox trade clock is naive IST.
                    tx = s.Transaction(
                        user_id=user,
                        asset_id=asset.id,
                        action=fill["action"],
                        quantity=s.decimal(fill["quantity"], "quantity", 0, True),
                        price=s.decimal(fill["price"], "fill price", positive=True),
                        trade_date=stamp.date(),
                        trade_time=stamp.time(),
                        notes=f"Confirmed Sandbox fill {fill['order_id']} · {tag(link.id)}",
                        **dict.fromkeys(s.CHARGES, s.ZERO),
                    )
                    session.add(tx)
                    session.flush()
                    s.rebuild(session, asset)
                    session.add(Fill(user_id=user, order_id=fill["order_id"], transaction_id=tx.id))
                    record_imports += 1
                link.gtt_id = snapshot["gtt_id"]
                link.status = "filled" if snapshot["fills"] else snapshot["status"]
                link.message = (
                    "Reconciled with existing Sandbox. Offline threshold crossings remain unknown."
                )
            imported += record_imports
            updated += 1
        except s.InvestmentError as exc:
            errors.append(f"Trigger {record['id']}: {exc}")
    return {"updated": updated, "imported": imported, "errors": errors}


def cancel(user, record_id):
    from database.sandbox_db import db_session
    from sandbox.gtt_manager import GTTManager

    with s.transaction() as session:
        link = s.owned(session, Link, user, record_id)
        trigger_id = link.gtt_id
    if not trigger_id:
        raise s.InvestmentError("Reconcile this trigger before cancelling", 409)
    try:
        ok, response, code = GTTManager(user).cancel_gtt(trigger_id)
        if not ok:
            raise s.InvestmentError(response.get("message", "Cancellation failed"), code)
    finally:
        db_session.remove()
    with s.transaction(True) as session:
        link = s.owned(session, Link, user, record_id)
        link.status = "cancelled"
    return {"cancelled": True}
