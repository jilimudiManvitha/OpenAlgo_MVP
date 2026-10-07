"""Behavioral tests use real SQLite state and controlled quotes, never broker orders."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from strategies.nifty_options.admin import set_capital
from strategies.nifty_options.engine import (
    IST,
    apply_close,
    apply_open,
    decision,
    initial_state,
    lots_for_margin,
    net_delta,
    opening_plan,
    risk_decision,
)
from strategies.nifty_options.greeks import historical_lot_size, session_close
from strategies.nifty_options.profiles import PROFILES, ROOT, Policy
from strategies.nifty_options.selection import DataUnavailable, Option, select_expiry, select_legs
from strategies.nifty_options.state import StateConflict, Store

NOW = datetime(2026, 9, 23, 9, 30, tzinfo=IST)
EXPIRY = date(2026, 9, 29)
POLICY = Policy.load(ROOT / "strategies/nifty_options/policy.json")


def chain(now=NOW, price=50):
    return [
        Option("C", EXPIRY, 24000, "CE", price, 0.30, 65, now),
        Option("P", EXPIRY, 23800, "PE", price, -0.30, 65, now),
        Option("HC", EXPIRY, 24200, "CE", 12, 0.15, 65, now),
        Option("HP", EXPIRY, 23600, "PE", 12, -0.15, 65, now),
    ]


def opened(name, quantity=65):
    profile = PROFILES[name]
    state = initial_state(profile, POLICY)
    options = chain(
        price=10
        if profile.family == "iron_condor" and profile.positional
        else 27
        if profile.positional
        else 50
    )
    policy = replace(POLICY, lots=1)
    legs = opening_plan(profile, policy, options, EXPIRY, 100000)
    for leg in legs:
        leg["quantity"] = quantity
    apply_open(
        state, profile, legs, {o.symbol: (o.price, 0) for o in options}, NOW, str(EXPIRY), True
    )
    return profile, state, options


def test_twelve_profiles_have_correct_allocation():
    assert len(PROFILES) == 12
    assert sum(p.capital for p in PROFILES.values()) == 24_000_000
    assert {p.loss_limit for p in PROFILES.values()} == {20000}


def test_expiry_uses_listed_holiday_shift_and_next():
    dates = [date(2026, 3, 23), date(2026, 3, 30), date(2026, 4, 7)]
    assert select_expiry(date(2026, 3, 24), dates, "current") == dates[1]
    assert select_expiry(date(2026, 3, 24), dates, "next") == dates[2]
    with pytest.raises(DataUnavailable):
        select_expiry(date(2026, 3, 24), [dates[2]], "current")


def test_put_delta_tie_prefers_highest_strike_and_exact_hedges():
    profile = PROFILES["iron_condor_intraday_current_week"]
    options = chain()
    options += [
        replace(options[1], symbol="P2", strike=23850),
        replace(options[3], symbol="HP2", strike=23650),
    ]
    result = select_legs(profile, POLICY, options, EXPIRY)
    assert [o.symbol for o, side in result] == ["C", "P2", "HC", "HP2"]
    assert sum(o.delta * side for o, side in result) == pytest.approx(0)


@pytest.mark.parametrize(
    "premium,accepted", [(25, False), (25.05, True), (29.95, True), (30, False)]
)
def test_positional_strict_premium_band(premium, accepted):
    options = chain(price=premium)
    profile = PROFILES["premium_positional_current_week"]
    if accepted:
        assert len(select_legs(profile, POLICY, options, EXPIRY)) == 4
    else:
        with pytest.raises(DataUnavailable):
            select_legs(profile, POLICY, options, EXPIRY)


def test_missing_hedge_rejects_basket():
    with pytest.raises(DataUnavailable):
        select_legs(PROFILES["iron_condor_intraday_current_week"], POLICY, chain()[:3], EXPIRY)


def test_stale_chain_rejected():
    options = chain()
    options[0] = replace(options[0], timestamp=NOW - timedelta(minutes=1))
    with pytest.raises(DataUnavailable):
        select_legs(PROFILES["iron_condor_intraday_current_week"], POLICY, options, EXPIRY)


def test_premium_selection_does_not_require_model_greeks():
    options = [replace(o, delta=None) for o in chain()]
    assert len(select_legs(PROFILES["premium_intraday_current_week"], POLICY, options, EXPIRY)) == 4
    with pytest.raises(DataUnavailable):
        select_legs(PROFILES["delta_intraday_current_week"], POLICY, options, EXPIRY)


def test_unknown_held_delta_delays_adjustment_but_not_price_stop():
    p, state, options = opened("delta_intraday_current_week")
    options = [replace(o, delta=None) for o in options]
    with pytest.raises(DataUnavailable, match="Greek unavailable"):
        decision(p, POLICY, state, options, NOW, [EXPIRY])
    assert (
        risk_decision(p, POLICY, state, {"C": 1000, "P": 50, "HC": 12, "HP": 12}, NOW)["reason"]
        == "capital_stop"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_invalid_premium_rejected(value):
    with pytest.raises(DataUnavailable):
        replace(chain()[0], price=value)


def test_explicit_broker_no_data_is_empty_not_a_fabricated_candle(monkeypatch):
    from broker.fyers.api import data
    from strategies.nifty_options.history import regular_history

    monkeypatch.setattr(data, "get_api_response", lambda *_: {"s": "no_data", "candles": []})
    result = regular_history("test-token", "NSE:NIFTY26O0617350CE", "2026-09-23", "2026-10-01")
    assert result["candles"] == [] and result["data_status"] == "no_data"
    monkeypatch.setattr(data, "get_api_response", lambda *_: {"s": "error", "code": 401})
    with pytest.raises(RuntimeError, match="code 401"):
        regular_history("test-token", "NSE:NIFTY26O0617350CE", "2026-09-23", "2026-10-01")


def test_premium_stop_closes_hit_spread_and_keeps_protected_survivor():
    p, state, quotes = opened("premium_intraday_current_week")
    now = NOW + timedelta(minutes=1)
    quotes = [replace(o, timestamp=now, price=65 if o.symbol == "C" else o.price) for o in quotes]
    action = decision(p, POLICY, state, quotes, now, [EXPIRY])
    assert action["action"] == "close_legs" and action["symbols"] == ["C", "HC"]
    apply_close(state, {"C": (65, 0), "HC": (12, 0)}, now, action["reason"])
    assert [leg["symbol"] for leg in state["legs"]] == ["HP", "P"]
    assert decision(p, POLICY, state, quotes, now, [EXPIRY])["reason"] == "hold"


def test_condor_stop_closes_all_then_reenters_same_expiry():
    p, state, quotes = opened("iron_condor_positional_next_week")
    now = NOW + timedelta(minutes=1)
    quotes = [replace(o, timestamp=now, price=40 if o.symbol == "C" else o.price) for o in quotes]
    action = decision(p, POLICY, state, quotes, now, [date(2026, 9, 24), EXPIRY])
    assert action["action"] == "close_all" and action["reenter"] is True
    apply_close(
        state, {o.symbol: (o.price, 0) for o in quotes}, now, action["reason"], reenter=True
    )
    result = decision(p, POLICY, state, quotes, now, [EXPIRY, date(2026, 10, 6)])
    assert result == {"action": "open", "expiry": str(EXPIRY), "new_cycle": False}


def test_net_delta_includes_hedges_and_uses_signed_position_direction():
    p, state, quotes = opened("iron_condor_intraday_current_week")
    now = NOW + timedelta(minutes=1)
    deltas = {"C": 0.90, "P": -0.20, "HC": 0.65, "HP": -0.10}
    quotes = [replace(o, timestamp=now, delta=deltas[o.symbol]) for o in quotes]
    assert net_delta(state["legs"], {o.symbol: o for o in quotes}) == pytest.approx(-0.15)
    assert decision(p, POLICY, state, quotes, now, [EXPIRY])["reason"] == "hold"
    quotes = [replace(o, delta=0.30 if o.symbol == "HC" else o.delta) for o in quotes]
    assert decision(p, POLICY, state, quotes, now, [EXPIRY])["reason"] == "delta_adjustment"


def test_delta_intraday_uses_net_not_individual_half_delta():
    p, state, quotes = opened("delta_intraday_current_week")
    now = NOW + timedelta(minutes=1)
    quotes = [replace(o, timestamp=now, delta=0.51 if o.symbol == "C" else o.delta) for o in quotes]
    assert decision(p, POLICY, state, quotes, now, [EXPIRY])["reason"] == "hold"
    quotes = [replace(o, delta=0.81 if o.symbol == "C" else o.delta) for o in quotes]
    assert decision(p, POLICY, state, quotes, now, [EXPIRY])["reason"] == "delta_adjustment"


@pytest.mark.parametrize("holding", ["intraday", "positional"])
def test_unfilled_adjustment_cannot_strand_next_cycle(holding):
    p, state, quotes = opened(f"delta_{holding}_current_week")
    apply_close(
        state, {o.symbol: (o.price, 0) for o in quotes}, NOW, "delta_adjustment", reenter=True
    )
    now = NOW + timedelta(days=1 if holding == "intraday" else 7)
    expiry = EXPIRY if holding == "intraday" else date(2026, 10, 6)
    quotes = [replace(o, timestamp=now, expiry=expiry) for o in quotes]
    result = decision(p, POLICY, state, quotes, now, [expiry])
    assert result == {"action": "open", "expiry": str(expiry), "new_cycle": True}


def test_cumulative_loss_beats_condor_reentry_and_survives_restart(tmp_path):
    p, state, quotes = opened("iron_condor_positional_current_week", quantity=650)
    state["cycle_realized"] = -19990
    now = NOW + timedelta(days=1)
    quotes = [
        replace(o, timestamp=now, price=o.price + 0.1 if o.symbol == "C" else o.price)
        for o in quotes
    ]
    action = decision(p, POLICY, state, quotes, now, [EXPIRY])
    assert action["reason"] == "capital_stop" and action["halt"]
    apply_close(state, {o.symbol: (o.price, 0) for o in quotes}, now, action["reason"], halt=True)
    store = Store(tmp_path / "state.db")
    store.save("owner", p.name, 0, state)
    _, restored = Store(tmp_path / "state.db").load("owner", p.name)
    assert restored["cycle_realized"] == pytest.approx(-20055)
    assert decision(p, POLICY, restored, quotes, now, [EXPIRY])["reason"] == "loss_latched"


def test_exit_and_price_stop_do_not_depend_on_greeks():
    p, state, _ = opened("premium_intraday_current_week")
    assert (
        risk_decision(p, POLICY, state, {}, NOW.replace(hour=15, minute=20))["reason"]
        == "intraday_squareoff"
    )
    assert risk_decision(p, POLICY, state, {"C": 65}, NOW)["symbols"] == ["C", "HC"]


def test_positional_risk_stays_active_during_extended_session():
    p, state, _ = opened("premium_positional_current_week")
    now = NOW.replace(hour=15, minute=35)
    assert session_close(now.date()).isoformat() == "15:40:00"
    assert session_close(date(2026, 7, 31)).isoformat() == "15:30:00"
    assert risk_decision(p, POLICY, state, {"C": 35.1}, now)["symbols"] == ["C", "HC"]


def test_positional_carries_overnight_and_exits_expiry_at_1520():
    p, state, quotes = opened("delta_positional_next_week")
    assert risk_decision(p, POLICY, state, {}, NOW.replace(hour=15, minute=20)) is None
    assert (
        risk_decision(p, POLICY, state, {}, datetime(2026, 9, 29, 15, 20, tzinfo=IST))["reason"]
        == "expiry_squareoff"
    )


def test_atomic_state_rejects_second_runner_and_preserves_owner_isolation(tmp_path):
    store = Store(tmp_path / "state.db")
    store.save("a", "s", 0, {"positions": [1]})
    with pytest.raises(StateConflict):
        store.save("a", "s", 0, {"positions": []})
    assert store.load("a", "s")[1] == {"positions": [1]}
    assert store.load("b", "s") == (0, None)


def test_margin_sizes_whole_lots_within_allocation():
    profile = PROFILES["premium_intraday_current_week"]
    assert lots_for_margin(profile, POLICY, 150000) == 13
    with pytest.raises(DataUnavailable):
        lots_for_margin(profile, POLICY, 2000001)


def test_capital_update_keeps_pnl_margin_and_is_idempotent(tmp_path):
    path = tmp_path / "sandbox.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""CREATE TABLE sandbox_funds(user_id TEXT PRIMARY KEY,total_capital REAL,
            available_balance REAL,used_margin REAL,realized_pnl REAL,reset_count INTEGER,updated_at TEXT);
            INSERT INTO sandbox_funds VALUES('u',10000000,9900265.28,100000,265.28,2,'before');
            CREATE TABLE sandbox_config(config_key TEXT PRIMARY KEY,config_value TEXT,updated_at TEXT NOT NULL);""")
    result = set_capital(path, "u")
    assert result["after"]["available_balance"] == pytest.approx(49900265.28)
    assert result["after"]["used_margin"] == 100000
    assert result["after"]["realized_pnl"] == 265.28
    assert set_capital(path, "u")["after"] == result["after"]


@pytest.mark.parametrize(
    "expiry,day,size",
    [
        ("2021-10-07", "2021-10-04", 50),
        ("2024-05-02", "2024-04-25", 50),
        ("2024-05-02", "2024-04-26", 25),
        ("2025-01-02", "2024-12-27", 75),
        ("2025-01-30", "2025-01-24", 25),
        ("2026-01-06", "2025-12-31", 65),
    ],
)
def test_historical_lots(expiry, day, size):
    assert historical_lot_size(date.fromisoformat(expiry), date.fromisoformat(day)) == size
