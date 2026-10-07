"""All-family protection and restart recovery, using only isolated state/fake orders."""

import copy
from dataclasses import asdict, replace
from datetime import timedelta

import pytest

from strategies.nifty_options.engine import risk_decision
from strategies.nifty_options.greeks import historical_margin
from strategies.nifty_options.hedges import missing_hedges, protected_quantity
from strategies.nifty_options.profiles import PROFILES
from strategies.nifty_options.runtime import recover_hedges
from strategies.nifty_options.selection import DataUnavailable, select_legs
from test.test_nifty_options_execution import executor_fixture
from test.test_nifty_options_strategies import EXPIRY, NOW, POLICY, chain, opened


def contracts():
    return [{**asdict(o), "expiry": str(o.expiry)} for o in chain()]


@pytest.mark.parametrize("name", PROFILES)
def test_every_variant_requires_both_equal_quantity_same_expiry_wings(name):
    profile, state, _ = opened(name)
    assert len(state["legs"]) == 4
    for short in [leg for leg in state["legs"] if leg["side"] < 0]:
        assert protected_quantity(profile, short, state["legs"]) == short["quantity"]
    assert missing_hedges(profile, state["legs"], contracts()) == []


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("wing", ["HC", "HP"])
def test_missing_either_wing_skips_entry_for_every_variant(name, wing):
    profile, _, options = opened(name)
    with pytest.raises(DataUnavailable, match="hedge is unavailable"):
        select_legs(profile, POLICY, [o for o in options if o.symbol != wing], EXPIRY)


@pytest.mark.parametrize("name", PROFILES)
def test_every_variant_orders_hedges_before_shorts_and_covers_shorts_first(
    monkeypatch, tmp_path, name
):
    restore, _, dispatches, _ = executor_fixture(monkeypatch, tmp_path, name)
    runner = restore()
    profile, state, options = opened(name)
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": True}, state["legs"], NOW)
    quotes = {o.symbol: {"ltp": o.price} for o in options}
    for _ in range(5):
        runner.advance(quotes, NOW)
    assert [(d["symbol"], d["action"]) for d in dispatches] == [
        ("HC", "BUY"),
        ("HP", "BUY"),
        ("C", "SELL"),
        ("P", "SELL"),
    ]
    runner.begin({"action": "close_all", "reason": "expiry_squareoff"}, runner.state["legs"], NOW)
    for _ in range(5):
        runner.advance(quotes, NOW)
    assert [(d["symbol"], d["action"]) for d in dispatches[4:]] == [
        ("C", "BUY"),
        ("P", "BUY"),
        ("HC", "SELL"),
        ("HP", "SELL"),
    ]
    assert not runner.state["legs"] and not runner.state["pending"]


@pytest.mark.parametrize("family", ["delta", "premium"])
def test_carried_hedge_recovery_survives_crash_without_reset_or_duplicate(
    monkeypatch, tmp_path, family
):
    name = family + "_positional_next_week"
    restore, _, dispatches, store = executor_fixture(monkeypatch, tmp_path, name)
    runner = restore()
    _, legacy, options = opened(name)
    legacy["legs"] = [leg for leg in legacy["legs"] if leg["side"] < 0]
    legacy.update(cycle=7, cycle_realized=-500, total_realized=1200, fees=100)
    runner.state.update(legacy)
    before = copy.deepcopy(legacy)
    now = NOW + timedelta(days=1, hours=1)
    wings = missing_hedges(runner.profile, runner.state["legs"], contracts())
    runner.begin({"action": "add_hedges", "expiry": str(EXPIRY)}, wings, now)
    quotes = {o.symbol: {"ltp": o.price} for o in options}
    runner.manager.crash_after_commit = True
    with pytest.raises(RuntimeError, match="simulated crash"):
        runner.advance(quotes, now)
    runner = restore()
    for _ in range(4):
        runner.advance(quotes, now)
    assert [(d["symbol"], d["action"]) for d in dispatches] == [("HC", "BUY"), ("HP", "BUY")]
    assert not runner.state["pending"]
    for key, value in before.items():
        if key != "legs":
            assert runner.state[key] == value, key
    assert [leg for leg in runner.state["legs"] if leg["side"] < 0] == before["legs"]
    assert missing_hedges(runner.profile, runner.state["legs"], contracts()) == []
    assert len(store.load("u", name)[1]["legs"]) == 4


def test_old_unhedged_pending_entry_cannot_dispatch_a_short(monkeypatch, tmp_path):
    name = "delta_intraday_current_week"
    restore, _, dispatches, _ = executor_fixture(monkeypatch, tmp_path, name)
    runner = restore()
    _, old, options = opened(name)
    shorts = [leg for leg in old["legs"] if leg["side"] < 0]
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": True}, shorts, NOW)
    runner = restore()
    runner.advance({o.symbol: {"ltp": o.price} for o in options}, NOW)
    assert not dispatches
    assert runner.state["halted"] and not runner.state["pending"]


def test_premium_single_stop_keeps_other_wing_and_missing_short_quote_blocks_exit(
    monkeypatch, tmp_path
):
    name = "premium_positional_current_week"
    restore, _, dispatches, _ = executor_fixture(monkeypatch, tmp_path, name)
    runner = restore()
    profile, state, options = opened(name)
    runner.state.update(state)
    action = risk_decision(profile, POLICY, state, {"C": 36}, NOW)
    runner.begin(action, [leg for leg in state["legs"] if leg["symbol"] in action["symbols"]], NOW)
    runner.advance({"HC": {"ltp": 12}}, NOW)
    assert not dispatches  # Never sell wing before short cover gets a fresh quote/fill.
    for _ in range(3):
        runner.advance({o.symbol: {"ltp": o.price} for o in options}, NOW)
    assert [(d["symbol"], d["action"]) for d in dispatches] == [("C", "BUY"), ("HC", "SELL")]
    assert {leg["symbol"] for leg in state["legs"]} == {"P", "HP"}
    assert missing_hedges(profile, state["legs"], contracts()) == []


def test_carried_recovery_rejects_wrong_expiry_and_handles_single_survivor():
    profile, state, _ = opened("premium_positional_current_week")
    survivor = [leg for leg in state["legs"] if leg["symbol"] == "P"]
    assert [leg["symbol"] for leg in missing_hedges(profile, survivor, contracts())] == ["HP"]
    with pytest.raises(DataUnavailable, match="absent"):
        missing_hedges(profile, survivor, [{**c, "expiry": "2026-10-06"} for c in contracts()])


def test_all_family_margin_reserve_counts_long_premium_and_wing_width():
    for profile in PROFILES.values():
        options = chain(
            price=10
            if profile.family == "iron_condor" and profile.positional
            else 27
            if profile.positional
            else 50
        )
        selected = select_legs(profile, POLICY, options, EXPIRY)
        assert historical_margin(profile, selected, 24000) == 65 * (200 + 720 + 24)


def test_recovery_waits_for_fresh_wings_and_does_not_require_index_or_greeks(monkeypatch, tmp_path):
    name = "delta_positional_current_week"
    restore, _, dispatches, _ = executor_fixture(monkeypatch, tmp_path, name)
    runner = restore()
    _, legacy, _ = opened(name)
    legacy["legs"] = [leg for leg in legacy["legs"] if leg["side"] < 0]
    runner.state.update(legacy)
    with pytest.raises(DataUnavailable, match="fresh quotes"):
        recover_hedges(runner, contracts(), {"HC": {"ltp": 12}}, NOW)
    assert not runner.state["pending"] and not dispatches
    fresh = {"HC": {"ltp": 12}, "HP": {"ltp": 12}}
    assert recover_hedges(runner, contracts(), fresh, NOW)
    for _ in range(3):
        runner.advance(fresh, NOW)
    assert not recover_hedges(runner, contracts(), fresh, NOW)
    assert len(dispatches) == 2


def test_rejected_recovery_closes_shorts_before_releasing_filled_wing(monkeypatch, tmp_path):
    name = "premium_positional_next_week"
    restore, _, dispatches, _ = executor_fixture(monkeypatch, tmp_path, name)
    runner = restore()
    _, legacy, options = opened(name)
    legacy["legs"] = [leg for leg in legacy["legs"] if leg["side"] < 0]
    runner.state.update(legacy)
    now = NOW + timedelta(days=1)
    quotes = {o.symbol: {"ltp": o.price} for o in options}
    assert recover_hedges(runner, contracts(), quotes, now)
    place = runner.manager.place_order

    def reject_put_wing(order, prefetched_quote):
        if order["symbol"] == "HP" and order["action"] == "BUY":
            return False, {"message": "Insufficient funds"}, 400
        return place(order, prefetched_quote)

    runner.manager.place_order = reject_put_wing
    for _ in range(8):
        runner.advance(quotes, now)
    assert [(d["symbol"], d["action"]) for d in dispatches] == [
        ("HC", "BUY"),
        ("C", "BUY"),
        ("P", "BUY"),
        ("HC", "SELL"),
    ]
    assert runner.state["halted"] and not runner.state["legs"] and not runner.state["pending"]
    assert runner.state["last_entry_day"] == str(NOW.date())


def test_custom_width_is_used_for_selection_and_recovery():
    profile = replace(PROFILES["delta_intraday_current_week"], hedge_width=300)
    options = [
        replace(o, strike=24300 if o.symbol == "HC" else 23500 if o.symbol == "HP" else o.strike)
        for o in chain()
    ]
    assert len(select_legs(profile, POLICY, options, EXPIRY)) == 4
    _, state, _ = opened(profile.name)
    shorts = [leg for leg in state["legs"] if leg["side"] < 0]
    wings = missing_hedges(
        profile, shorts, [{**asdict(o), "expiry": str(o.expiry)} for o in options]
    )
    assert {leg["strike"] for leg in wings} == {24300, 23500}
