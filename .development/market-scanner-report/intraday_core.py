"""Pure scanner gating and partial-session execution for research only."""
from dataclasses import dataclass
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parents[1] / 'six-task-research/backtesting/all_stock_ha'
sys.path.insert(0, str(ENGINE))
from engine import Config, ha_values, signals

OHLCV = ['open', 'high', 'low', 'close', 'volume']


def valid_frame(rows):
    d = pd.DataFrame(rows, columns=['timestamp'] + OHLCV)
    if d.empty:
        return d
    d = d.sort_values('timestamp').reset_index(drop=True)
    if d.timestamp.duplicated().any():
        raise ValueError('duplicate_timestamp')
    a = d[OHLCV].to_numpy(dtype=float)
    good = (np.isfinite(a).all(axis=1) & (a[:, :4] > 0).all(axis=1) & (a[:, 4] >= 0)
            & (a[:, 1] >= a[:, :4].max(axis=1)) & (a[:, 2] <= a[:, :4].min(axis=1)))
    if not good.all() or (d.timestamp % 60 != 0).any():
        raise ValueError('invalid_ohlcv_or_timestamp')
    return d


def continuous_today(d, start, cutoff):
    """Retain the proven continuous prefix; never invent missing bars."""
    d = d[(d.timestamp >= start) & (d.timestamp + 60 <= cutoff)].copy()
    expected = start + np.arange(len(d)) * 60
    bad = np.flatnonzero(d.timestamp.to_numpy() != expected)
    if len(bad):
        d = d.iloc[:bad[0]].copy()
    return d.reset_index(drop=True)


def rank_snapshot(symbols, closes, cumulative, previous, average, limit=50):
    valid = np.isfinite(closes) & np.isfinite(previous) & (previous > 0) & (closes > 0) & (cumulative > 0)
    changes = np.full(len(symbols), np.nan)
    np.divide(closes - previous, previous, out=changes, where=valid)
    changes *= 100
    rv = np.full(len(symbols), np.nan)
    np.divide(cumulative, average, out=rv, where=valid & np.isfinite(average) & (average > 0))
    indices = np.flatnonzero(valid)
    shock = sorted((i for i in indices if rv[i] > 1), key=lambda i: (-rv[i], -changes[i], symbols[i]))[:limit]
    gain = sorted((i for i in indices if changes[i] > 0), key=lambda i: (-changes[i], symbols[i]))[:limit]
    loss = sorted((i for i in indices if changes[i] < 0), key=lambda i: (changes[i], symbols[i]))[:limit]
    ranks = np.zeros((len(symbols), 3), dtype=np.uint16)
    for group, selected in enumerate([shock, gain, loss]):
        for rank, i in enumerate(selected, 1):
            ranks[i, group] = rank
    return ranks, changes, rv, int(valid.sum())


def prepare(d, tf, session_start, daily_baselines):
    """Warm HA continuously through available history; only complete signal bars."""
    d = d.copy()
    local = pd.to_datetime(d.timestamp, unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    minute = local.dt.hour * 60 + local.dt.minute
    d = d[(minute >= 555) & (minute < 930)].copy()
    d['bucket'] = (d.timestamp + 19800 - 555 * 60) // (tf * 60)
    g = d.groupby('bucket', sort=True)
    bars = g.agg(timestamp=('timestamp', 'first'), open=('open', 'first'), high=('high', 'max'),
                 low=('low', 'min'), close=('close', 'last'), volume=('volume', 'sum'), count=('timestamp', 'size'))
    bars = bars[bars['count'] == tf].reset_index(drop=True)
    ha = ha_values(bars[OHLCV].to_numpy(dtype=float))
    bars[['ha_open', 'ha_high', 'ha_low', 'ha_close']] = ha
    mid = bars.ha_close.rolling(20).mean()
    sd = bars.ha_close.rolling(20).std(ddof=0)
    bars['bb_middle'], bars['bb_upper'], bars['bb_lower'] = mid, mid + 2 * sd, mid - 2 * sd
    days = (bars.timestamp + 19800) // 86400
    cumulative = bars.volume.groupby(days).cumsum()
    tpv = (bars.high + bars.low + bars.close) / 3 * bars.volume
    bars['vwap'] = tpv.groupby(days).cumsum() / cumulative.replace(0, np.nan)
    baseline = math.fsum(x['volume'] for x in daily_baselines[-20:]) / 20 if len(daily_baselines) >= 20 else np.nan
    bars['rvol'] = np.nan
    today = bars.timestamp >= session_start
    bars.loc[today, 'rvol'] = cumulative[today] / baseline if baseline > 0 else np.nan
    return bars


@dataclass(frozen=True)
class ReplayConfig:
    allocation: float = 100000.
    tick: float = .01
    lot: int = 1
    fee_bps: float = 5.
    slippage_bps: float = 5.
    reward_r: float = 2.
    square_off: int = 920


def execute(raw, bars, tf, rank_by_close, cfg):
    """Only finalized prior signals/selection enter; open positions remain open."""
    up = lambda x: math.ceil(x / cfg.tick - 1e-9) * cfg.tick
    down = lambda x: math.floor(x / cfg.tick + 1e-9) * cfg.tick
    directions = signals(bars, Config())
    ends = bars.timestamp.to_numpy(dtype=np.int64) + tf * 60
    cumulative = raw.volume.cumsum()
    vwap = ((raw.high + raw.low + raw.close) / 3 * raw.volume).cumsum() / cumulative.replace(0, np.nan)
    position, records, rejects = None, [], []
    used = set()
    realized, fees = 0., 0.
    curve, occupied, fee_curve = [], [], []
    last_exit = -1
    for i, candle in enumerate(raw.itertuples(index=False)):
        t = int(candle.timestamp)
        minute = (t // 60 + 330) % 1440
        notional = position['entry_notional'] if position else 0.
        entered = False
        s = int(np.searchsorted(ends, t, side='right') - 1)
        if position is None and s >= 0 and s not in used and 560 <= minute < cfg.square_off and ends[s] <= t < ends[s] + tf * 60 and ends[s] > last_exit:
            side = int(directions[s])
            if side:
                signal_ranks = rank_by_close.get(int(ends[s]))
                entry_ranks = rank_by_close.get(t)
                if signal_ranks is None or not any(signal_ranks) or entry_ranks is None or not any(entry_ranks):
                    rejects.append({'signal_timestamp': int(bars.timestamp.iloc[s]), 'decision_timestamp': t, 'reason': 'not_scanner_eligible_at_signal_or_entry'})
                    used.add(s)
                elif i > 0 and np.isfinite(vwap.iloc[i - 1]):
                    sig = bars.iloc[s]
                    reference = sig.ha_high if side == 1 else sig.ha_low
                    vw = vwap.iloc[i - 1]
                    trigger = down(max(reference, vw)) + cfg.tick if side == 1 else up(min(reference, vw)) - cfg.tick
                    crossed = candle.high >= trigger if side == 1 else candle.low <= trigger
                    if crossed:
                        base = max(candle.open, trigger) if side == 1 else min(candle.open, trigger)
                        entry = up(base * (1 + cfg.slippage_bps / 10000)) if side == 1 else down(base * (1 - cfg.slippage_bps / 10000))
                        stop = down(sig.ha_low) if side == 1 else up(sig.ha_high)
                        risk = side * (entry - stop)
                        quantity = math.floor(cfg.allocation / entry / cfg.lot) * cfg.lot if entry > 0 else 0
                        used.add(s)
                        if risk <= 0 or quantity <= 0:
                            rejects.append({'signal_timestamp': int(sig.timestamp), 'decision_timestamp': t, 'reason': 'invalid_risk_or_unaffordable_quantity'})
                        else:
                            target = up(entry + cfg.reward_r * risk) if side == 1 else down(entry - cfg.reward_r * risk)
                            notional = entry * quantity
                            cost = notional * cfg.fee_bps / 10000
                            realized -= cost
                            fees += cost
                            position = {'signal_timestamp': int(sig.timestamp), 'signal_available_at': int(ends[s]),
                                        'entry_timestamp': t, 'side': 'LONG' if side == 1 else 'SHORT',
                                        'direction': side, 'entry': entry, 'stop': stop, 'target': target,
                                        'quantity': quantity, 'entry_notional': notional, 'entry_cost': cost,
                                        'signal_rvol_20': float(sig.rvol), 'signal_ranks': list(map(int, signal_ranks)),
                                        'entry_ranks': list(map(int, entry_ranks)), 'ambiguous': False}
                            entered = True
        if position:
            p = position
            side = p['direction']
            stop_hit = candle.low <= p['stop'] if side == 1 else candle.high >= p['stop']
            target_hit = candle.high >= p['target'] if side == 1 else candle.low <= p['target']
            reason, price = None, None
            if not entered and minute >= cfg.square_off:
                reason, price = 'square_off', candle.open
            elif not entered and (candle.open <= p['stop'] if side == 1 else candle.open >= p['stop']):
                reason, price = 'gap_stop', candle.open
            elif not entered and (candle.open >= p['target'] if side == 1 else candle.open <= p['target']):
                reason, price = 'target', p['target']
            elif stop_hit:
                reason, price = 'stop', p['stop']
            elif target_hit:
                reason, price = 'target', p['target']
            p['ambiguous'] = bool(p['ambiguous'] or (stop_hit and target_hit) or (entered and (stop_hit or target_hit)))
            if reason:
                if reason != 'target':
                    price = max(cfg.tick, down(price * (1 - cfg.slippage_bps / 10000))) if side == 1 else up(price * (1 + cfg.slippage_bps / 10000))
                gross = side * p['quantity'] * (price - p['entry'])
                cost = p['quantity'] * price * cfg.fee_bps / 10000
                realized += gross - cost
                fees += cost
                p.update(status='CLOSED', exit_timestamp=t, exit=price, exit_cost=cost, gross_pnl=gross,
                         net_pnl=gross - p['entry_cost'] - cost, reason=reason)
                records.append(p)
                position = None
                last_exit = t
        marked = position['direction'] * position['quantity'] * (candle.close - position['entry']) if position else 0.
        curve.append(realized + marked)
        occupied.append(notional)
        fee_curve.append(fees)
    if position:
        last = raw.iloc[-1]
        p = position
        gross = p['direction'] * p['quantity'] * (last.close - p['entry'])
        p.update(status='OPEN', exit_timestamp=None, exit=None, exit_cost=0., gross_pnl=gross,
                 net_pnl=gross - p['entry_cost'], reason='open_at_cutoff', mark_timestamp=int(last.timestamp), mark_price=float(last.close))
        records.append(p)
    return records, rejects, np.array(curve), np.array(occupied), np.array(fee_curve)
