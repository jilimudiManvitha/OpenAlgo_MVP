"""Mode isolation and financial dispatch tests: real ledger, fake broker boundary."""

# ruff: noqa: F811
import pytest

from database.investment_execution_db import InvestmentExecution
from services import investment_execution as execution
from services import investment_mode as modes
from services import investment_service as s
from test.test_investment_api import client, post  # noqa: F401
from test.test_investment_ledger import ledger  # noqa: F401


def seed(kind):
    account = s.save_account("alice", {"name": kind, "kind": kind})
    asset = s.save_asset(
        "alice", {"account_id": account["id"], "symbol": "SBIN", "exchange": "NSE"}
    )
    tx = s.save_transaction(
        "alice",
        {
            "asset_id": asset["id"],
            "action": "BUY",
            "quantity": "3",
            "price": "100",
            "trade_date": "2026-10-07",
            "trade_time": "09:30",
        },
    )
    return account, asset, tx


def test_partition_reads_and_direct_id_writes(client, monkeypatch):
    paper, pa, pt = seed("paper")
    live, la, lt = seed("live")
    for mode, account, asset, tx, hidden_asset, hidden_tx in [
        ("paper", paper, pa, pt, la, lt),
        ("live", live, la, lt, pa, pt),
    ]:
        monkeypatch.setattr(modes, "get_analyze_mode", lambda mode=mode: mode == "paper")
        assert [r["id"] for r in client.get("/investments/api/accounts").json["data"]] == [
            account["id"]
        ]
        assert [r["id"] for r in client.get("/investments/api/holdings").json["data"]] == [
            asset["id"]
        ]
        assert [r["id"] for r in client.get("/investments/api/transactions").json["data"]] == [
            tx["id"]
        ]
        assert client.get("/investments/api/dashboard").json["data"]["invested"] == "300.0000"
        assert len(client.get("/investments/api/reports/transactions").json["data"]["rows"]) == 1
        assert client.get(f"/investments/api/holdings/{hidden_asset['id']}").status_code == 404
        assert (
            post(
                client,
                f"assets/{hidden_asset['id']}/price",
                {"price": "123", "as_of": "2025-10-07T10:00:00+05:30"},
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/investments/api/transactions/{hidden_tx['id']}",
                headers={"X-CSRFToken": client.csrf},
            ).status_code
            == 404
        )
    # Outside the request partition both original records remain intact.
    assert len(s.transactions("alice")) == 2


def test_stale_mode_broker_and_account_relabelling(client, monkeypatch):
    paper, _, _ = seed("paper")
    assert client.get("/investments/api/accounts?mode=live").status_code == 409
    assert client.get("/investments/api/accounts?broker=zerodha").status_code == 409
    assert (
        client.patch(
            f"/investments/api/accounts/{paper['id']}",
            json={"kind": "live"},
            headers={"X-CSRFToken": client.csrf},
        ).status_code
        == 409
    )
    monkeypatch.setattr(modes, "get_analyze_mode", lambda: False)
    assert post(client, "paper/sync", {}).status_code == 409
    assert client.get("/investments/api/paper/gtt").status_code == 409


def test_watches_share_categories_but_not_items_and_preserve_hidden_items(client, monkeypatch):
    from services import investment_watchlists as w

    _, paper, _ = seed("paper")
    _, live, _ = seed("live")
    watch = w.save("alice", {"name": "Shared category", "category": "Swing"})
    for asset in (paper, live):
        w.save_item("alice", watch["id"], {"asset_id": asset["id"]})
    shown = client.get("/investments/api/watchlists").json["data"]
    assert [i["asset_id"] for i in shown[0]["items"]] == [paper["id"]]
    response = client.delete(
        f"/investments/api/watchlists/{watch['id']}", headers={"X-CSRFToken": client.csrf}
    )
    assert response.status_code == 409
    assert len(w.lists("alice")[0]["items"]) == 2
    monkeypatch.setattr(modes, "get_analyze_mode", lambda: False)
    assert [
        i["asset_id"] for i in client.get("/investments/api/watchlists").json["data"][0]["items"]
    ] == [live["id"]]


@pytest.fixture
def broker_boundary(client, monkeypatch):
    with client.session_transaction() as session:
        session["broker"] = "zerodha"
    calls = []
    monkeypatch.setattr(execution, "authenticate", lambda *_: "fixture-token")
    monkeypatch.setattr(execution, "tick_check", lambda *_: None)

    def dispatch(*args):
        calls.append(args)
        return True, {"orderid": "fixture-order", "trigger_id": "fixture-trigger"}, 200

    monkeypatch.setattr(execution, "dispatch", dispatch)
    return calls


def body(asset, **extra):
    return dict(
        asset_id=asset["id"],
        kind="order",
        action="BUY",
        quantity="2",
        price="100",
        request_key="stable-test-key",
        confirm=True,
        **extra,
    )


def test_explicit_review_mode_and_broker_required(client, broker_boundary):
    _, asset, _ = seed("paper")
    payload = body(asset)
    assert post(client, "execution/orders", payload).status_code == 409
    assert post(client, "execution/orders?mode=live&broker=zerodha", payload).status_code == 409
    assert post(client, "execution/orders?mode=paper&broker=fyers", payload).status_code == 409
    payload["confirm"] = False
    assert post(client, "execution/orders?mode=paper&broker=zerodha", payload).status_code == 400
    assert broker_boundary == []


@pytest.mark.parametrize(
    "mode,kind", [("paper", "order"), ("live", "order"), ("paper", "gtt"), ("live", "gtt")]
)
def test_pinned_dispatch_idempotency_and_history(client, monkeypatch, broker_boundary, mode, kind):
    monkeypatch.setattr(modes, "get_analyze_mode", lambda mode=mode: mode == "paper")
    _, asset, _ = seed(mode)
    payload = body(asset)
    payload.update(kind=kind, trigger_price="95", reference_price="100")
    path = f"execution/orders?mode={mode}&broker=zerodha"
    first = post(client, path, payload)
    assert first.status_code == 200, first.json
    assert first.json["data"]["status"] == "accepted"
    assert len(broker_boundary) == 1
    assert broker_boundary[0][1:4] == ("zerodha", mode, kind)
    assert post(client, path, payload).json == first.json
    assert len(broker_boundary) == 1
    assert post(client, path, {**payload, "quantity": "4"}).status_code == 409
    assert len(client.get("/investments/api/execution/orders").json["data"]) == 1
    monkeypatch.setattr(modes, "get_analyze_mode", lambda mode=mode: mode != "paper")
    assert client.get("/investments/api/execution/orders").json["data"] == []
    assert len(s.transactions("alice")) == 1  # Acceptance never invents a fill.


def test_unknown_dispatch_never_retried(client, monkeypatch, broker_boundary):
    _, asset, _ = seed("paper")
    calls = []

    def timeout(*args):
        calls.append(args)
        raise TimeoutError()

    monkeypatch.setattr(execution, "dispatch", timeout)
    path = "execution/orders?mode=paper&broker=zerodha"
    assert post(client, path, body(asset)).json["data"]["status"] == "unknown"
    assert post(client, path, body(asset)).json["data"]["status"] == "unknown"
    assert len(calls) == 1


def test_unsupported_live_gtt_and_invalid_orders_do_not_dispatch(
    client, monkeypatch, broker_boundary
):
    monkeypatch.setattr(modes, "get_analyze_mode", lambda: False)
    _, asset, _ = seed("live")
    with client.session_transaction() as session:
        session["broker"] = "groww"
    path = "execution/orders?mode=live&broker=groww"
    payload = body(asset)
    payload.update(kind="gtt", trigger_price="95", reference_price="100")
    assert post(client, path, payload).status_code == 501
    for field, value in [
        ("quantity", "1.5"),
        ("quantity", "NaN"),
        ("price", "0"),
        ("action", "CLOSE"),
    ]:
        assert post(client, path, {**body(asset), field: value}).status_code == 400
    assert broker_boundary == []


def test_brokerage_estimate_both_modes_is_read_only(client, monkeypatch, broker_boundary):
    for mode in ("paper", "live"):
        monkeypatch.setattr(modes, "get_analyze_mode", lambda mode=mode: mode == "paper")
        _, asset, _ = seed(mode)
        response = post(client, "execution/estimate", body(asset))
        assert response.status_code == 200
        assert response.json["data"]["breakdown"]["brokerage"] == 0  # Zerodha delivery
        assert response.json["data"]["total"] > 0
    assert broker_boundary == []


def test_real_dispatch_routes_use_pinned_modes(monkeypatch):
    import sys
    from types import SimpleNamespace

    place_order_service = SimpleNamespace(place_order_with_auth=lambda: None)
    place_gtt_order_service = SimpleNamespace(place_gtt_order=lambda: None)
    monkeypatch.setitem(sys.modules, "services.place_order_service", place_order_service)
    monkeypatch.setitem(sys.modules, "services.place_gtt_order_service", place_gtt_order_service)

    calls = []

    class FakeManager:
        def __init__(self, owner):
            assert owner == "alice"

        def place_order(self, data):
            calls.append(("paper-order", data))
            return True, {"orderid": "paper"}, 200

        def place_gtt(self, data, reference):
            calls.append(("paper-gtt", reference))
            return True, {"trigger_id": "paper-gtt"}, 200

    monkeypatch.setitem(
        sys.modules, "sandbox.order_manager", SimpleNamespace(OrderManager=FakeManager)
    )
    monkeypatch.setitem(sys.modules, "sandbox.gtt_manager", SimpleNamespace(GTTManager=FakeManager))
    monkeypatch.setattr(
        place_order_service,
        "place_order_with_auth",
        lambda *a, **kw: calls.append(("live-order", kw)) or (True, {"orderid": "live"}, 200),
    )
    monkeypatch.setattr(
        place_gtt_order_service,
        "place_gtt_order",
        lambda *a, **kw: calls.append(("live-gtt", kw)) or (True, {"trigger_id": "live-gtt"}, 200),
    )
    for mode in ("paper", "live"):
        for kind in ("order", "gtt"):
            assert execution.dispatch(
                "alice", "fyers", mode, kind, {"reference_price": 100}, "fixture-token"
            )[0]
    assert [c[0] for c in calls] == ["paper-order", "paper-gtt", "live-order", "live-gtt"]
    assert calls[2][1] == {"force_live": True}
    assert calls[3][1] == {"auth_token": "fixture-token", "broker": "fyers"}


def test_execution_preserves_asset_identity(client, broker_boundary):
    account = s.save_account("alice", {"name": "Watch only", "kind": "paper"})
    asset = s.save_asset(
        "alice",
        {"account_id": account["id"], "symbol": "SBIN", "exchange": "NSE", "is_watch_only": True},
    )
    assert (
        post(client, "execution/orders?mode=paper&broker=zerodha", body(asset)).status_code == 200
    )
    assert (
        client.patch(
            f"/investments/api/assets/{asset['id']}",
            json={"symbol": "TCS"},
            headers={"X-CSRFToken": client.csrf},
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/investments/api/assets/{asset['id']}", headers={"X-CSRFToken": client.csrf}
        ).status_code
        == 409
    )
    assert s.assets("alice")[0]["symbol"] == "SBIN"


def test_ledger_estimate_uses_trade_date_and_actual_average_price(client, broker_boundary):
    _, asset, _ = seed("paper")
    data = {**body(asset), "price": "100.1234", "trade_date": "2025-10-07"}
    result = post(client, "execution/estimate", data)
    assert result.status_code == 200 and result.json["data"]["status"] == "estimated"
    assert (
        post(client, "execution/estimate", {**data, "trade_date": {}}).json["data"]["status"]
        == "unavailable"
    )
    assert (
        post(client, "execution/estimate", {**data, "trade_date": "2020-01-01"}).json["data"][
            "status"
        ]
        == "unavailable"
    )
    assert broker_boundary == []


def test_new_paper_fills_get_estimates_once_without_rewriting_prior_fills(ledger, monkeypatch):
    from services import investment_paper_charges as charges

    _, asset, previous = seed("paper")
    with s.transaction(True) as session:
        session.add(s.PaperFill(user_id="alice", order_id="old", transaction_id=previous["id"]))
    inserted = []

    def fake_reconcile(user):
        if inserted:
            return {"imported": 0, "updated": 1, "errors": []}
        tx = s.save_transaction(
            user,
            {
                "asset_id": asset["id"],
                "action": "BUY",
                "quantity": "2",
                "price": "1000",
                "trade_date": "2026-10-07",
                "trade_time": "10:00",
            },
        )
        with s.transaction(True) as session:
            session.add(s.PaperFill(user_id=user, order_id="new", transaction_id=tx["id"]))
        inserted.append(tx["id"])
        return {"imported": 1, "updated": 1, "errors": []}

    monkeypatch.setattr(charges.paper, "reconcile", fake_reconcile)
    first = charges.reconcile("alice", "fyers")
    assert first["imported"] == 1 and not first["errors"]
    transactions = s.transactions("alice")
    new = next(t for t in transactions if t["id"] == inserted[0])
    old = next(t for t in transactions if t["id"] == previous["id"])
    assert new["brokerage"] == "6.0000"
    assert "assumed current broker fyers" in new["notes"]
    assert old["brokerage"] == "0.0000"
    charges.reconcile("alice", "zerodha")
    assert s.transactions("alice") == transactions
