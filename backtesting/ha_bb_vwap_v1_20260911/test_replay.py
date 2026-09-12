"""Focused simulator checks; synthetic data only."""

import sys
from dataclasses import fields
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from replay import START, Maker, charges, event_stream

from strategies.ha_bb_vwap_v1.indicators import build_snapshot
from strategies.ha_bb_vwap_v1.models import Candle


def candles(count=80):
    result = []
    for i in range(count):
        start = START + timedelta(minutes=i)
        price = 100 + np.sin(i / 3) + i / 50
        result.append(
            Candle(
                start,
                start + timedelta(minutes=1),
                price,
                price + 1,
                price - 1,
                price + 0.3,
                100,
                True,
            )
        )
    return result


def test_cached_indicator_preview_matches_strategy_reference():
    bars = candles()
    maker = Maker(bars[:-1])
    got = maker.preview(bars[-1])
    expected = build_snapshot(bars[:-1], bars[-1], 1)
    for field in fields(expected.indicators):
        assert np.isclose(
            getattr(got.indicators, field.name),
            getattr(expected.indicators, field.name),
            equal_nan=True,
        )
    assert got.ha_open == expected.ha_open
    assert got.ha_low == expected.ha_low


def test_paths_end_at_identical_real_and_ha_candles():
    bars = candles(5)
    a, ca, _ = event_stream([], bars, bars, 1, "OLHC")
    b, cb, _ = event_stream([], bars, bars, 1, "OHLC")
    assert len(a) == 55 and len(b) == 55
    assert [(x.ha_open, x.ha_high, x.ha_low, x.ha_close) for x in ca] == [
        (x.ha_open, x.ha_high, x.ha_low, x.ha_close) for x in cb
    ]
    for events in (a, b):
        assert all(
            x[0].candle.observed_at <= y[0].candle.observed_at
            for x, y in zip(events, events[1:], strict=False)
        )
        assert all(s.candle.volume <= 100 for s, _ in events)


def test_five_minute_forming_data_does_not_see_later_minute_high():
    bars = candles(5)
    events, charts, _ = event_stream([], bars, [], 5, "OLHC")
    first = events[0][0]
    assert first.candle.high == bars[0].open
    assert first.candle.volume == 0
    assert charts[0].candle.high == max(b.high for b in bars)
    assert charts[0].candle.volume == 500
    assert sum(s.candle.complete for s, _ in events) == 1


def test_side_specific_intraday_charges():
    buy = charges("buy", 1000, 100)
    sell = charges("sell", 1000, 100)
    assert np.isclose(buy, 30.3406)
    assert np.isclose(sell, 52.3406)
