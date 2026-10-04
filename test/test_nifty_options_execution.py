"""Crash recovery, order ordering and actual backtest-accounting regressions."""

import copy
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from strategies.nifty_options.engine import initial_state, opening_plan
from strategies.nifty_options.execution import SandboxExecutor
from strategies.nifty_options.profiles import PROFILES
from strategies.nifty_options.replay import risk_crossing, segment, verify_vectorbt
from strategies.nifty_options.state import Store
from test.test_nifty_options_strategies import EXPIRY, NOW, POLICY, chain, opened


def executor_fixture(monkeypatch, tmp_path):
    import database.sandbox_db
    import database.token_db
    import sandbox.execution_engine
    import strategies.nifty_options.execution as module

    rows, dispatches = [], []

    class Session:
        def query(self, *_):
            return self

        def filter_by(self, **filters):
            self.filters = filters
            return self

        def all(self):
            return [
                row for row in rows if all(getattr(row, k) == v for k, v in self.filters.items())
            ]

        def remove(self):
            pass

    class Manager:
        crash_after_commit = False

        def place_order(self, order, prefetched_quote):
            dispatches.append(copy.deepcopy(order))
            row = SimpleNamespace(
                user_id="u",
                strategy=order["strategy"],
                orderid=str(len(rows) + 1),
                symbol=order["symbol"],
                quantity=order["quantity"],
                order_status="complete",
                filled_quantity=order["quantity"],
                average_price=prefetched_quote["ltp"],
            )
            rows.append(row)
            if self.crash_after_commit:
                self.crash_after_commit = False
                raise RuntimeError("simulated crash after committed order")
            return True, {"orderid": row.orderid, "mode": "analyze"}, 200

    monkeypatch.setattr(database.sandbox_db, "db_session", Session())
    monkeypatch.setattr(
        database.token_db, "get_symbol_info", lambda *_: SimpleNamespace(lotsize=65)
    )
    monkeypatch.setattr(sandbox.execution_engine, "quote_looks_stale", lambda _: False)
    monkeypatch.setattr(module, "cleanup_sessions", lambda: None)
    profile = PROFILES["iron_condor_intraday_current_week"]
    store = Store(tmp_path / "state.db")

    def restore():
        revision, state = store.load("u", profile.name)
        runner = SandboxExecutor.__new__(SandboxExecutor)
        runner.owner, runner.profile, runner.state = (
            "u",
            profile,
            state or initial_state(profile, POLICY),
        )
        runner.lock = tmp_path / "dispatch.lock"
        runner.manager = Manager()

        def persist(kind, event):
            nonlocal revision
            revision = store.save("u", profile.name, revision, runner.state, [(kind, event)])

        runner.persist = persist
        return runner

    return restore, rows, dispatches, store


def test_crash_after_dispatch_reconciles_without_duplicate(monkeypatch, tmp_path):
    restore, rows, dispatches, store = executor_fixture(monkeypatch, tmp_path)
    runner = restore()
    legs = opening_plan(runner.profile, POLICY, chain(), EXPIRY, 1_000_000)
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": True}, legs, NOW)
    quotes = {o.symbol: {"ltp": o.price} for o in chain()}
    runner.manager.crash_after_commit = True
    with pytest.raises(RuntimeError, match="simulated crash"):
        runner.advance(quotes, NOW)
    assert len(dispatches) == 1
    runner = restore()
    for _ in range(7):
        runner.advance(quotes, NOW)
    assert len(dispatches) == 4
    assert {d["product"] for d in dispatches} == {"NRML"}
    assert [d["action"] for d in dispatches] == ["BUY", "BUY", "SELL", "SELL"]
    assert len(runner.state["legs"]) == 4 and runner.state["pending"] is None
    runner.begin(
        {"action": "close_all", "reason": "capital_stop", "halt": True}, runner.state["legs"], NOW
    )
    for _ in range(7):
        runner.advance(quotes, NOW)
    assert [d["action"] for d in dispatches[4:]] == ["BUY", "BUY", "SELL", "SELL"]
    assert not runner.state["legs"] and runner.state["halted"]
    assert runner.state["total_realized"] == 0


def test_unknown_dispatch_never_blindly_retries(monkeypatch, tmp_path):
    restore, rows, dispatches, store = executor_fixture(monkeypatch, tmp_path)
    runner = restore()
    legs = opening_plan(runner.profile, POLICY, chain(), EXPIRY, 1_000_000)
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": True}, legs, NOW)
    runner.state["pending"]["steps"][0]["status"] = "dispatching"
    runner.persist("before_crash", {})
    runner = restore()
    with pytest.raises(RuntimeError, match="Ambiguous dispatch"):
        runner.advance({o.symbol: {"ltp": o.price} for o in chain()}, NOW)
    assert dispatches == []


def test_stale_unfilled_entry_does_not_open_late(monkeypatch, tmp_path):
    restore, rows, dispatches, store = executor_fixture(monkeypatch, tmp_path)
    runner = restore()
    legs = opening_plan(runner.profile, POLICY, chain(), EXPIRY, 1_000_000)
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": True}, legs, NOW)
    runner = restore()
    runner.advance({o.symbol: {"ltp": o.price} for o in chain()}, NOW + timedelta(minutes=2))
    assert dispatches == []
    assert runner.state["pending"] is None and runner.state["halted"]


def test_stalled_partial_entry_unwinds_filled_hedge(monkeypatch, tmp_path):
    restore, rows, dispatches, store = executor_fixture(monkeypatch, tmp_path)
    runner = restore()
    legs = opening_plan(runner.profile, POLICY, chain(), EXPIRY, 1_000_000)
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": True}, legs, NOW)
    quotes = {o.symbol: {"ltp": o.price} for o in chain()}
    runner.advance(quotes, NOW)
    runner = restore()
    now = NOW + timedelta(minutes=2)
    runner.advance(quotes, now)  # Recover committed hedge, then abort old entry.
    for _ in range(3):
        runner.advance(quotes, now)
    assert [d["action"] for d in dispatches] == ["BUY", "SELL"]
    assert not runner.state["legs"] and runner.state["pending"] is None
    assert runner.state["halted"]


def test_partial_adjustment_capital_stop_prevents_remaining_entry_orders(monkeypatch, tmp_path):
    restore, rows, dispatches, store = executor_fixture(monkeypatch, tmp_path)
    runner = restore()
    runner.state.update(cycle=1, cycle_realized=-19990, expiry=str(EXPIRY))
    legs = opening_plan(runner.profile, POLICY, chain(), EXPIRY, 1_000_000)
    runner.begin({"action": "open", "expiry": str(EXPIRY), "new_cycle": False}, legs, NOW)
    quotes = {o.symbol: {"ltp": o.price} for o in chain()}
    runner.advance(quotes, NOW)
    runner = restore()
    quotes[dispatches[0]["symbol"]]["ltp"] -= 1
    for _ in range(4):
        runner.advance(quotes, NOW + timedelta(seconds=1))
    assert [d["action"] for d in dispatches] == ["BUY", "SELL"]
    assert runner.state["cycle_realized"] < -20000
    assert not runner.state["legs"] and runner.state["halted"]


@pytest.mark.parametrize("gap", [1, 6])
def test_replay_waits_for_actual_prices_and_bounds_missing_bars(monkeypatch, gap):
    from dataclasses import replace

    import strategies.nifty_options.replay as module
    from strategies.nifty_options.selection import DataUnavailable

    profile = PROFILES["premium_intraday_current_week"]
    monkeypatch.setattr(module, "PROFILES", {profile.name: profile})
    start = int(NOW.replace(hour=9, minute=15).timestamp())
    stamps = np.arange(start, start + 385 * 60, 60)
    contracts = [{"symbol": o.symbol, "expiry": str(EXPIRY)} for o in chain()]
    arrays = {o.symbol: np.full((385, 4), 50.0) for o in chain()}
    arrays["P"][30 : 30 + gap, :] = np.nan
    archive = SimpleNamespace(
        spot={int(t): 24000 for t in stamps[:375]},
        expiries=[EXPIRY],
        day=lambda *_: (stamps, contracts, arrays),
    )
    monkeypatch.setattr(
        module,
        "chain_options",
        lambda _c, prices, _s, now, _l: [
            replace(o, timestamp=now, price=prices[o.symbol]) for o in chain() if o.symbol in prices
        ],
    )
    if gap > 5:
        with pytest.raises(DataUnavailable, match="Held price gap exceeds"):
            module.replay(archive, NOW.date(), NOW.date(), "OLHC")
    else:
        states, trades, curves, skipped = module.replay(archive, NOW.date(), NOW.date(), "OLHC")
        assert len(curves[profile.name]) == 384
        assert len(trades[profile.name]) == 2
        assert len([s for s in skipped[profile.name] if s.get("type") == "missing_held_bar"]) == 1
        assert not states[profile.name]["legs"]


def test_premium_stop_interpolates_instead_of_exiting_at_bar_high():
    profile, state, _ = opened("premium_intraday_current_week")
    trades = []
    segment(
        profile,
        state,
        {"C": 50, "P": 50},
        {"C": 80, "P": 30},
        NOW,
        NOW + timedelta(seconds=20),
        trades,
    )
    assert len(trades) == 1
    assert trades[0]["symbol"] == "C"
    assert trades[0]["exit"] == pytest.approx(65.05)
    assert trades[0]["exit_ts"] == (NOW + timedelta(seconds=10)).isoformat()
    assert [leg["symbol"] for leg in state["legs"]] == ["P"]
    verify_vectorbt(trades, profile.capital)


def test_open_gap_fills_at_market_not_unavailable_stop_price():
    profile, state, _ = opened("premium_intraday_current_week")
    trades = []
    segment(
        profile,
        state,
        {"C": 80, "P": 50},
        {"C": 90, "P": 49},
        NOW,
        NOW + timedelta(seconds=20),
        trades,
    )
    assert trades[0]["exit"] == pytest.approx(80.05)


def test_capital_stop_uses_all_four_mtm_legs():
    profile, state, _ = opened("iron_condor_intraday_current_week", quantity=650)
    state["cycle_realized"] = -19000
    a = {"C": 50, "P": 50, "HC": 12, "HP": 12}
    b = {"C": 60, "P": 50, "HC": 15, "HP": 12}
    crossing = risk_crossing(profile, state, a, b)
    assert crossing[0] == pytest.approx(1000 / 4550)
    trades = []
    segment(profile, state, a, b, NOW, NOW + timedelta(seconds=20), trades)
    assert len(trades) == 4 and state["halted"] and not state["needs_reentry"]
    assert state["cycle_realized"] < -20000  # adverse fills and fees are not capped away
