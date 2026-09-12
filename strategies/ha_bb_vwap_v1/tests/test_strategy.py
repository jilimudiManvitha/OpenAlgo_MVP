"""Synthetic correctness checks only; no historical or forward market testing."""

from dataclasses import replace
from datetime import datetime, timedelta
from math import isclose, isnan, sin

import pytest

from strategies.ha_bb_vwap_v1 import Candle, Config, Indicators, Snapshot, Strategy
from strategies.ha_bb_vwap_v1.engine import indicator_exit, signal_qualifies
from strategies.ha_bb_vwap_v1.indicators import build_snapshot
from strategies.ha_bb_vwap_v1.models import EXIT_RULES, IST, Position
from strategies.ha_bb_vwap_v1.variants import FULL_COUNT, iter_all, listed_variants

START = datetime(2026, 9, 11, 9, 15, tzinfo=IST)
VALUES = Indicators(102, 100, 98, 101, 100, 100, 100, 65, 1, 0, 95, -1)


def snap(
    start=START,
    complete=True,
    price=103,
    open_=100,
    high=104,
    low=100,
    ha_open=100,
    ha_high=104,
    ha_low=100,
    ha_close=103,
    values=VALUES,
    minutes=1,
):
    observed = start + (timedelta(minutes=minutes) if complete else timedelta(seconds=10))
    return Snapshot(
        Candle(start, observed, open_, high, low, price, 100, complete),
        ha_open,
        ha_high,
        ha_low,
        ha_close,
        values,
    )


def enter(side="buy", **kwargs):
    cfg = Config(side=side, timeframe_minutes=1, **kwargs)
    engine = Strategy("EXAMPLE", False, cfg)
    if side == "buy":
        signal = snap()
        entry = snap(
            START + timedelta(minutes=1),
            complete=False,
            price=105,
            open_=104,
            high=106,
            low=104,
            ha_open=103,
            ha_low=103,
            ha_high=106,
            ha_close=105,
        )
    else:
        values = replace(VALUES, vwap=99)
        signal = snap(
            price=97, high=100, low=96, ha_high=100, ha_low=96, ha_close=97, values=values
        )
        entry = snap(
            START + timedelta(minutes=1),
            complete=False,
            price=95,
            open_=96,
            high=96,
            low=94,
            ha_open=97,
            ha_high=97,
            ha_low=94,
            ha_close=95,
            values=values,
        )
    assert engine.on_snapshot(signal) == []
    orders = engine.on_snapshot(entry)
    assert len(orders) == 1
    return engine, orders[0], entry


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_entry_uses_real_price_and_explicit_fills(side):
    engine, order, _ = enter(side)
    assert order.side == side
    assert order.quantity == int(100000 / order.reference_price)
    assert engine.position is None
    engine.acknowledge_fill(order.order_id, order.reference_price, order.quantity)
    p = engine.position
    assert p.initial_stop == (99.9 if side == "buy" else 100.1)
    assert p.entry == order.reference_price
    assert isclose(abs(p.target - p.entry), 2 * p.risk)


def test_a_final_entry_candle_cannot_claim_an_intrabar_entry():
    engine = Strategy("X", False, Config(timeframe_minutes=1))
    engine.on_snapshot(snap())
    assert engine.on_snapshot(snap(START + timedelta(minutes=1), price=105, high=106)) == []


def test_pending_orders_block_assumed_fills_and_duplicate_orders():
    engine, order, entry = enter()
    with pytest.raises(RuntimeError):
        engine.on_snapshot(entry)
    with pytest.raises(ValueError):
        engine.acknowledge_fill(order.order_id, order.reference_price, order.quantity - 1)
    engine.reject_order(order.order_id)
    assert engine.on_snapshot(entry) == []
    assert engine.position is None


def test_signal_requires_both_filters_but_does_not_require_open_above_vwap():
    assert signal_qualifies(snap(), Config(timeframe_minutes=1))
    assert not signal_qualifies(snap(values=replace(VALUES, vwap=105)), Config())
    assert not signal_qualifies(snap(ha_low=99), Config())
    assert not signal_qualifies(snap(complete=False), Config())


def test_skipped_interval_expires_signal():
    engine = Strategy("X", False, Config(timeframe_minutes=1))
    engine.on_snapshot(snap())
    assert (
        engine.on_snapshot(snap(START + timedelta(minutes=2), complete=False, price=105, high=106))
        == []
    )


def held(side="buy", quantity=100, **kwargs):
    cfg = Config(side=side, timeframe_minutes=1, **kwargs)
    engine = Strategy("EXAMPLE", False, cfg)
    d = cfg.direction
    engine.position = Position(
        quantity, quantity, 100, 100 - d * 10, 100 - d * 10, 10, 100 + d * cfg.reward_risk * 10, 100
    )
    return engine


def update(price, minute=2, complete=False):
    return snap(
        START + timedelta(minutes=minute),
        complete=complete,
        price=price,
        open_=price,
        high=price,
        low=price,
        ha_open=price,
        ha_high=price,
        ha_low=price,
        ha_close=price,
    )


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_gap_through_stop_uses_observed_price(side):
    engine = held(side)
    price = 85 if side == "buy" else 115
    order = engine.on_snapshot(update(price))[0]
    assert order.reason == "stop_loss" and order.reference_price == price
    assert engine.position is not None
    engine.acknowledge_fill(order.order_id, price, order.quantity)
    assert engine.position is None


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_trail_activates_at_one_r_and_never_loosens(side):
    engine = held(side, trail_fraction=0.2, reward_risk=3)
    d = engine.config.direction
    assert engine.on_snapshot(update(100 + 9 * d)) == []
    assert engine.position.stop == 100 - 10 * d
    assert engine.on_snapshot(update(100 + 10 * d, minute=3)) == []
    assert isclose(engine.position.stop, 100 + 4 * d)
    assert engine.on_snapshot(update(100 + 8 * d, minute=4)) == []
    assert isclose(engine.position.stop, 100 + 4 * d)
    assert engine.on_snapshot(update(100 + 3 * d, minute=5))[0].reason == "stop_loss"


def test_large_rr_trail_locks_breakeven_at_activation():
    engine = held(trail_fraction=0.7, reward_risk=30)
    engine.on_snapshot(update(110))
    assert engine.position.stop == 100


@pytest.mark.parametrize(
    "preset,first,last,quantity",
    [("half_1r_2r", 110, 120, 50), ("quarter_1p5r_2p5r", 115, 125, 25)],
)
def test_partial_exits_are_once_only_and_use_original_risk(preset, first, last, quantity):
    engine = held(partial=preset, reward_risk=3)
    order = engine.on_snapshot(update(first))[0]
    assert order.quantity == quantity and order.reason == "partial_first"
    engine.acknowledge_fill(order.order_id, first, quantity)
    assert engine.position.risk == 10
    assert engine.on_snapshot(update(first, minute=3)) == []
    final = engine.on_snapshot(update(last, minute=4))[0]
    assert final.quantity == 100 - quantity and final.reason == "partial_final"


def test_small_quantities_never_emit_zero_quantity_orders():
    engine = held(quantity=1, partial="quarter_1p5r_2p5r", reward_risk=3)
    assert engine.on_snapshot(update(115)) == []
    assert engine.on_snapshot(update(125, minute=3))[0].quantity == 1


@pytest.mark.parametrize("is_fo,hour,minute", [(True, 15, 5), (False, 15, 20)])
def test_clock_squareoff_without_tick(is_fo, hour, minute):
    engine = held()
    engine.is_fo = is_fo
    at = START.replace(hour=hour, minute=minute)
    order = engine.on_clock(at, 100)[0]
    assert order.reason == "square_off" and order.quantity == 100
    engine.acknowledge_fill(order.order_id, 100, 100)
    assert engine.on_clock(at, 100) == []
    with pytest.raises(ValueError):
        engine.on_snapshot(update(103))


@pytest.mark.parametrize("rule", EXIT_RULES[1:])
@pytest.mark.parametrize("d", [1, -1])
def test_each_indicator_exit_direction_and_completion_gate(rule, d):
    level = 200 if d == 1 else 50
    values = Indicators(
        level, level, level, level, level, level, level, 59 if d == 1 else 41, -d, 0, level, d
    )
    previous = snap(values=replace(values, macd=d))
    final = snap(START + timedelta(minutes=1), values=values)
    assert indicator_exit(rule, final, previous, d)
    forming = replace(
        final,
        candle=replace(
            final.candle, complete=False, observed_at=final.candle.start + timedelta(seconds=10)
        ),
    )
    assert indicator_exit(rule, forming, previous, d) == rule.endswith("_tick")


def test_complete_ohlc_rule_requires_whole_candle_beyond_line():
    current = snap(ha_high=102, ha_close=99, values=replace(VALUES, bb_mid=100))
    assert not indicator_exit("bb_mid_full", current, None, 1)


def test_indicator_target_only_takes_gross_profit():
    engine = held(target_rule="rsi_tick")
    assert engine.on_snapshot(replace(update(99), indicators=replace(VALUES, rsi=50))) == []
    assert (
        engine.on_snapshot(replace(update(101, minute=3), indicators=replace(VALUES, rsi=50)))[
            0
        ].reason
        == "indicator_target"
    )


def test_snapshot_adapter_is_causal_and_daily_vwap_uses_raw_prices():
    bars = []
    for i in range(80):
        price = 100 + sin(i / 3) + i / 50
        start = START + timedelta(minutes=i)
        bars.append(
            Candle(
                start,
                start + timedelta(minutes=1),
                price,
                price + 1,
                price - 1,
                price + 0.5,
                100,
                True,
            )
        )
    snapshot = build_snapshot(bars[:-1], bars[-1], 1)
    expected_vwap = sum((b.high + b.low + b.close) / 3 for b in bars) / len(bars)
    assert isclose(snapshot.indicators.vwap, expected_vwap, rel_tol=1e-10)
    tomorrow = START + timedelta(days=1)
    current = Candle(tomorrow, tomorrow + timedelta(seconds=10), 150, 152, 149, 151, 10)
    assert isclose(build_snapshot(bars, current, 1).indicators.vwap, (152 + 149 + 151) / 3)
    with pytest.raises(ValueError):
        build_snapshot(bars, bars[-1], 1)


def test_indicator_warmup_does_not_produce_an_entry():
    raw = snap().candle
    snapshot = build_snapshot([], raw, 1)
    assert isnan(snapshot.indicators.bb_upper)
    assert not signal_qualifies(snapshot, Config())


def test_variant_coverage_and_stable_names():
    variants = list(listed_variants())
    assert len(variants) == 404
    assert len({v.name for v in variants}) == 404
    assert FULL_COUNT == 6_918_660
    assert next(iter_all()) == Config(side="buy", timeframe_minutes=1)
    assert {v.reward_risk for v in variants} == {x / 2 for x in range(4, 61)}
    assert {v.stop_rule for v in variants} == set(EXIT_RULES)
    assert {v.target_rule for v in variants} == set(EXIT_RULES)


def test_five_minute_entry_uses_only_immediate_next_five_minute_bar():
    engine = Strategy("X", False, Config(timeframe_minutes=5))
    engine.on_snapshot(snap(minutes=5))
    entry = snap(START + timedelta(minutes=5), complete=False, price=105, high=106, minutes=5)
    assert engine.on_snapshot(entry)[0].reason == "entry"


@pytest.mark.parametrize("is_fo,cutoff", [(True, (15, 5)), (False, (15, 20))])
def test_entry_is_forbidden_at_squareoff_cutoff(is_fo, cutoff):
    engine = Strategy("X", is_fo, Config(timeframe_minutes=1))
    at = START.replace(hour=cutoff[0], minute=cutoff[1])
    engine.on_snapshot(snap(at - timedelta(minutes=1)))
    assert engine.on_snapshot(snap(at, complete=False, price=105, high=106)) == []


def test_missing_squareoff_clock_is_caught_on_next_date():
    engine, order, _ = enter()
    engine.acknowledge_fill(order.order_id, order.reference_price, order.quantity)
    tomorrow = START + timedelta(days=1)
    assert engine.on_snapshot(snap(tomorrow, complete=False))[0].reason == "square_off"


def test_zero_volume_vwap_is_undefined():
    raw = replace(snap().candle, volume=0)
    assert isnan(build_snapshot([], raw, 1).indicators.vwap)


def test_alternative_interpretations_get_distinct_names():
    base = Config(side="sell")
    assert base.name != replace(base, short_stop_anchor="low").name
    assert base.name != replace(base, trail_basis="profit_reached").name
