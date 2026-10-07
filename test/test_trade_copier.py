"""Offline copier contracts: never read credentials or send broker requests."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from services.trade_copier import models as m
from services.trade_copier.adapters import BrokerFailure, Gateway, Native
from services.trade_copier.domain import CopierError, order
from services.trade_copier.engine import Engine


def event(**kwargs):
    return (
        dict(
            orderid="MASTER-1",
            symbol="SBIN",
            exchange="NSE",
            action="BUY",
            quantity=10,
            filled_quantity=4,
            price=0,
            trigger_price=0,
            average_price=100,
            pricetype="MARKET",
            product="MIS",
            order_status="open",
            **kwargs,
        )
        if not kwargs
        else {**event(), **kwargs}
    )


class Fake:
    def __init__(self, identity):
        self.identity = identity
        self.calls = []
        self.rows = []
        self.delay = 0
        self.failure = None
        self.pnl = 0
        self.quantity = 0
        self.started = threading.Event()

    def verify(self):
        return self.identity

    def risk(self):
        return {"pnl": self.pnl, "quantity": self.quantity}

    def execute(self, action, o, tag, orderid=""):
        self.calls.append((action, o, tag, orderid))
        self.started.set()
        time.sleep(self.delay)
        if self.failure:
            raise self.failure
        oid = orderid or "CHILD-" + str(len(self.calls))
        self.rows.append(
            {"orderid": oid, "tag": tag, "status": "open", "filled": 0, "average_price": 0}
        )
        return {"status": "ACKNOWLEDGED", "orderid": oid}

    def orders(self):
        return self.rows


@pytest.fixture
def rig(tmp_path):
    vault = Fernet(Fernet.generate_key())
    fakes = {}
    state = {"rows": [], "current": True}

    def factory(a):
        return fakes.setdefault(a.id, Fake(a.client_id))

    def create():
        return Engine(
            "sqlite:///" + str(tmp_path / "copier.db"),
            lambda s: vault.encrypt(s.encode()).decode(),
            lambda s: vault.decrypt(s.encode()).decode(),
            lambda *_: (state["rows"], ["MASTER"]),
            lambda *_: state["current"],
            lambda *_: {"lot": 1, "price": 100},
            transport=factory,
        )

    e = create()
    yield e, fakes, state, create
    e.close()


def add(e, client="CHILD", mode="paper", **kwargs):
    return e.account(
        "owner",
        mode,
        dict(name=client, client_id=client, broker="fyers", symbols=["NSE:SBIN"], **kwargs),
    )


def arm(e, mode="paper"):
    e.control("owner", mode, "fyers", "arm")


def ingest(e, raw=None, **kwargs):
    return e.ingest("owner", "paper", "fyers", raw or event(), **kwargs)


def settled(e, mode="paper"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = e.snapshot("owner", mode, "fyers")["attempts"]
        if all(r["status"] not in ("QUEUED", "SUBMITTING") for r in rows):
            return rows
        time.sleep(0.005)
    pytest.fail("Copier work did not settle")


def test_partial_fill_duplicate_concurrent_and_regressive(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: ingest(e), range(20)))
    settled(e)
    ingest(e, event(filled_quantity=10, order_status="complete"))
    settled(e)
    ingest(e, event(filled_quantity=7))
    settled(e)
    assert [c[1]["quantity"] for c in fs[child].calls] == [4, 6]
    assert len(e.snapshot("other", "paper", "fyers")["attempts"]) == 0


def test_lot_rounding_uses_cumulative_quantity(rig):
    e, fs, _, _ = rig
    e.instrument = lambda *_: {"lot": 5, "price": 100}
    child = add(e, multiplier=0.5)
    arm(e)
    ingest(e, event(quantity=20, filled_quantity=8))
    settled(e)
    ingest(e, event(quantity=20, filled_quantity=12))
    settled(e)
    assert [c[1]["quantity"] for c in fs[child].calls] == [5]


@pytest.mark.parametrize("copy_mode", ["fast", "hybrid"])
def test_fast_and_hybrid_only_once_on_subsequent_fills(rig, copy_mode):
    e, fs, _, _ = rig
    child = add(e, copy_mode=copy_mode, fast_symbols=["NSE:SBIN"])
    arm(e)
    ingest(e, event(filled_quantity=0))
    settled(e)
    ingest(e, event(filled_quantity=4))
    settled(e)
    ingest(e, event(filled_quantity=10, order_status="complete"))
    settled(e)
    assert [c[1]["quantity"] for c in fs[child].calls] == [10]


def test_hybrid_limit_waits_for_fill(rig):
    e, fs, _, _ = rig
    child = add(e, copy_mode="hybrid", fast_symbols=["NSE:SBIN"])
    arm(e)
    ingest(e, event(pricetype="LIMIT", price=100, filled_quantity=0))
    settled(e)
    assert not fs[child].calls
    ingest(e, event(pricetype="LIMIT", price=100, filled_quantity=4))
    settled(e)
    assert fs[child].calls[0][1]["pricetype"] == "MARKET"


def test_parallel_fanout_not_serial_network(rig):
    e, fs, _, _ = rig
    children = [add(e, str(i)) for i in range(8)]
    arm(e)
    for child in children:
        fs[child].delay = 0.15
    start = time.monotonic()
    ingest(e)
    settled(e)
    assert time.monotonic() - start < 1.0  # Serial network alone is 1.2 seconds.
    assert all(len(fs[c].calls) == 1 for c in children)


def test_baseline_and_restart_do_not_replay(rig):
    e, fs, state, create = rig
    child = add(e)
    state["rows"] = [event()]
    arm(e)
    ingest(e, event(filled_quantity=10, order_status="complete"))
    settled(e)
    assert not fs[child].calls
    state["rows"] = []
    ingest(e, event(orderid="NEW"))
    settled(e)
    assert len(fs[child].calls) == 1
    e.close()
    restored = create()
    try:
        assert not restored.snapshot("owner", "paper", "fyers")["armed"]
        arm(restored)
        ingest(restored, event(orderid="NEW"))
        settled(restored)
        assert len(fs[child].calls) == 1
    finally:
        restored.close()


def test_timeout_never_retried_and_late_ack_reconciles(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    fs[child].failure = TimeoutError("access_token=SHOULD_NOT_LEAK")
    ingest(e)
    rows = settled(e)
    assert rows[0]["status"] == "UNKNOWN"
    assert "SHOULD_NOT_LEAK" not in json.dumps(e.snapshot("owner", "paper", "fyers"))
    ingest(e)
    settled(e)
    assert len(fs[child].calls) == 1
    with pytest.raises(CopierError, match="UNKNOWN"):
        arm(e)
    tag = fs[child].calls[0][2]
    fs[child].rows = [
        {"orderid": "FOUND", "tag": tag, "status": "complete", "filled": 4, "average_price": 100}
    ]
    e.reconcile("owner", "paper", "fyers")
    assert e.snapshot("owner", "paper", "fyers")["attempts"][0]["status"] == "COMPLETE"
    assert len(fs[child].calls) == 1


@pytest.mark.parametrize(
    "policy,expected",
    [
        ({"max_quantity": 2}, "quantity"),
        ({"max_order_value": 100}, "order value"),
        ({"max_daily_value": 100}, "daily value"),
        ({"max_position_quantity": 2}, "position"),
    ],
)
def test_risk_limits_block_dispatch(rig, policy, expected):
    e, fs, _, _ = rig
    child = add(e, **policy)
    arm(e)
    ingest(e)
    rows = settled(e)
    assert rows[0]["status"] == "BLOCKED" and expected in rows[0]["message"]
    assert not fs[child].calls


def test_loss_limit_and_mode_flip(rig):
    e, fs, state, _ = rig
    child = add(e)
    arm(e)
    e.risk_cache[child] = (time.time(), {"pnl": -10000, "quantity": 0})
    ingest(e)
    assert settled(e)[0]["status"] == "BLOCKED"
    state["current"] = False
    ingest(e, event(orderid="NEW"))
    assert not e.snapshot("owner", "paper", "fyers")["armed"]
    assert not fs[child].calls


def test_stop_blocks_queued_orders_and_child_config_while_armed(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    with pytest.raises(CopierError, match="Disarm"):
        add(e, "ANOTHER")
    e.control("owner", "paper", "fyers", "kill")
    ingest(e)
    assert not fs[child].calls
    assert e.snapshot("owner", "paper", "fyers")["killed"]


def test_cancel_and_authoritative_modify(rig):
    e, fs, _, _ = rig
    child = add(e, copy_mode="fast")
    arm(e)
    base = event(pricetype="LIMIT", price=100, filled_quantity=0)
    ingest(e, base)
    settled(e)
    changed = {**base, "price": 101}
    ingest(e, changed)
    settled(e)
    ingest(e, changed, authoritative=True)
    settled(e)
    ingest(e, {**changed, "order_status": "cancelled"})
    settled(e)
    assert [c[0] for c in fs[child].calls] == ["PLACE", "MODIFY", "CANCEL"]
    assert fs[child].calls[-1][3] == "CHILD-1"


def test_secrets_encrypted_and_owner_mode_isolation(rig):
    e, _, _, _ = rig
    token = "PRIVATE_CHILD_TOKEN"
    child = add(e, mode="live", credentials={"app_id": "APP", "access_token": token})
    with e.sessions() as s:
        row = s.get(m.Account, child)
        assert token not in row.secret
        assert token in e.decrypt(row.secret)
    assert token not in json.dumps(e.snapshot("owner", "live", "fyers"))
    assert not e.snapshot("owner", "paper", "fyers")["accounts"]
    assert not e.snapshot("other", "live", "fyers")["accounts"]
    with pytest.raises(CopierError, match="not found"):
        e.account(
            "other",
            "live",
            {"name": "x", "broker": "fyers", "client_id": "CHILD", "symbols": ["NSE:SBIN"]},
            child,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", True),
        ("quantity", 1.5),
        ("price", float("nan")),
        ("filled_quantity", 11),
        ("action", "SHORT"),
        ("product", "BO"),
    ],
)
def test_invalid_orders_rejected(field, value):
    with pytest.raises(CopierError):
        order(event(**{field: value}))


@pytest.mark.parametrize("broker", ["fyers", "zerodha", "dhan"])
def test_native_uses_child_credentials_and_contract(monkeypatch, broker):
    from services.trade_copier import adapters

    captured = []

    def http(method, url, headers, payload=None, **kwargs):
        captured.append((method, url, headers, payload))
        return {"id": "F1", "data": {"order_id": "Z1"}, "orderId": "D1"}

    monkeypatch.setattr(adapters, "http", http)
    a = Native(
        broker,
        {
            "app_id": "CHILD_APP",
            "access_token": "CHILD_TOKEN",
            "client_id": "CHILD",
            "instruments": {
                "NSE:SBIN": "3045"
                if broker == "dhan"
                else ("NSE:SBIN-EQ" if broker == "fyers" else "SBIN")
            },
        },
    )
    assert a.execute("PLACE", event(), "cp" + "a" * 18)["status"] == "ACKNOWLEDGED"
    headers = captured[0][2]
    payload = captured[0][3]
    assert "CHILD_TOKEN" in json.dumps(headers)
    assert (payload.get("qty") or payload.get("quantity")) == 10
    assert len(captured) == 1


def test_transport_timeout_and_429_are_not_retried(monkeypatch):
    from services.trade_copier import adapters

    class Client:
        calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            raise TimeoutError("SECRET")

    client = Client()
    monkeypatch.setattr(adapters, "get_httpx_client", lambda: client)
    with pytest.raises(BrokerFailure) as exc:
        adapters.http("POST", "https://fixed.broker/orders", {}, mutation=True)
    assert exc.value.state == "UNKNOWN" and "SECRET" not in str(exc.value) and client.calls == 1


def test_gateway_origin_and_mode_contract(monkeypatch):
    from services.trade_copier import adapters

    with pytest.raises(CopierError):
        Gateway({"url": "http://169.254.169.254", "api_key": "SECRET"}, "live", "angel")
    captured = []
    monkeypatch.setattr(
        adapters,
        "http",
        lambda *args, **kw: (
            captured.append(args[3])
            or {
                "status": "success",
                "data": {"version": 1, "broker": "angel", "mode": "live", "identity": "CHILD"},
            }
        ),
    )
    a = Gateway({"url": "http://127.0.0.1:5020", "api_key": "SECRET"}, "live", "angel")
    assert a.verify() == "CHILD"
    assert captured[0]["mode"] == "live" and captured[0]["broker"] == "angel"


def test_cancel_waits_for_inflight_parent(rig):
    e, fs, _, _ = rig
    child = add(e, copy_mode="fast")
    arm(e)
    fs[child].delay = 0.08
    ingest(e, event(filled_quantity=0))
    assert fs[child].started.wait(1)
    ingest(e, event(filled_quantity=0, order_status="cancelled"))
    settled(e)
    assert [c[0] for c in fs[child].calls] == ["PLACE", "CANCEL"]
    assert fs[child].calls[1][3] == "CHILD-1"


def test_cancelled_order_copies_last_unseen_fill_delta(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    ingest(e, event(filled_quantity=0))
    settled(e)
    ingest(e, event(filled_quantity=3, order_status="cancelled"))
    settled(e)
    assert fs[child].calls[0][1]["quantity"] == 3
    assert fs[child].calls[0][1]["filled_quantity"] == 0


def test_kill_during_preflight_wins(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    started = threading.Event()
    resume = threading.Event()

    def slow():
        started.set()
        assert resume.wait(2)
        return "CHILD"

    fs[child].verify = slow
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(arm, e)
        assert started.wait(1)
        e.control("owner", "paper", "fyers", "kill")
        resume.set()
        with pytest.raises(CopierError, match="changed during preflight"):
            future.result()
    assert not e.snapshot("owner", "paper", "fyers")["armed"]
    assert e.snapshot("owner", "paper", "fyers")["killed"]


def test_rejection_remains_paused_after_periodic_reconcile(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    fs[child].failure = BrokerFailure("REJECTED", "Broker refused")
    ingest(e)
    settled(e)
    e.reconcile("owner", "paper", "fyers")
    assert e.snapshot("owner", "paper", "fyers")["accounts"][0]["health"] == "DEGRADED"
    ingest(e, event(orderid="NEW"))
    settled(e)
    assert len(fs[child].calls) == 1


def test_real_blueprint_csrf_owner_mode_and_bridge_idempotency(rig, monkeypatch):
    from flask import Flask, session
    from flask_wtf import CSRFProtect
    from flask_wtf.csrf import generate_csrf

    from blueprints.trade_copier import trade_copier_bp
    from database import auth_db
    from services.trade_copier import runtime
    from utils import session as auth_session

    e, _, _, _ = rig
    monkeypatch.setattr(runtime, "active_mode", lambda: "paper")
    monkeypatch.setattr(runtime, "context", lambda *_: True)
    monkeypatch.setattr(auth_session, "is_session_valid", lambda: bool(session.get("user")))
    app = Flask(__name__)
    app.secret_key = "copier-test-only"
    app.add_url_rule("/login", "auth.login", lambda: "Sign in")
    csrf = CSRFProtect(app)
    app.config["TRADE_COPIER_ENGINE"] = e
    app.register_blueprint(trade_copier_bp)
    csrf.exempt(app.view_functions["trade_copier.bridge"])

    @app.get("/csrf")
    def token():
        return {"token": generate_csrf()}

    c = app.test_client()
    assert c.get("/trade-copier/api/state?mode=paper&broker=fyers").status_code in (302, 401)
    with c.session_transaction() as s:
        s["user"] = "owner"
        s["broker"] = "fyers"
    payload = {"name": "Child", "client_id": "CHILD", "broker": "fyers", "symbols": ["NSE:SBIN"]}
    assert (
        c.post("/trade-copier/api/accounts?mode=paper&broker=fyers", json=payload).status_code
        == 400
    )
    headers = {"X-CSRFToken": c.get("/csrf").json["token"]}
    assert (
        c.post(
            "/trade-copier/api/accounts?mode=live&broker=fyers", json=payload, headers=headers
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/trade-copier/api/accounts?mode=paper&broker=fyers", json=payload, headers=headers
        ).status_code
        == 200
    )
    with c.session_transaction() as s:
        s["user"] = "other"
    assert c.get("/trade-copier/api/state?mode=paper&broker=fyers").json["data"]["accounts"] == []
    monkeypatch.setenv("TRADE_COPIER_BRIDGE_ENABLED", "TRUE")
    monkeypatch.setattr(
        auth_db, "verify_api_key", lambda key: "child-owner" if key == "CHILD-KEY" else None
    )
    monkeypatch.setattr(auth_db, "get_order_mode", lambda _: "auto")
    fake = Fake("identity")
    monkeypatch.setattr(runtime, "LocalBridge", lambda *args: fake)
    req = {
        "apikey": "CHILD-KEY",
        "mode": "paper",
        "broker": "fyers",
        "operation": "execute",
        "key": "cp" + "b" * 18,
        "action": "PLACE",
        "order": event(),
    }
    assert c.post("/trade-copier/bridge", json={**req, "apikey": "WRONG"}).status_code == 403
    first = c.post("/trade-copier/bridge", json=req)
    assert first.status_code == 200 and first.json["data"]["status"] == "ACKNOWLEDGED"
    assert c.post("/trade-copier/bridge", json=req).json == first.json
    assert len(fake.calls) == 1
    altered = {**req, "order": event(quantity=20)}
    assert c.post("/trade-copier/bridge", json=altered).status_code == 400
    assert len(fake.calls) == 1


def test_repeated_price_revisions_are_not_suppressed(rig):
    e, fs, _, _ = rig
    child = add(e, copy_mode="fast")
    arm(e)
    base = event(filled_quantity=0, pricetype="LIMIT", price=100)
    ingest(e, base)
    settled(e)
    for price in (101, 100, 101):
        ingest(e, {**base, "price": price}, authoritative=True)
        settled(e)
    assert [c[1]["price"] for c in fs[child].calls] == [100, 101, 100, 101]


def test_event_bus_ingress_uses_owner_and_mode(rig):
    from events import OrderUpdateEvent

    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    e.on_event(
        OrderUpdateEvent(**event(), mode="live", broker="fyers", request_data={"user_id": "owner"})
    )
    e.on_event(
        OrderUpdateEvent(
            **event(), mode="analyze", broker="sandbox", request_data={"user_id": "somebody-else"}
        )
    )
    assert not fs[child].calls
    e.on_event(
        OrderUpdateEvent(
            **event(), mode="analyze", broker="sandbox", request_data={"user_id": "owner"}
        )
    )
    settled(e)
    assert len(fs[child].calls) == 1


def test_master_cannot_be_a_child_and_duplicate_remote_identity(rig):
    e, fs, _, _ = rig
    add(e, "MASTER", mode="live", credentials={"app_id": "APP", "access_token": "TEST"})
    with pytest.raises(CopierError, match="preflight failed"):
        arm(e, "live")
    with e.sessions() as s:
        assert s.scalar(select(m.Account)).health == "DISABLED"


def test_real_paper_orderbook_partitions_children(monkeypatch):
    import uuid
    from datetime import datetime
    from decimal import Decimal

    from database import sandbox_db as db
    from services.trade_copier.adapters import Paper

    assert "log/test/" in str(db.engine.url)
    db.Base.metadata.create_all(db.engine)
    users = ["copier-test-" + uuid.uuid4().hex[:12] for _ in range(2)]
    try:
        for i, user in enumerate(users):
            db.db_session.add(
                db.SandboxOrders(
                    orderid="cp-test-" + uuid.uuid4().hex,
                    user_id=user,
                    symbol="SBIN",
                    exchange="NSE",
                    action="BUY",
                    quantity=i + 1,
                    price=100,
                    price_type="LIMIT",
                    product="CNC",
                    order_status="open",
                    filled_quantity=0,
                    pending_quantity=i + 1,
                    order_timestamp=datetime.now(),
                    strategy="cp-tag",
                )
            )
            db.db_session.add(
                db.SandboxPositions(
                    user_id=user,
                    symbol="SBIN",
                    exchange="NSE",
                    product="CNC",
                    quantity=i + 1,
                    average_price=Decimal("100"),
                    ltp=Decimal("101"),
                    pnl=Decimal(str(i + 1)),
                    today_realized_pnl=Decimal("2"),
                )
            )
        db.db_session.commit()
        assert [r["quantity"] for r in Paper(users[0]).orders()] == [1]
        assert [r["quantity"] for r in Paper(users[1]).orders()] == [2]
        assert Paper(users[1]).risk() == {"pnl": 4.0, "quantity": 2}
        oid = Paper(users[0]).orders()[0]["orderid"]
        result = Paper(users[1]).execute("CANCEL", event(), "", oid)
        assert result["status"] == "REJECTED"
    finally:
        for user in users:
            db.SandboxOrders.query.filter_by(user_id=user).delete()
            db.SandboxPositions.query.filter_by(user_id=user).delete()
        db.db_session.commit()
        db.db_session.remove()


def test_estimated_fees_use_child_broker_for_confirmed_fill(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    ingest(e)
    settled(e)
    fs[child].rows[0].update(status="complete", filled=4, average_price=100)
    e.reconcile("owner", "paper", "fyers")
    charges = e.snapshot("owner", "paper", "fyers")["attempts"][0]["estimated_charges"]
    assert charges["brokerage"] > 0 and charges["gst"] > 0
    with e.db.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 2


def test_multiplier_decimal_does_not_drop_a_share(rig):
    e, fs, _, _ = rig
    child = add(e, multiplier=0.58)
    arm(e)
    ingest(e, event(quantity=100, filled_quantity=100, order_status="complete"))
    settled(e)
    assert fs[child].calls[0][1]["quantity"] == 58


def test_bridge_lost_ack_returns_receipt_without_second_broker_call(rig, monkeypatch):
    # Exercise the actual endpoint with an ambiguous broker submission.
    from flask import Flask

    from blueprints.trade_copier import trade_copier_bp
    from database import auth_db
    from services.trade_copier import runtime

    e, _, _, _ = rig
    monkeypatch.setenv("TRADE_COPIER_BRIDGE_ENABLED", "TRUE")
    monkeypatch.setattr(runtime, "context", lambda *_: True)
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _: "child")
    monkeypatch.setattr(auth_db, "get_order_mode", lambda _: "auto")
    fake = Fake("child")
    fake.failure = TimeoutError("PRIVATE")
    monkeypatch.setattr(runtime, "LocalBridge", lambda *_: fake)
    app = Flask(__name__)
    app.config["TRADE_COPIER_ENGINE"] = e
    app.register_blueprint(trade_copier_bp)
    c = app.test_client()
    req = {
        "apikey": "fake",
        "mode": "paper",
        "broker": "fyers",
        "operation": "execute",
        "action": "PLACE",
        "key": "cp" + "c" * 18,
        "order": event(),
    }
    assert c.post("/trade-copier/bridge", json=req).json["data"]["status"] == "UNKNOWN"
    assert c.post("/trade-copier/bridge", json=req).json["data"]["status"] == "UNKNOWN"
    assert len(fake.calls) == 1


def test_same_order_id_from_different_master_brokers_is_separate(rig):
    e, fs, _, _ = rig
    child = add(e, copy_mode="fast")
    arm(e)
    ingest(e, event(filled_quantity=0))
    settled(e)
    e.control("owner", "paper", "fyers", "disarm")
    e.control("owner", "paper", "zerodha", "arm")
    e.ingest("owner", "paper", "zerodha", event(filled_quantity=0))
    settled(e)
    assert [c[0] for c in fs[child].calls] == ["PLACE", "PLACE"]
    with e.sessions() as s:
        assert len({a.master_key for a in s.scalars(select(m.Attempt))}) == 2


def test_old_queued_intent_cannot_execute_after_rearming(rig):
    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    fs[child].delay = 0.25
    ingest(e)
    assert fs[child].started.wait(1)
    ingest(e, event(orderid="QUEUED-OLD"))
    e.control("owner", "paper", "fyers", "disarm")
    arm(e)
    rows = settled(e)
    assert len(fs[child].calls) == 1
    assert next(r for r in rows if r["master_orderid"] == "QUEUED-OLD")["status"] == "BLOCKED"


def test_unknown_order_can_be_matched_only_in_its_child_orderbook(rig, monkeypatch):
    from flask import Flask

    from blueprints.trade_copier import trade_copier_bp
    from services.trade_copier import runtime
    from utils import session as auth_session

    e, fs, _, _ = rig
    child = add(e)
    arm(e)
    fs[child].failure = TimeoutError()
    ingest(e)
    attempt = settled(e)[0]
    fs[child].rows = [
        {"orderid": "LATE-ACK", "tag": "", "status": "complete", "filled": 4, "average_price": 100}
    ]
    monkeypatch.setattr(runtime, "active_mode", lambda: "paper")
    monkeypatch.setattr(auth_session, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.secret_key = "offline-only"
    app.config["TRADE_COPIER_ENGINE"] = e
    app.register_blueprint(trade_copier_bp)
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = "owner"
        s["broker"] = "fyers"
    path = f"/trade-copier/api/resolve/{attempt['id']}?mode=paper&broker=fyers"
    data = {"confirm": True, "resolution": "confirmed_executed", "broker_orderid": "WRONG"}
    assert c.post(path, json=data).status_code == 400
    assert c.post(path, json={**data, "broker_orderid": "LATE-ACK"}).status_code == 200
    row = e.snapshot("owner", "paper", "fyers")["attempts"][0]
    assert (
        row["status"] == "COMPLETE" and row["filled"] == 4 and row["broker_orderid"] == "LATE-ACK"
    )
    assert len(fs[child].calls) == 1
