"""Staged shorts: causal signals, SELL/BUY lifecycle and add-only schedules.

conftest.py redirects all database/log/scheduler writes to isolated test paths.
No staged main() or real account is run.
"""

import inspect
import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

STAGED = Path(__file__).resolve().parents[1] / ".development/equity-shorts"
from strategies.short_equity import runtime
from strategies.short_equity.profiles import PROFILES
from strategies.short_equity.runtime import (
    TickCandles,
    eligible_symbols,
    enter,
    exit_trade,
    maintain_positions,
)
from strategies.short_equity.sandbox_execution import SandboxExecution
from strategies.short_equity.schedule import configurations, merge_configurations, prepare


def seeded(minutes=1):
    start = int(datetime(2026, 10, 7, 9, 15, tzinfo=runtime.IST).timestamp())
    raw = [[start - 86400 + i * 60, 100, 100, 100, 100, 10] for i in range(100)]
    raw += [[start + i * 60, 110, 110, 110, 110, 1000] for i in range(minutes)]
    raw += [[start + minutes * 60 + i * 60, 90, 90, 88, 89, 1] for i in range(minutes)]
    candle = TickCandles(raw, start + minutes * 120 - 1, timeframe_minutes=minutes)
    return candle, start + minutes * 120, minutes * 1001


def status(state, price=100, qty=100):
    return (
        True,
        {
            "data": {
                "order_status": state,
                "average_price": price,
                "filled_quantity": qty if state == "complete" else 0,
            }
        },
        200,
    )


def sink_fixture(tmp_path):
    sink = SandboxExecution.__new__(SandboxExecution)
    sink.lock_path = tmp_path / "dispatch.lock"
    sink.strategy = "Short10K_fixture"
    sink.persist = Mock()
    sink.manager = Mock()
    sink.manager.place_order.return_value = True, {"mode": "analyze", "orderid": "one"}, 200
    sink.manager.get_order_status.return_value = status("open")
    return sink


def trade_fixture():
    return {
        "symbol": "ABC",
        "quantity": 100,
        "entry": 100,
        "stop": 101,
        "target": 97,
        "exit_ts": None,
        "entry_ts": 1000,
        "path": "PAPER",
        "side": "SELL",
        "direction": "SHORT",
    }


@pytest.mark.parametrize("profile_id", list(PROFILES))
def test_all_eight_enter_intrabar_below_signal_low_and_lower_band(profile_id, tmp_path):
    candle, start, volume = seeded(PROFILES[profile_id]["timeframe_minutes"])
    assert not candle.tick(start, 89, volume)
    assert candle.signal == (start - candle.interval, 105, 88)
    bar = candle.chart[-1]
    assert max(bar[k] for k in ("ha_open", "ha_high", "ha_low", "ha_close")) < bar["vwap"]
    assert bar["ha_low"] < bar["bb_lower"]
    assert bar["bb_lower"] == pytest.approx(2 * bar["bb_middle"] - bar["bb_upper"])
    assert not candle.tick(start + 1, 88, volume + 10)  # Touch is not a break.
    assert candle.tick(start + 2, 87, volume + 20)
    trade = enter("ABC", start + 2, 87, candle, 0.05)
    assert trade["entry_ts"] < start + candle.interval
    assert trade["side"] == "SELL" and trade["direction"] == "SHORT"
    assert trade["entry"] <= 87  # Adverse simulated sell slippage.
    assert trade["stop"] == pytest.approx(105.05)
    assert trade["target"] <= trade["entry"] - 3 * (trade["stop"] - trade["entry"]) + 1e-9
    assert trade["entry"] * trade["quantity"] <= 10000
    sink = sink_fixture(tmp_path)
    assert sink.enter(trade, {"ltp": 87, "high": 110, "low": 87}, 0.05)
    order = sink.manager.place_order.call_args.args[0]
    assert order["action"] == "SELL" and order["product"] == "MIS"
    assert order["exchange"] == "NSE" and order["price_type"] == "MARKET"
    assert trade["entry_order_state"] == "pending"


def test_signal_requires_ha_high_below_vwap():
    candle, start, volume = seeded()
    candle.pv = 104 * candle.volume
    assert not candle.tick(start, 89, volume)
    assert candle.signal is None  # Low is below VWAP but high is above it.


def test_forming_entry_requires_ha_high_below_vwap():
    candle, start, volume = seeded()
    candle.tick(start, 89, volume)
    assert candle.signal
    candle.pv = 96 * candle.volume
    assert not candle.tick(start + 1, 87, volume + 10)


def test_vwap_regressions_fail_when_the_exact_guards_are_disabled(monkeypatch):
    for method, guard, regression in (
        ("_finish", "and hh < vw", test_signal_requires_ha_high_below_vwap),
        ("tick", "and max(high, ho, hc) < vw", test_forming_entry_requires_ha_high_below_vwap),
    ):
        with monkeypatch.context() as context:
            source = textwrap.dedent(inspect.getsource(getattr(TickCandles, method)))
            assert source.count(guard) == 1
            namespace = dict(runtime.__dict__)
            exec(source.replace(guard, "and True"), namespace)
            context.setattr(TickCandles, method, namespace[method])
            with pytest.raises(AssertionError):
                regression()


def test_lower_band_guard_independent_of_signal_break(monkeypatch):
    candle, start, volume = seeded()
    candle.tick(start, 89, volume)
    # Put the forming lower band at 80: 87 breaks the signal low, but not BB.
    monkeypatch.setattr(runtime, "bands", lambda _: (100, 120))
    assert not candle.tick(start + 1, 87, volume + 10)


@pytest.mark.parametrize("fault", ["gap", "volume_rewind", "old_tick", "missing_minute"])
def test_short_candles_reject_incomplete_or_noncausal_ticks(fault):
    candle, start, volume = seeded()
    candle.tick(start, 89, volume)
    if fault == "gap":
        assert not candle.tick(start + 91, 87, volume + 10)
        assert candle.invalid
    elif fault == "volume_rewind":
        assert not candle.tick(start + 1, 87, volume - 1)
        assert candle.invalid
    elif fault == "old_tick":
        original = list(candle.bar)
        assert not candle.tick(start - 2, 87, volume)
        assert candle.bar == original
    else:
        with pytest.raises(ValueError, match="incomplete"):
            TickCandles([], start)


def test_strict_vwap_cannot_be_disabled():
    with pytest.raises(ValueError, match="require every"):
        TickCandles([], 0, strict_vwap=False)


def test_negative_scanner_membership_filters_before_top50():
    rows = {
        f"S{i}": {
            "symbol": f"S{i}",
            "ltp": 100,
            "volume": 100,
            "rvol": 2 + i,
            "change_percent": -i - 1,
            "live_stamp": 100,
        }
        for i in range(60)
    }
    rows["POS"] = {
        "symbol": "POS",
        "ltp": 100,
        "volume": 999,
        "rvol": 999,
        "change_percent": 99,
        "live_stamp": 100,
    }
    rows["STALE"] = {**rows["S59"], "symbol": "STALE", "live_stamp": 80}
    rows["FLAT"] = {**rows["POS"], "symbol": "FLAT", "change_percent": 0}
    assert eligible_symbols(rows, 100) == {f"S{i}" for i in range(10, 60)}
    assert eligible_symbols(rows, 100, {"S0", "S1", "POS", "FLAT"}) == {"S0", "S1"}


@pytest.mark.parametrize(
    "price,hour,reason", [(101, 10, "STOP"), (97, 10, "TARGET"), (99, 15, "SQUARE_OFF")]
)
def test_short_exits_and_pnl(price, hour, reason):
    trade = trade_fixture()
    now = datetime(2026, 10, 7, hour, 15 if hour == 15 else 0, tzinfo=runtime.IST).timestamp()
    assert exit_trade(trade, now, price, 0.05, runtime.SQUARE_OFF_MINUTE)
    assert trade["reason"] == reason
    assert trade["gross_pnl"] == pytest.approx((100 - trade["exit"]) * 100)
    assert trade["net_pnl"] == pytest.approx(trade["gross_pnl"] - trade["fees"])
    assert (trade["gross_pnl"] > 0) == (reason != "STOP")


def test_short_trail_arms_at_3r_and_covers_above_middle_without_moving_stop():
    trade = trade_fixture()
    now = datetime(2026, 10, 7, 10, tzinfo=runtime.IST).timestamp()
    assert not exit_trade(trade, now, 98, 0.05, 900, trailing=True, middle=97)
    assert not trade.get("trail_armed")
    assert not exit_trade(trade, now + 1, 97, 0.05, 900, trailing=True, middle=98)
    assert trade["trail_armed"] and trade["stop"] == 101 and trade["quantity"] == 100
    assert not exit_trade(trade, now + 2, 97, 0.05, 900, trailing=True, middle=97)
    assert exit_trade(trade, now + 3, 97.1, 0.05, 900, trailing=True, middle=97)
    assert trade["reason"] == "BB_MIDDLE"


def test_stop_retained_after_trailing_armed():
    trade = {**trade_fixture(), "trail_armed": True, "trail_armed_at": 1}
    now = datetime(2026, 10, 7, 10, tzinfo=runtime.IST).timestamp()
    assert exit_trade(trade, now, 102, 0.05, 900, trailing=True, middle=99)
    assert trade["reason"] == "STOP"


def test_pending_short_entry_and_buy_cover_reconcile_without_redispatch(tmp_path):
    sink, trade = sink_fixture(tmp_path), trade_fixture()
    assert sink.enter(trade, {"ltp": 100}, 0.05)
    assert runtime.entries_blocked({"ABC": trade})
    assert sink.reconcile(trade, 1001) == "pending"
    sink.manager.get_order_status.return_value = status("complete", 99.5)
    assert sink.reconcile(trade, 1002) == "open"
    assert trade["entry"] == 99.5 and trade["target"] == 95
    assert sink.manager.place_order.call_count == 1
    sink.manager.place_order.return_value = True, {"mode": "analyze", "orderid": "two"}, 200
    sink.manager.get_order_status.return_value = status("open")
    assert not sink.exit(trade, 1003, {"ltp": 95}, "TARGET")
    assert not sink.exit(trade, 1004, {"ltp": 95}, "TARGET")
    assert [c.args[0]["action"] for c in sink.manager.place_order.call_args_list] == ["SELL", "BUY"]
    sink.manager.get_order_status.return_value = status("complete", 95.1)
    assert sink.reconcile(trade, 1005) == "closed"
    assert trade["net_pnl"] == pytest.approx(440)
    assert trade["exit_order_state"] == "complete"


def test_uncertain_sell_never_retried_and_stale_quote_does_not_dispatch(tmp_path):
    sink, trade = sink_fixture(tmp_path), trade_fixture()
    assert not sink.enter(trade, {"ltp": 100, "high": 99, "low": 98}, 0.05)
    sink.manager.place_order.assert_not_called()
    sink.manager.place_order.return_value = False, {}, 500
    assert sink.enter(trade, {"ltp": 100}, 0.05)
    assert runtime.entries_blocked({"ABC": trade})
    assert sink.place(trade, "SELL", {"ltp": 100}) is None
    assert sink.manager.place_order.call_count == 1


def test_clock_covers_short_and_cancels_unfilled_sell(tmp_path):
    sink, trade = sink_fixture(tmp_path), trade_fixture()
    now = datetime(2026, 10, 7, 15, 15, tzinfo=runtime.IST).timestamp()
    trade["entry_order_state"] = "complete"
    sink.manager.get_order_status.return_value = status("complete", 99)
    maintain_positions(
        sink, {"ABC": trade}, {"trades": [trade]}, {"ABC": (now - 1, {"ltp": 99})}, now
    )
    assert trade["reason"] == "SQUARE_OFF" and trade["net_pnl"] == 100
    assert sink.manager.place_order.call_args.args[0]["action"] == "BUY"
    trade = trade_fixture()
    sink.manager.get_order_status.return_value = status("open")
    assert sink.enter(trade, {"ltp": 100}, 0.05)
    sink.manager.get_order_status.side_effect = [status("open"), status("cancelled")]
    report, traded = {"trades": [trade]}, {"ABC": trade}
    maintain_positions(sink, traded, report, {}, now)
    assert not traded and not report["trades"]
    sink.manager.cancel_order.assert_called_once_with("one")


def test_schedules_are_add_only_and_idempotent(tmp_path):
    desired = configurations("fixture", tmp_path)
    existing = {f"existing-{i}": {"user_id": "fixture", "custom": [i]} for i in range(20)}
    before = json.dumps(existing)
    merged = merge_configurations(existing, desired)
    assert len(desired) == 8 and len(merged) == 28
    assert json.dumps(existing) == before
    assert all(merged[k] == v for k, v in existing.items())
    assert merge_configurations(merged, desired) == merged
    for c in desired.values():
        assert c["exchange"] == "NSE" and c["is_scheduled"] and not c["is_running"]
        assert (c["schedule_start"], c["schedule_stop"]) == ("09:15", "15:15")
        assert len(c["schedule_days"]) == 5
        assert (STAGED / "launchers" / c["file_name"]).is_file()
    sid = next(iter(desired))
    merged[sid]["user_id"] = "different"
    with pytest.raises(ValueError, match="Refusing"):
        merge_configurations(merged, desired)


def test_prepare_never_writes_active_schedules_and_rejects_production_output(tmp_path):
    path = tmp_path / "strategies/strategy_configs.json"
    path.parent.mkdir()
    raw = json.dumps({f"old{i}": {"user_id": "fixture"} for i in range(20)})
    path.write_text(raw)
    with pytest.raises(ValueError, match="isolated"):
        prepare(tmp_path, path.parent)
    output = tmp_path / ".development/equity-shorts/schedules"
    assert prepare(tmp_path, output) == (20, 8, 28)
    assert path.read_text() == raw
    assert len(json.loads((output / "strategy_configs.json").read_text())) == 28


def test_installed_package_and_launchers_exist():
    root = Path(__file__).resolve().parents[1]
    assert Path(runtime.__file__).parent == root / "strategies/short_equity"
    assert all((root / "strategies" / p["file"]).is_file() for p in PROFILES.values())


def test_repeated_short_order_lifecycle_releases_descriptors(tmp_path):
    import psutil

    sink = sink_fixture(tmp_path)
    # Warm lazy module imports before measuring the lock/session lifecycle.
    sink.enter(trade_fixture(), {"ltp": 100}, 0.05)
    process = psutil.Process()
    before = process.num_fds()
    for _ in range(120):
        trade = trade_fixture()
        sink.manager.get_order_status.return_value = status("complete", 100)
        assert sink.enter(trade, {"ltp": 100}, 0.05)
        sink.manager.get_order_status.return_value = status("complete", 99)
        assert sink.exit(trade, 1001, {"ltp": 99}, "TARGET")
        sink.manager.reset_mock()
        sink.persist.reset_mock()
    assert process.num_fds() <= before + 2


@pytest.mark.parametrize("delayed_status", [False, True])
def test_real_short_sandbox_roundtrip(monkeypatch, tmp_path, delayed_status):
    """Real OrderManager/ExecutionEngine, isolated test DB, synthetic current quotes."""
    import uuid
    from datetime import datetime

    from database import sandbox_db, symbol
    from sandbox import execution_engine, order_manager
    from strategies.short_equity.sandbox_execution import SandboxExecution

    assert "test" in str(sandbox_db.engine.url) and "test" in str(symbol.engine.url)
    sandbox_db.init_db()
    symbol.Base.metadata.create_all(symbol.engine)
    if symbol.SymToken.query.filter_by(symbol="SHORTTEST", exchange="NSE").first() is None:
        symbol.db_session.add(
            symbol.SymToken(
                symbol="SHORTTEST",
                brsymbol="SHORTTEST-EQ",
                name="Fixture",
                exchange="NSE",
                brexchange="NSE",
                token="99999992",
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
    owner = "short_fixture_" + uuid.uuid4().hex[:10]
    sink = SandboxExecution(owner, "weekday_short_fixed", Mock())
    sink.lock_path = tmp_path / "dispatch.lock"
    original_status = sink.manager.get_order_status
    if delayed_status:
        calls = [0]

        def delayed(orderid):
            calls[0] += 1
            if calls[0] == 1:
                return True, {"data": {"order_status": "open", "filled_quantity": 0}}, 200
            return original_status(orderid)

        monkeypatch.setattr(sink.manager, "get_order_status", delayed)
    trade = {
        "symbol": "SHORTTEST",
        "quantity": 99,
        "entry": 100,
        "stop": 105,
        "target": 81,
        "exit_ts": None,
    }
    try:
        assert sink.enter(trade, {"ltp": 100, "bid": 99, "ask": 101}, 0.05)
        if delayed_status:
            assert trade["entry_order_state"] == "pending"
            assert sink.reconcile(trade, 1790657100) == "open"
        assert trade["entry"] == 99 and trade["quantity"] == 100
        assert trade["entry"] * trade["quantity"] <= 10000
        assert trade["entry_order_state"] == "complete"
        assert trade["target"] == 81
        position = sandbox_db.SandboxPositions.query.filter_by(user_id=owner).one()
        assert position.quantity == -100
        assert sink.exit(trade, 1790657160, {"ltp": 95, "bid": 94, "ask": 96}, "SQUARE_OFF")
        assert trade["exit"] == 96 and trade["net_pnl"] == 300
        assert trade["exit_order_state"] == "complete"
        positions = sandbox_db.SandboxPositions.query.filter_by(user_id=owner).all()
        assert len(positions) == 1 and positions[0].quantity == 0
        orders = sandbox_db.SandboxOrders.query.filter_by(user_id=owner).all()
        assert {o.action for o in orders} == {"SELL", "BUY"}
        assert len(orders) == 2 and all(
            o.strategy == "Short10K_weekday_short_fixed" for o in orders
        )
    finally:
        sandbox_db.db_session.remove()
        symbol.db_session.remove()


def test_schedule_next_start_and_stop_are_weekdays_ist():
    from apscheduler.triggers.cron import CronTrigger

    for config in configurations("fixture", STAGED).values():
        for field, hour in (("schedule_start", 9), ("schedule_stop", 15)):
            h, m = map(int, config[field].split(":"))
            trigger = CronTrigger(
                day_of_week=",".join(config["schedule_days"]),
                hour=h,
                minute=m,
                timezone=runtime.IST,
            )
            now = datetime(2026, 10, 9, 16, tzinfo=runtime.IST)  # Friday after close
            next_time = trigger.get_next_fire_time(None, now)
            assert next_time == datetime(2026, 10, 12, hour, m, tzinfo=runtime.IST)


@pytest.mark.parametrize(
    "quote",
    [
        {"ltp": 102},
        {"ltp": 100, "bid": float("nan")},
        {"ltp": 100, "bid": -1},
        {"ltp": 50},
    ],
)
def test_invalid_short_risk_or_bid_does_not_submit(quote, tmp_path):
    sink = sink_fixture(tmp_path)
    assert not sink.enter(trade_fixture(), quote, 0.05)
    sink.manager.place_order.assert_not_called()


def test_short_order_field_regression_detects_long_side_mapping(monkeypatch, tmp_path):
    source = textwrap.dedent(inspect.getsource(SandboxExecution._place_locked))
    guard = '"entry_order" if side == "SELL" else "exit_order"'
    assert source.count(guard) == 1
    from strategies.short_equity import sandbox_execution

    namespace = dict(sandbox_execution.__dict__)
    exec(source.replace(guard, '"entry_order" if side == "BUY" else "exit_order"'), namespace)
    monkeypatch.setattr(SandboxExecution, "_place_locked", namespace["_place_locked"])
    with pytest.raises(AssertionError):
        test_pending_short_entry_and_buy_cover_reconcile_without_redispatch(tmp_path)


def test_short_report_metrics_keep_correct_sign(tmp_path):
    from services.scanner_strategy_reports import ReportStore

    trade = trade_fixture()
    trade.update(
        entry_ts=1791347400,
        exit_ts=1791347460,
        exit=99,
        gross_pnl=100,
        net_pnl=100,
        fees=0,
        reason="TARGET",
    )
    report = {
        "id": "paper-short-fixture",
        "day": "2026-10-07",
        "kind": "Sandbox SHORT",
        "status": "complete",
        "paths": ["PAPER"],
        "trades": [trade],
    }
    store = ReportStore(tmp_path / "reports.db")
    try:
        store.save("fixture", report)
        saved = store.get("fixture", report["id"])
        assert saved["trades"][0]["side"] == "SELL"
        assert saved["metrics"]["PAPER"]["gross_pnl"] == 100
        assert saved["metrics"]["PAPER"]["win_rate"] == 100
    finally:
        store.close()
