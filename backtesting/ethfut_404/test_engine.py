"""Parity against original V1 rules, after removing only session restrictions."""

import inspect
from datetime import UTC, datetime, timezone
from types import SimpleNamespace

import numpy as np

from backtesting.ethfut_404.engine import REASONS, parameters, replay
from backtesting.ha_bb_vwap_v1_20260911.replay import definitions
from strategies.ha_bb_vwap_v1 import engine as original
from strategies.ha_bb_vwap_v1.models import Indicators, Snapshot


def reference_class():
    source = inspect.getsource(original)
    edits = {
        "        bar.validate(self.config.timeframe_minutes)\n": "",
        "        local = bar.observed_at.astimezone(IST)\n"
        "        same_day = self._signal and self._signal.candle.start.astimezone(IST).date() == local.date()\n"
        "        if not same_day:\n            self._signal = None\n": "",
        "elif time(9, 15) <= local.time() < self.cutoff:": "else:",
        "if not position_at_start and self.pending is None and local.time() < self.cutoff:": "if not position_at_start and self.pending is None:",
        "if now.astimezone(IST).time() >= self.cutoff or (\n"
        "            self._position_day and now.astimezone(IST).date() > self._position_day\n"
        "        ):": "if False:",
    }
    for before, after in edits.items():
        assert before in source
        source = source.replace(before, after)
    namespace = dict(vars(original))
    exec(compile(source, "<isolated ETH reference>", "exec"), namespace)
    return namespace["Strategy"]


def reference(events, cfg):
    adjusted = SimpleNamespace(
        **{**vars(cfg), "capital": 100000 / 0.01, "direction": cfg.direction, "name": cfg.name}
    )
    engine = reference_class()("ETHUSD", False, adjusted)
    result = []
    for i, e in enumerate(events):
        bar = SimpleNamespace(
            start=datetime.fromtimestamp(e[1] / 1e6, UTC),
            observed_at=datetime.fromtimestamp(e[0] / 1e6, UTC),
            open=e[3],
            high=e[3],
            low=e[3],
            close=e[3],
            volume=1.0,
            complete=bool(e[2]),
        )
        # Preserve cumulative raw OHLC checks; original engine uses only close for decisions.
        if engine._previous and engine._previous.candle.start == bar.start:
            old = engine._previous.candle
            bar.open, bar.high, bar.low = old.open, max(old.high, bar.high), min(old.low, bar.low)
        snap = Snapshot(bar, *e[4:8], Indicators(*e[8:20]))
        for intent in engine.on_snapshot(snap):
            sign = 1 if intent.side == "buy" else -1
            price = e[20] * (1 + sign * 0.0005)
            q = intent.quantity
            if intent.reason == "entry":
                from dataclasses import replace

                q = min(q, int(np.floor(100000 / (0.01 * price))))
                if q < 1:
                    engine.reject_order(intent.order_id)
                    continue
                engine.pending.intent = replace(intent, quantity=q)
            try:
                engine.acknowledge_fill(intent.order_id, price, q)
            except ValueError:
                engine.reject_order(intent.order_id)
                continue
            result.append(
                [
                    i,
                    e[21],
                    sign * q * 0.01,
                    price,
                    q * 0.01 * price * 0.0005,
                    REASONS.index(intent.reason),
                ]
            )
    if engine.position:
        e = events[-1]
        q = engine.position.quantity
        price = e[20] * (1 - cfg.direction * 0.0005)
        result.append(
            [len(events) - 1, e[21], -cfg.direction * q * 0.01, price, q * 0.01 * price * 0.0005, 8]
        )
    return np.array(result).reshape(-1, 6)


def test_all_404_parity():
    """Real tick-derived snapshots include long/short, partial, trail and indicator rules."""
    from backtesting.ethfut_404.data import OUT

    count = 0
    for cfg, _, _ in definitions():
        events = np.load(OUT / f"events_{cfg.timeframe_minutes}m.npy", mmap_mode="r")[:12000]
        actual, _ = replay(events, *parameters(cfg))
        expected = reference(events, cfg)
        np.testing.assert_allclose(actual[:, :6], expected, atol=1e-7, rtol=1e-12)
        count += len(actual)
    assert count > 100


def fixture():
    # A qualifying 23:59 signal, midnight breakout, next-day target.
    t = datetime(2024, 4, 1, 23, 59, tzinfo=UTC).timestamp() * 1e6
    e = np.full((4, 22), np.nan)
    e[:, :8] = [
        [t + 60e6, t, 1, 100, 98, 100, 98, 99],
        [t + 61e6, t + 60e6, 0, 101, 99, 101, 99, 100],
        [t + 62e6, t + 60e6, 0, 103, 99, 103, 99, 101],
        [t + 121e6, t + 120e6, 0, 120, 100, 120, 100, 110],
    ]
    e[:, 8], e[:, 11] = 90, 90
    e[:, 20], e[:, 21] = e[:, 3], e[:, 0]
    return e


def test_midnight_and_no_squareoff():
    cfg = definitions()[0][0]
    e = fixture()
    actual, marks = replay(e, *parameters(cfg))
    expected = reference(e, cfg)
    np.testing.assert_allclose(actual[:, :6], expected)
    assert actual[0, 0] == 1 and len(actual) >= 2
    assert actual[-1, 5] != 8  # Target, no forced midnight exit.
    assert abs(marks[-1, 1] - np.sum(-actual[:, 2] * actual[:, 3] - actual[:, 4])) < 1e-7


def test_gap_does_not_enter_from_stale_signal():
    cfg = definitions()[0][0]
    e = fixture()
    e[1:, 1] += 10 * 60e6
    actual, _ = replay(e, *parameters(cfg))
    assert len(actual) == 0


def test_end_liquidation():
    cfg = definitions()[0][0]
    e = fixture()[:2]
    actual, marks = replay(e, *parameters(cfg))
    assert list(actual[:, 5]) == [0, 8]
    assert np.isclose(actual[:, 2].sum(), 0)
    assert marks[-1, 1] < 0  # Entry/exit costs and adverse slippage.
