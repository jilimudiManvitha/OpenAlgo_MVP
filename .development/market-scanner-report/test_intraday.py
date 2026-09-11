import numpy as np
import pandas as pd
import pytest

from intraday_core import ReplayConfig, continuous_today, execute, rank_snapshot


def fixture():
    start = int(pd.Timestamp('2026-09-11 09:15', tz='Asia/Kolkata').timestamp())
    raw = pd.DataFrame({'timestamp': start + np.arange(10) * 60, 'open': 100.,
                        'high': 100.2, 'low': 99.8, 'close': 100., 'volume': 100.})
    bars = raw.copy()
    bars['ha_open'], bars['ha_close'] = 100., 100.
    bars['ha_low'], bars['ha_high'] = 100., 101.
    bars['bb_upper'], bars['bb_lower'], bars['vwap'], bars['rvol'] = 102., 98., 99., 3.
    bars.loc[4, ['ha_open', 'ha_low', 'ha_high', 'ha_close']] = [100., 100., 104., 103.]
    raw.loc[5, ['open', 'high', 'low', 'close']] = [103., 105., 102., 104.5]
    raw.loc[6:, ['open', 'high', 'low', 'close']] = [104.5, 106., 103., 105.]
    membership = {int(t + 60): [1, 1, 0] for t in raw.timestamp}
    return raw, bars, membership


def test_top50_full_universe_union_and_price_reference():
    symbols = np.array([f'S{i:03}' for i in range(100)])
    close = np.arange(100.) + 50
    ranks, change, rv, count = rank_snapshot(symbols, close, np.arange(100.) + 1,
                                            np.full(100, 100.), np.full(100, 10.))
    assert count == 100
    assert ranks[99, 0] == ranks[99, 1] == 1
    assert ranks[0, 2] == 1
    assert np.count_nonzero(ranks[:, 0]) == 50
    assert change[60] == pytest.approx(10.)
    assert rv[24] == pytest.approx(2.5)


def test_missing_minute_does_not_fabricate_prices():
    raw, _, _ = fixture()
    valid = continuous_today(raw.drop(index=3), int(raw.timestamp.iloc[0]), int(raw.timestamp.iloc[-1] + 60))
    assert len(valid) == 3


def test_membership_required_at_signal_and_entry():
    raw, bars, members = fixture()
    cfg = ReplayConfig(fee_bps=0, slippage_bps=0)
    trades, rejects, *_ = execute(raw, bars, 1, members, cfg)
    assert len(trades) == 1 and trades[0]['status'] == 'OPEN'
    members[int(raw.timestamp.iloc[5])] = [0, 0, 0]
    trades, rejects, *_ = execute(raw, bars, 1, members, cfg)
    assert not trades and rejects[0]['reason'].startswith('not_scanner_eligible')


def test_position_survives_list_removal_and_marks_open_without_forced_exit():
    raw, bars, members = fixture()
    for t in raw.timestamp.iloc[6:]:
        members[int(t)] = [0, 0, 0]
    trades, _, curve, occupied, fees = execute(raw, bars, 1, members, ReplayConfig())
    assert len(trades) == 1 and trades[0]['status'] == 'OPEN'
    assert trades[0]['exit'] is None
    assert curve[-1] == pytest.approx(trades[0]['net_pnl'])
    assert occupied.max() <= 100000 and fees[-1] == pytest.approx(trades[0]['entry_cost'])


def test_stop_first_ambiguity_and_ledger_reconciliation():
    raw, bars, members = fixture()
    raw.loc[6, ['open', 'high', 'low', 'close']] = [105., 120., 90., 100.]
    trades, _, curve, _, fees = execute(raw, bars, 1, members, ReplayConfig())
    assert len(trades) == 1 and trades[0]['reason'] == 'stop'
    assert trades[0]['ambiguous']
    assert curve[-1] == pytest.approx(trades[0]['net_pnl'])
    assert fees[-1] == pytest.approx(trades[0]['entry_cost'] + trades[0]['exit_cost'])


def test_future_prices_do_not_change_prior_entry():
    raw, bars, members = fixture()
    before = execute(raw, bars, 1, members, ReplayConfig())[0][0]
    raw.loc[8:, ['open', 'high', 'low', 'close']] *= 2
    after = execute(raw, bars, 1, members, ReplayConfig())[0][0]
    for key in ['signal_timestamp', 'entry_timestamp', 'entry', 'quantity', 'entry_ranks']:
        assert before[key] == after[key]


def test_no_duplicate_entry_from_overlapping_lists_and_direction_not_forced():
    raw, bars, members = fixture()
    for t in members:
        members[t] = [0, 0, 2]  # A bullish signal in a loser remains a long signal.
    trades = execute(raw, bars, 1, members, ReplayConfig())[0]
    assert len(trades) == 1 and trades[0]['side'] == 'LONG'


def test_five_minute_gate_checked_again_after_signal_close():
    raw, _, members = fixture()
    start = int(raw.timestamp.iloc[0])
    bars = pd.DataFrame({'timestamp': [start - 300, start], 'ha_open': [100., 100.],
                         'ha_close': [100., 103.], 'ha_high': [101., 104.], 'ha_low': [100., 100.],
                         'bb_upper': [102., 102.], 'bb_lower': [98., 98.], 'vwap': [99., 99.], 'rvol': [3., 3.]})
    raw.loc[5, ['open', 'high', 'low', 'close']] = [100., 102., 99.8, 100.]
    members[start + 6 * 60] = [0, 0, 0]
    trades, rejects, *_ = execute(raw, bars, 5, members, ReplayConfig())
    assert not trades
    assert any(r['reason'].startswith('not_scanner_eligible') for r in rejects)
