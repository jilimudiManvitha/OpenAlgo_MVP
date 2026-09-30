"""Four-profile rules and shutdown failure paths; no production orders."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from strategies.top_gain_volumes.runtime import (
    TickCandles,
    eligible_symbols,
    enter,
    exit_trade,
    shutdown_runtime,
)
from strategies.top_gain_volumes.schedule import configurations
from test.test_top_gain_volumes import seeded


@pytest.mark.parametrize(
    "failure", [None, "persist", "unregister", "disconnect", "executor", "store"]
)
def test_shutdown_attempts_all_resources_when_any_step_fails(failure):
    calls = []

    def step(name):
        def run(*args, **kwargs):
            calls.append(name)
            if failure == name:
                raise RuntimeError(name)

        return run

    args = (
        SimpleNamespace(unregister_callback=step("unregister"), disconnect=step("disconnect")),
        None,
        SimpleNamespace(shutdown=step("executor")),
        SimpleNamespace(close=step("store")),
        step("persist"),
        step("http"),
    )
    if failure:
        with pytest.raises(RuntimeError):
            shutdown_runtime(*args)
    else:
        shutdown_runtime(*args)
    assert calls == ["persist", "unregister", "disconnect", "executor", "persist", "store", "http"]


def test_shutdown_regression_detects_save_before_cleanup(monkeypatch):
    def broken(client, receive, executor, store, persist, cleanup_http):
        persist()

    monkeypatch.setitem(globals(), "shutdown_runtime", broken)
    with pytest.raises(AssertionError):
        test_shutdown_attempts_all_resources_when_any_step_fails("persist")


def test_nifty_filter_precedes_ranking():
    rows = {
        f"OUT{i}": {
            "symbol": f"OUT{i}",
            "ltp": 100,
            "volume": 100,
            "rvol": 9,
            "change_percent": 100,
            "live_stamp": 100,
        }
        for i in range(60)
    }
    rows["IN"] = {
        "symbol": "IN",
        "ltp": 100,
        "volume": 100,
        "rvol": 2,
        "change_percent": 1,
        "live_stamp": 100,
    }
    assert eligible_symbols(rows, 101, {"IN"}) == {"IN"}


@pytest.mark.parametrize(
    "signal_low,tick,expected_stop",
    [(100, 0.01, 99.97), (100, 0.05, 99.95), (1000, 0.05, 999.70), (20000, 0.10, 19994)],
)
def test_entry_stop_is_three_basis_points_below_signal_low(signal_low, tick, expected_stop):
    candle = SimpleNamespace(signal=(1790653500, signal_low + 1, signal_low))
    # Larger test-only capital permits whole shares for the high-price rounding case.
    trade = enter("ABC", 1790653561, signal_low + 2, candle, tick, capital=100000)
    assert trade is not None
    assert trade["stop"] == pytest.approx(expected_stop)
    raw_stop = signal_low * 0.9997
    assert trade["stop"] <= raw_stop + 1e-9
    assert raw_stop - trade["stop"] < tick + 1e-9
    raw_target = trade["entry"] + 3 * (trade["entry"] - expected_stop)
    assert raw_target - 1e-8 <= trade["target"] < raw_target + tick + 1e-8


def test_trailing_arms_at_3r_then_exits_first_price_below_middle():
    candle, start = seeded()
    candle.tick(start + 60, 111, 110)
    candle.tick(start + 61, 113, 120)
    trade = enter("ABC", start + 61, 113, candle, 0.05)
    original_stop = trade["stop"]
    assert not exit_trade(trade, start + 62, trade["target"], 0.05, 900, True, 110)
    assert trade["trail_armed"] and trade["exit_ts"] is None
    assert not exit_trade(trade, start + 63, 120, 0.05, 900, True, 120)
    assert exit_trade(trade, start + 63.1, 119.9, 0.05, 900, True, 120)
    assert trade["reason"] == "BB_MIDDLE" and trade["stop"] == original_stop


def test_trailing_original_stop_still_exits_before_or_after_arming():
    for armed in (False, True):
        trade = {
            "entry": 100,
            "quantity": 100,
            "stop": 99,
            "target": 103,
            "exit_ts": None,
            "trail_armed": armed,
        }
        assert exit_trade(trade, 1790653561, 98, 0.05, 900, True, 100)
        assert trade["reason"] == "STOP"


def test_strict_signal_requires_ha_low_above_vwap():
    candle, start = seeded()
    candle.strict_vwap = True
    candle.tick(start + 60, 111, 110)
    assert candle.chart[-1]["ha_low"] < candle.chart[-1]["vwap"]
    assert candle.signal is None
    ordinary, start = seeded()
    ordinary.tick(start + 60, 111, 110)
    assert ordinary.signal is not None


def test_strict_forming_entry_requires_entire_ha_candle_above_vwap():
    ordinary, start = seeded()
    ordinary.tick(start + 60, 111, 110)
    assert ordinary.tick(start + 61, 113, 120)
    strict, start = seeded()
    strict.tick(start + 60, 111, 110)
    strict.strict_vwap = True  # isolate entry guard from the separately tested signal guard
    assert not strict.tick(start + 61, 113, 120)


def test_four_distinct_schedules_are_10k_nse_weekdays():
    configs = configurations("fixture")
    assert len(configs) == 4
    assert len({r["file_path"] for r in configs.values()}) == 4
    for r in configs.values():
        assert r["schedule_start"] == "09:15" and r["schedule_stop"] == "15:00"
        assert r["schedule_days"] == ["mon", "tue", "wed", "thu", "fri"]
        assert r["exchange"] == "NSE" and r["user_id"] == "fixture"


def test_native_bands_matches_independent_population_statistics():
    from strategies.top_gain_volumes.fast_math import bands

    rng = np.random.default_rng(12)
    for n in range(1, 21):
        values = rng.uniform(1, 100000, n)
        middle, upper = bands(values)
        assert middle == pytest.approx(float(np.mean(values)), rel=1e-12)
        assert upper == pytest.approx(float(np.mean(values) + 2 * np.std(values)), rel=1e-12)


def test_sandbox_rejection_and_uncertain_dispatch_are_not_blindly_retried(monkeypatch, tmp_path):
    from strategies.top_gain_volumes.sandbox_execution import SandboxExecution

    sink = SandboxExecution.__new__(SandboxExecution)
    sink.lock_path = tmp_path / "dispatch.lock"
    sink.strategy = "Four10K_fixture"
    sink.persist = Mock()
    sink.manager = Mock()
    trade = {"symbol": "ABC", "quantity": 10}
    sink.manager.place_order.return_value = (False, {"mode": "analyze"}, 400)
    assert sink.place(trade, "BUY", {"ltp": 100}) is False
    assert trade["entry_order_state"] == "rejected"
    sink.manager.place_order.return_value = (False, {"mode": "analyze"}, 500)
    with pytest.raises(RuntimeError, match="Uncertain"):
        sink.place(trade, "BUY", {"ltp": 100})
    assert trade["entry_order_state"] == "uncertain"
    assert sink.manager.place_order.call_count == 2


def test_dispatch_lock_contention_and_exception_release(tmp_path):
    from strategies.top_gain_volumes.coordination import dispatch_lock

    path = tmp_path / "dispatch.lock"
    with pytest.raises(ValueError):
        with dispatch_lock(path):
            with pytest.raises(TimeoutError):
                with dispatch_lock(path, timeout=0.01):
                    pytest.fail("two owners acquired the same lock")
            raise ValueError("simulated order failure")
    with dispatch_lock(path, timeout=0.01):
        pass


def test_history_ranges_discard_broker_boundary_overlap_without_choosing_conflicts():
    from datetime import datetime

    from strategies.top_gain_volumes.history import fetch_intraday_history
    from strategies.top_gain_volumes.runtime import IST

    boundary = int(datetime(2026, 9, 29, tzinfo=IST).timestamp())
    previous = [boundary - 60, 100, 101, 99, 100, 50]
    today = [boundary + 555 * 60, 102, 103, 101, 102, 100]
    wrong_boundary = [today[0], 999, 999, 999, 999, 0]
    provider = Mock()
    provider._request.side_effect = [
        {"candles": [previous, wrong_boundary]},
        {"candles": [previous, today]},
    ]
    assert fetch_intraday_history(provider, "NSE:ABC-EQ", "2026-09-29") == [previous, today]
    assert provider._request.call_count == 2


def test_actual_sandbox_round_trip_records_confirmed_fills_without_live_router(
    monkeypatch, tmp_path
):
    """Real OrderManager/ExecutionEngine, isolated test DB, synthetic current quotes."""
    import uuid
    from datetime import datetime

    from database import sandbox_db, symbol
    from sandbox import execution_engine, order_manager
    from strategies.top_gain_volumes.sandbox_execution import SandboxExecution

    assert "test" in str(sandbox_db.engine.url) and "test" in str(symbol.engine.url)
    sandbox_db.init_db()
    symbol.Base.metadata.create_all(symbol.engine)
    if symbol.SymToken.query.filter_by(symbol="FOURTEST", exchange="NSE").first() is None:
        symbol.db_session.add(
            symbol.SymToken(
                symbol="FOURTEST",
                brsymbol="FOURTEST-EQ",
                name="Fixture",
                exchange="NSE",
                brexchange="NSE",
                token="99999991",
                lotsize=1,
                instrumenttype="EQ",
                tick_size=0.05,
            )
        )
        symbol.db_session.commit()
    symbol.db_session.remove()

    class MarketClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 29, 10, 0, tzinfo=tz)

    monkeypatch.setattr(order_manager, "datetime", MarketClock)
    # A frozen clock otherwise reuses the finite timestamp-derived ID space
    # across repeated fixture runs. Keep order creation/filling real.
    monkeypatch.setattr(
        order_manager.OrderManager, "_generate_order_id", lambda self: "fixture-" + uuid.uuid4().hex
    )
    monkeypatch.setattr(
        order_manager.OrderManager, "_publish_order_update_event", lambda *a, **k: None
    )
    monkeypatch.setattr(
        execution_engine.ExecutionEngine, "_publish_fill_event", lambda *a, **k: None
    )
    monkeypatch.setattr(
        execution_engine.ExecutionEngine, "_publish_order_update_event", lambda *a, **k: None
    )
    # A prefetched tick must make REST quote lookup unnecessary.
    import services.quotes_service as quotes

    monkeypatch.setattr(
        quotes, "get_quotes", lambda *a, **k: pytest.fail("unexpected REST quote lookup")
    )
    owner = "four_fixture_" + uuid.uuid4().hex[:10]
    sink = SandboxExecution(owner, "weekday_fixed", Mock())
    sink.lock_path = tmp_path / "dispatch.lock"
    trade = {
        "symbol": "FOURTEST",
        "quantity": 99,
        "entry": 100,
        "stop": 95,
        "target": 115,
        "exit_ts": None,
    }
    try:
        assert sink.enter(trade, {"ltp": 100, "bid": 99, "ask": 101}, 0.05)
        assert trade["entry"] == 101 and trade["quantity"] == 99
        assert trade["entry"] * trade["quantity"] <= 10000
        assert trade["entry_order_state"] == "complete"
        assert trade["target"] == 119
        assert sink.exit(trade, 1790657160, {"ltp": 105, "bid": 104, "ask": 106}, "SQUARE_OFF")
        assert trade["exit"] == 104 and trade["net_pnl"] == 297
        assert trade["exit_order_state"] == "complete"
        positions = sandbox_db.SandboxPositions.query.filter_by(user_id=owner).all()
        assert len(positions) == 1 and positions[0].quantity == 0
        orders = sandbox_db.SandboxOrders.query.filter_by(user_id=owner).all()
        assert len(orders) == 2 and all(o.strategy == "Four10K_weekday_fixed" for o in orders)
    finally:
        sandbox_db.db_session.remove()
        symbol.db_session.remove()


def test_repeated_native_workers_and_locks_release_descriptors(monkeypatch, tmp_path):
    from datetime import date

    import psutil

    from services.scanner_baseline_download import BINARY, download
    from strategies.top_gain_volumes.coordination import dispatch_lock

    if not BINARY.exists():
        pytest.skip("optional native binary not built")
    monkeypatch.setenv("BROKER_API_KEY", "fixture")
    process = psutil.Process()
    baseline = process.num_fds()
    for _ in range(120):
        assert list(download("fixture", [], date(2026, 9, 30), lambda: None)) == []
        with dispatch_lock(tmp_path / "dispatch.lock"):
            pass
    assert process.num_fds() <= baseline + 2
