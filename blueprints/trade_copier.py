"""Copier controls use session authentication + the application's CSRF guard.

Only /bridge is CSRF exempt: it requires a child OpenAlgo API key and a
versioned, explicit broker/mode payload. It is separately opt-in.
"""

import json
import os
import re
import time

from flask import Blueprint, current_app, jsonify, request, session

from limiter import limiter
from services.trade_copier import models as m
from services.trade_copier import runtime
from services.trade_copier.domain import CopierError, digest, order, packed
from utils.session import check_session_validity

trade_copier_bp = Blueprint("trade_copier", __name__, url_prefix="/trade-copier")


def engine():
    return current_app.config.get("TRADE_COPIER_ENGINE") or runtime.get_engine()


def scope():
    owner = session.get("user")
    broker = session.get("broker")
    mode = runtime.active_mode()
    if not owner or not broker:
        raise CopierError("Sign in to a broker first")
    if request.args.get("mode") != mode or request.args.get("broker") != broker:
        raise CopierError("Broker or Live/Sandbox mode changed. Reload this page.")
    return owner, mode, broker


def body():
    if request.content_length and request.content_length > 32768:
        raise CopierError("Request is too large")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise CopierError("A JSON object is required")
    return data


def result(data=None):
    return jsonify(status="success", data=data)


@trade_copier_bp.errorhandler(CopierError)
def invalid(error):
    return jsonify(status="error", message=str(error)), 400


@trade_copier_bp.get("")
@check_session_validity
def page():
    from blueprints.react_app import serve_react_app

    return serve_react_app()


@trade_copier_bp.get("/api/state")
@check_session_validity
def state():
    return result(engine().snapshot(*scope()))


@trade_copier_bp.route("/api/accounts", methods=["POST"])
@trade_copier_bp.route("/api/accounts/<account_id>", methods=["PATCH"])
@check_session_validity
def account(account_id=None):
    owner, mode, _ = scope()
    return result({"id": engine().account(owner, mode, body(), account_id)})


@trade_copier_bp.post("/api/control")
@check_session_validity
def control():
    data = body()
    if data.get("action") == "arm" and data.get("confirm") is not True:
        raise CopierError("Review and confirm arming the copier")
    engine().control(*scope(), data.get("action"))
    return result()


@trade_copier_bp.post("/api/reconcile")
@check_session_validity
def reconcile():
    engine().reconcile(*scope())
    return result()


@trade_copier_bp.post("/api/resolve/<attempt_id>")
@check_session_validity
def resolve(attempt_id):
    owner, mode, _ = scope()
    data = body()
    resolution = data.get("resolution")
    if data.get("confirm") is not True or resolution not in (
        "confirmed_not_placed",
        "confirmed_executed",
    ):
        raise CopierError("Review the child broker orderbook and confirm the outcome")
    e = engine()
    matched = None
    if resolution == "confirmed_executed":
        with e.sessions() as s:
            attempt = s.get(m.Attempt, attempt_id)
            if (
                not attempt
                or attempt.owner != owner
                or attempt.mode != mode
                or attempt.status != "UNKNOWN"
            ):
                raise CopierError("Unknown attempt not found")
            child = s.get(m.Account, attempt.account_id)
        broker_id = str(data.get("broker_orderid", ""))
        matches = [r for r in e.transport(child).orders() if r["orderid"] == broker_id]
        if len(matches) != 1:
            raise CopierError("Broker order ID was not found in this child’s current orderbook")
        matched = matches[0]
    with e.lock, e.sessions.begin() as s:
        job = s.get(m.Attempt, attempt_id)
        if not job or job.owner != owner or job.mode != mode or job.status != "UNKNOWN":
            raise CopierError("Unknown attempt not found")
        if matched:
            job.broker_orderid = matched["orderid"]
            job.status = matched["status"].upper() if job.action == "PLACE" else "ACKNOWLEDGED"
            job.filled = int(matched.get("filled", 0)) if job.action == "PLACE" else 0
            job.average_price = float(matched.get("average_price", 0))
            job.message = "Operator matched this attempt to the child broker orderbook"
        else:
            job.status, job.message = (
                "REJECTED",
                "Operator confirmed not executed; no retry will be sent",
            )
        e.audit(s, owner, mode, "UNKNOWN_RESOLVED_" + resolution.upper(), attempt_id)
    return result()


@trade_copier_bp.post("/bridge")
@limiter.limit("5 per second; 180 per minute")
def bridge():
    if os.getenv("TRADE_COPIER_BRIDGE_ENABLED", "FALSE").upper() != "TRUE":
        return jsonify(status="error", message="Child copier bridge is disabled"), 403
    from database.auth_db import db_session, get_order_mode, verify_api_key

    try:
        data = body()
        owner = verify_api_key(str(data.get("apikey", "")))
        if not owner:
            return jsonify(status="error", message="Invalid child API key"), 403
        mode, broker = data.get("mode"), data.get("broker")
        if (
            not isinstance(broker, str)
            or not re.fullmatch(r"[a-z0-9_]{1,40}", broker)
            or not runtime.context(owner, mode, broker)
        ):
            raise CopierError("Child session, mode or broker does not match")
        if get_order_mode(owner) == "semi_auto":
            raise CopierError(
                "Child must use automatic execution; Action Center approval cannot be bypassed"
            )
        adapter = runtime.LocalBridge(owner, mode, broker, str(data.get("apikey", "")))
        op = data.get("operation")
        if op == "health":
            adapter.risk()  # A DB token alone is not a broker health check.
            return result(
                {"version": 1, "identity": adapter.verify(), "mode": mode, "broker": broker}
            )
        if op == "risk":
            return result(adapter.risk())
        if op == "orders":
            rows = adapter.orders()
            # Recover ACK lost between bridge and master using durable bridge receipts.
            e = engine()
            with e.sessions() as s:
                receipts = (
                    s.query(m.BridgeReceipt)
                    .filter_by(owner=owner, mode=mode)
                    .filter(m.BridgeReceipt.created > time.time() - 86400)
                    .all()
                )
                tags = {
                    json.loads(r.result).get("orderid"): r.key.split(":", 1)[1] for r in receipts
                }
            for row in rows:
                row["tag"] = tags.get(row["orderid"], "")
            return result(rows)
        if op != "execute" or data.get("action") not in ("PLACE", "MODIFY", "CANCEL"):
            raise CopierError("Unsupported bridge operation")
        tag = data.get("key", "")
        if not isinstance(tag, str) or not re.fullmatch(r"cp[a-f0-9]{18}", tag):
            raise CopierError("Invalid idempotency key")
        o = order(data.get("order", {}))
        key = digest(owner, mode) + ":" + tag
        fingerprint = digest(data["action"], o, data.get("orderid", ""), broker)
        e = engine()
        with e.lock, e.sessions.begin() as s:
            receipt = s.get(m.BridgeReceipt, key)
            if receipt:
                if receipt.fingerprint != fingerprint:
                    raise CopierError("Idempotency key belongs to a different request")
                return result(json.loads(receipt.result))
            s.add(
                m.BridgeReceipt(
                    key=key,
                    owner=owner,
                    mode=mode,
                    fingerprint=fingerprint,
                    created=time.time(),
                    result=packed(
                        {
                            "status": "UNKNOWN",
                            "orderid": "",
                            "message": "Submission claimed; reconcile before continuing",
                        }
                    ),
                )
            )
        try:
            answer = adapter.execute(data["action"], o, tag, str(data.get("orderid", "")))
        except Exception:
            answer = {
                "status": "UNKNOWN",
                "orderid": "",
                "message": "Broker result uncertain; inspect child orderbook",
            }
        with e.lock, e.sessions.begin() as s:
            receipt = s.get(m.BridgeReceipt, key)
            receipt.result = packed(answer)
        return result(answer)
    finally:
        db_session.remove()
