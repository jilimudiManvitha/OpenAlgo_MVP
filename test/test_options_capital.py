"""Read-only FYERS capital display, owner isolation and persisted sizing evidence."""

import copy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from services import options_capital as capital
from strategies.nifty_options.selection import DataUnavailable
from strategies.nifty_options.state import Store
from test.test_market_scanner_routes import client, headers, login  # noqa: F401
from test.test_nifty_options_execution import executor_fixture
from test.test_nifty_options_strategies import EXPIRY, NOW, POLICY, chain, opened

NAME = "iron_condor_intraday_current_week"


@pytest.fixture
def saved(monkeypatch, tmp_path):
    path = tmp_path / "capital.db"
    monkeypatch.setenv("NIFTY_OPTIONS_STATE_DB", str(path))
    store = Store(path)
    _, state, _ = opened(NAME, quantity=650)
    # Real master-style symbols let the common tariff classifier identify options.
    for leg in state["legs"]:
        leg["symbol"] += "29SEP2624000" + leg["kind"]
    store.save("alice", NAME, 0, state)
    other = copy.deepcopy(state)
    other["legs"][0]["symbol"] = "PRIVATE"
    store.save("bob", NAME, 0, other)
    return store, state


def test_overview_readonly_budget_charges_and_owner(saved):
    store, state = saved
    before = store.path.read_bytes()
    view = capital.overview("alice")
    assert view["allocation"] == 24_000_000
    assert view["deployable_budget"] == 21_600_000
    row = next(s for s in view["strategies"] if s["strategy_id"] == NAME)
    assert len(row["legs"]) == 4
    assert "PRIVATE" not in str(view)
    assert row["entry_snapshot"] is None
    assert row["charges"]["total"] > 80
    assert row["charges"]["breakdown"]["brokerage"] == 80  # four filled entry orders
    assert row["charges"]["breakdown"]["stt"] == 97.5  # 2 shorts * 650 * 50 * .0015
    assert row["unprotected_shorts"] == 0
    assert store.path.read_bytes() == before
    assert all(not s["legs"] for s in capital.overview("charlie")["strategies"])


def test_missing_state_db_never_created(monkeypatch, tmp_path):
    path = tmp_path / "missing.db"
    monkeypatch.setenv("NIFTY_OPTIONS_STATE_DB", str(path))
    assert len(capital.overview("alice")["strategies"]) == 12
    assert not path.exists()


def test_combined_nets_contracts_and_preserves_full_quantity(saved, monkeypatch):
    import strategies.nifty_options.runtime as runtime

    store, state = saved
    other = copy.deepcopy(state)
    other["legs"] = [dict(state["legs"][0], side=-state["legs"][0]["side"], quantity=65)]
    store.save("alice", "iron_condor_intraday_next_week", 0, other)
    captured = []
    monkeypatch.setattr(
        runtime,
        "broker_margin",
        lambda owner, selected, profile, **kw: (
            captured.append((owner, [(o.symbol, o.lot_size, side) for o, side in selected]))
            or {"sizing_requirement": 123}
        ),
    )
    fp = capital.overview("alice")["fingerprint"]
    result = capital.current_quote("alice", "combined", fp)
    assert result["sizing_requirement"] == 123
    assert captured[0][0] == "alice"
    quantities = {s: q * side for s, q, side in captured[0][1]}
    assert quantities[state["legs"][0]["symbol"]] == state["legs"][0]["side"] * 585
    assert len(quantities) == 4
    for invalid in (None, [], "not-a-strategy"):
        with pytest.raises(ValueError):
            capital.current_quote("alice", invalid, fp)
    with pytest.raises(DataUnavailable, match="Positions changed"):
        capital.current_quote("alice", NAME, "stale")
    assert len(captured) == 1


def test_pending_and_quote_race_rejected(saved, monkeypatch):
    import strategies.nifty_options.runtime as runtime

    store, state = saved
    fp = capital.overview("alice")["fingerprint"]

    def racing(*a, **kw):
        state["legs"][0]["quantity"] = 585
        store.save("alice", NAME, 1, state)
        return {}

    monkeypatch.setattr(runtime, "broker_margin", racing)
    with pytest.raises(DataUnavailable, match="during the quote"):
        capital.current_quote("alice", NAME, fp)
    state["pending"] = {"steps": []}
    store.save("alice", NAME, 2, state)
    with pytest.raises(DataUnavailable, match="pending orders"):
        capital.current_quote("alice", NAME, capital.overview("alice")["fingerprint"])


@pytest.mark.parametrize(
    "payload,valid",
    [
        ({"s": "ok", "data": {"margin_total": 150000, "margin_new_order": 120000}}, True),
        ({"s": "ok", "data": {"margin_total": float("nan"), "margin_new_order": 1}}, False),
        ({"s": "ok", "data": {"margin_total": -1, "margin_new_order": 1}}, False),
        ({"s": "ok", "data": {"margin_total": 0, "margin_new_order": 0}}, False),
        ({"s": "ok", "data": {}}, False),
        ([], False),
        ({"s": "error"}, False),
    ],
)
def test_margin_response_complete_basket_and_fail_closed(monkeypatch, payload, valid):
    import broker.fyers.api.rate_limiter as rate
    import broker.fyers.mapping.margin_data as mapper
    import services.market_scanner_provider as provider
    import strategies.nifty_options.runtime as runtime
    import utils.httpx_client as http

    calls, cleanup = [], []
    monkeypatch.setenv("BROKER_API_KEY", "fixture")
    monkeypatch.setattr(provider, "credentials", lambda *_: ("fixture-token", None))
    monkeypatch.setattr(mapper, "transform_margin_positions", lambda legs: legs)
    monkeypatch.setattr(rate, "apply_rate_limit", lambda: None)
    monkeypatch.setattr(runtime, "dispatch_lock", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    monkeypatch.setattr(runtime, "cleanup_sessions", lambda: cleanup.append(True))

    def post(url, **kw):
        calls.append((url, kw))
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setattr(http, "get_httpx_client", lambda: SimpleNamespace(post=post))
    selected = [(o, 1 if i > 1 else -1) for i, o in enumerate(chain())]
    if valid:
        receipt = runtime.broker_margin("alice", selected, None, lots=10, details=True)
        assert receipt["sizing_requirement"] == 150000
        assert receipt["margin_new_order"] == 120000
        assert [leg["quantity"] for leg in receipt["legs"]] == [650] * 4
        assert [leg["action"] for leg in receipt["legs"]] == ["SELL", "SELL", "BUY", "BUY"]
    else:
        with pytest.raises(DataUnavailable):
            runtime.broker_margin("alice", selected, None, details=True)
    assert len(calls) == 1 and calls[0][0].endswith("/multiorder/margin")
    assert calls[0][1]["timeout"] == 30
    assert cleanup == [True]


def test_entry_quote_survives_executor_restart(monkeypatch, tmp_path):
    from strategies.nifty_options.engine import opening_plan

    restore, _, _, store = executor_fixture(monkeypatch, tmp_path)
    runner = restore()
    receipt = {"basket": {"sizing_requirement": 1750000}, "lots_per_leg": 10}
    legs = opening_plan(runner.profile, POLICY, chain(), EXPIRY, 1000000)
    runner.begin(
        {"action": "open", "expiry": str(EXPIRY), "new_cycle": True, "capital_snapshot": receipt},
        legs,
        NOW,
    )
    for _ in range(7):
        runner.advance({o.symbol: {"ltp": o.price} for o in chain()}, NOW)
    assert restore().state["capital_snapshot"] == receipt
    assert len(restore().state["legs"]) == 4


def test_capital_routes_auth_csrf_and_owner(client, monkeypatch):  # noqa: F811
    from limiter import limiter

    monkeypatch.setattr(limiter, "limit", lambda *_: nullcontext())
    seen = []
    monkeypatch.setattr(
        capital, "overview", lambda owner: seen.append(owner) or {"allocation": 24000000}
    )
    base = "/market-scanner/api/options-capital"
    assert client.get(base).status_code == 401
    login(client)
    assert client.get(base).json["data"]["allocation"] == 24000000
    assert seen == ["alice"]
    assert client.post(base + "/quote", json={}).status_code == 400
    monkeypatch.setattr(
        capital, "current_quote", lambda owner, sid, fp: {"owner": owner, "strategy_id": sid}
    )
    response = client.post(
        base + "/quote", json={"strategy_id": NAME, "owner": "bob"}, headers=headers(client)
    )
    assert response.status_code == 200 and response.json["data"]["owner"] == "alice"
    login(client, "zerodha")
    assert client.post(base + "/quote", json={}, headers=headers(client)).status_code == 403


@pytest.mark.parametrize("name", list(capital.PROFILES))
def test_all_variants_size_equal_four_leg_basket_with_reserve(name, monkeypatch):
    import strategies.nifty_options.runtime as runtime

    profile, _, options = opened(name)
    calls = []

    def margin(owner, selected, p, lots=1, **kw):
        calls.append((lots, selected))
        return {
            "sizing_requirement": 170000 * lots,
            "margin_total": 170000 * lots,
            "margin_new_order": 160000 * lots,
            "quoted_at": NOW.isoformat(),
        }

    monkeypatch.setattr(runtime, "broker_margin", margin)
    legs, snapshot = runtime.prepare_opening("alice", profile, POLICY, options, EXPIRY)
    assert [lots for lots, selected in calls] == [1, 10]
    assert all(len(selected) == 4 for lots, selected in calls)
    assert len(legs) == 4 and {leg["quantity"] for leg in legs} == {650}
    assert sorted(leg["side"] for leg in legs) == [-1, -1, 1, 1]
    assert snapshot["allocation"] == 2000000
    assert snapshot["deployable_budget"] == 1800000
    assert snapshot["basket"]["sizing_requirement"] == 1700000
    assert snapshot["utilization_pct"] == 85


def test_full_basket_over_budget_rejected_before_intent(monkeypatch):
    import strategies.nifty_options.runtime as runtime

    profile, _, options = opened(NAME)
    calls = []

    def margin(owner, selected, p, lots=1, **kw):
        calls.append(lots)
        return {"sizing_requirement": 170000 if len(calls) == 1 else 1800001}

    monkeypatch.setattr(runtime, "broker_margin", margin)
    with pytest.raises(DataUnavailable, match="exceeds strategy allocation"):
        runtime.prepare_opening("alice", profile, POLICY, options, EXPIRY)
    assert calls == [1, 10]
