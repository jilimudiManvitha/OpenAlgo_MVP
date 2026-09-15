"""Streaming must preserve the verified full replay across arbitrary boundaries."""

import pickle

import numpy as np

from backtesting.btcfut_404.engine import parameters, replay
from backtesting.btcfut_404.run import SOURCE, accumulate, blank_stats, load_month, snapshots
from backtesting.ethfut_404.engine import replay as full_replay
from backtesting.ethfut_404.test_engine import fixture, reference
from backtesting.ha_bb_vwap_v1_20260911.replay import Maker, definitions


def test_all_404_chunk_carry_matches_verified_full_engine():
    from backtesting.ethfut_404.data import OUT

    arrays = {m: np.load(OUT / f"events_{m}m.npy", mmap_mode="r")[:12000] for m in (1, 5)}
    for cfg, _, _ in definitions():
        events = arrays[cfg.timeframe_minutes]
        expected_fills, expected_marks = full_replay(events, *parameters(cfg))
        fills, marks, state = [], [], None
        for start in range(0, len(events), 997):
            end = min(start + 997, len(events))
            f, m, state = replay(events[start:end], *parameters(cfg), state=state,
                                 final=end == len(events), offset=start)
            state = pickle.loads(pickle.dumps(state))
            fills.append(f)
            marks.append(m)
        np.testing.assert_allclose(np.concatenate(fills), expected_fills, atol=1e-7)
        np.testing.assert_allclose(np.concatenate(marks), expected_marks, atol=1e-7)


def test_real_btc_snapshots_and_original_reference():
    ticks = tuple(x[:3000] for x in load_month(sorted(SOURCE.rglob("*.zip"))[0]))
    for minutes in (1, 5):
        expected, _ = snapshots(minutes, ticks, Maker([]), None)
        maker, active, pieces = Maker([]), None, []
        for start in range(0, len(ticks[0]), 113):
            piece, active = snapshots(minutes, tuple(x[start:start+113] for x in ticks), maker, active)
            maker, active = pickle.loads(pickle.dumps((maker, active)))
            pieces.append(piece)
        np.testing.assert_allclose(np.concatenate(pieces), expected, equal_nan=True)
        for cfg, _, _ in definitions():
            if cfg.timeframe_minutes != minutes:
                continue
            actual, _, _ = replay(expected, *parameters(cfg))
            wanted = reference(expected, cfg)
            np.testing.assert_allclose(actual[:, :6], wanted, atol=1e-7, rtol=1e-12)


def test_boundary_position_signal_and_final_liquidation():
    cfg = definitions()[0][0]
    events = fixture()
    f1, _, state = replay(events[:1], *parameters(cfg), final=False)
    f2, _, state = replay(events[1:2], *parameters(cfg), state=state, final=False, offset=1)
    assert len(f1) == 0 and list(f2[:, 5]) == [0]
    f3, _, state = replay(events[2:3], *parameters(cfg), state=state, final=True, offset=2)
    assert f3[-1, 5] == 8 and state[0, 0] == 0
    assert abs(np.concatenate((f2, f3))[:, 2].sum()) < 1e-8


def test_drawdown_and_daily_carry_do_not_lose_intraday_extremes():
    day = 86400000000
    marks = np.array([[day, 20], [day+1, -30], [day+2, 10], [2*day, 40], [2*day+1, -50]])
    whole, split = blank_stats(), blank_stats()
    accumulate(whole, marks, [])
    accumulate(split, marks[:2], [])
    accumulate(split, marks[2:], [])
    assert whole == split
    assert whole["dd"] == 90 and whole["min"] == -50
    assert whole["daily"] == {1: 10, 2: -50}
