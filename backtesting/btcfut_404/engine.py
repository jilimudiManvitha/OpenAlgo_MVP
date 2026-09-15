"""Compiled replay of V1 rules, with session gates removed and fractional BTC sizing.

The original package remains unchanged. Parity tests compare every variant with
an isolated 24/7 reference subclass of the original engine.
"""

import numpy as np
from numba import njit

RULES = ["none"] + [
    f"{x}_{mode}"
    for x in ("bb_mid", "vwap", "supertrend", "sma9", "ema9", "ema21", "rsi", "macd")
    for mode in ("tick", "full")
]
REASONS = [
    "entry",
    "stop_loss",
    "trailing_stop",
    "indicator_stop",
    "fixed_target",
    "indicator_target",
    "partial_final",
    "partial_first",
    "end_of_data",
]


@njit(cache=True)
def indicator(rule, e, prev, closed, d):
    if rule == 0:
        return False
    full = rule % 2 == 0
    if full and not e[2]:
        return False
    kind = (rule - 1) // 2
    if kind == 6:
        return np.isfinite(e[15]) and (e[15] < 60 if d == 1 else e[15] > 40)
    if kind == 7:
        previous = closed if full else prev
        a, b = previous[16] - previous[17], e[16] - e[17]
        return np.isfinite(a) and np.isfinite(b) and d * a >= 0 > d * b
    column = (9, 11, 18, 12, 13, 14)[kind]
    level = e[column]
    if not np.isfinite(level):
        return False
    if kind == 2:
        if e[19] != d:
            return False
        if not full:
            return True
    price = (e[5] if d == 1 else e[6]) if full else e[3]
    return d * (price - level) < 0


@njit(cache=True)
def wick(e, d):
    tol = max(abs(e[4]), 1.0) * 1e-10
    return e[6] >= e[4] - tol if d == 1 else e[5] <= e[4] + tol


@njit(cache=True)
def replay(
    events,
    d,
    minutes,
    buffer,
    rr,
    trail,
    partial,
    stop_rule,
    target_rule,
    capital=100000.0,
    unit=0.01,
    fee_rate=0.0005,
    slippage=0.0005,
    state=None,
    final=True,
    offset=0,
):
    # fill columns: event index, execution time, signed BTC, price, fees, reason,
    # entry signal bucket, initial stop, target. One intent maximum per snapshot.
    fills = np.empty((len(events) + 1, 9))
    marks = np.empty((len(events) + 1, 2))
    nf = nm = 0
    quantity = original = 0
    entry = stop = risk = target = best = cash = 0.0
    signal = -1
    used = -1.0
    partial_done = False
    previous = np.full(22, np.nan)
    closed = np.full(22, np.nan)
    signal_bucket = initial_stop = 0.0
    signal_row = np.full(22, np.nan)
    if state is not None:
        quantity, original = int(state[0, 0]), int(state[0, 1])
        entry, stop, risk, target, best, cash = state[0, 2:8]
        signal, used = int(state[0, 8]), state[0, 9]
        partial_done = bool(state[0, 10])
        signal_bucket, initial_stop = state[0, 11:13]
        previous, closed, signal_row = state[1].copy(), state[2].copy(), state[3].copy()
    for i in range(len(events)):
        e = events[i]
        was_open = quantity > 0
        reason = -1
        q = quantity
        px = e[3]
        if quantity:
            if d * (px - stop) <= 0:
                reason = 1
            else:
                best = max(best, px) if d == 1 else min(best, px)
                favourable = d * (best - entry)
                if trail and rr >= 2 and favourable >= risk:
                    candidate = best - d * trail * rr * risk
                    candidate = max(entry, candidate) if d == 1 else min(entry, candidate)
                    stop = max(stop, candidate) if d == 1 else min(stop, candidate)
                if d * (px - stop) <= 0:
                    reason = 2
                elif indicator(stop_rule, e, previous, closed, d):
                    reason = 3
                elif d * (px - target) >= 0:
                    reason = 4
                elif indicator(target_rule, e, previous, closed, d) and d * (px - entry) > 0:
                    reason = 5
                elif partial:
                    first, last, fraction = (1.0, 2.0, 0.5) if partial == 1 else (1.5, 2.5, 0.25)
                    profit_r = d * (px - entry) / risk
                    if profit_r >= last:
                        reason = 6
                    elif not partial_done and profit_r >= first:
                        q = min(int(np.floor(original * fraction)), quantity - 1)
                        if q > 0:
                            reason = 7
        elif signal >= 0:
            s = signal_row
            expected = s[1] + minutes * 60_000_000
            if e[1] > expected:
                signal = -1
            elif e[1] == expected and s[1] != used and not e[2] and wick(e, d):
                band = e[8] if d == 1 else e[10]
                threshold = s[5] if d == 1 else s[6]
                if (
                    np.isfinite(band)
                    and np.isfinite(e[11])
                    and d * (px - threshold) > 0
                    and d * (px - band) > 0
                    and d * (px - e[11]) > 0
                ):
                    initial_stop = s[6] - buffer if d == 1 else s[5] + buffer
                    r = d * (px - initial_stop)
                    if initial_stop > 0 and r > 0 and px + d * rr * r > 0:
                        used = s[1]
                        fill_price = e[20] * (1 + d * slippage)
                        q = min(
                            int(np.floor(capital / (px * unit))),
                            int(np.floor(capital / (fill_price * unit))),
                        )
                        fill_risk = d * (fill_price - initial_stop)
                        if q > 0 and fill_risk > 0 and fill_price + d * rr * fill_risk > 0:
                            reason = 0
                            signal_bucket = s[1]
        if reason >= 0:
            side = d if reason == 0 else -d
            fill_price = e[20] * (1 + side * slippage)
            fee = q * unit * fill_price * fee_rate
            cash -= fee
            if reason == 0:
                quantity = original = q
                entry = best = fill_price
                stop = initial_stop
                risk = d * (entry - stop)
                target = entry + d * rr * risk
                partial_done = False
            else:
                cash += d * (fill_price - entry) * q * unit
                quantity -= q
                if reason == 7:
                    partial_done = True
            fills[nf] = (
                float(i + offset),
                e[21],
                side * q * unit,
                fill_price,
                fee,
                float(reason),
                signal_bucket,
                initial_stop,
                target,
            )
            nf += 1
        if e[2]:
            # Original code arms only when no position existed at observation start.
            if not was_open:
                band = e[8] if d == 1 else e[10]
                extreme = e[5] if d == 1 else e[6]
                signal = (
                    0
                    if (
                        np.isfinite(band)
                        and np.isfinite(e[11])
                        and wick(e, d)
                        and d * (extreme - band) > 0
                        and d * (extreme - e[11]) > 0
                    )
                    else -1
                )
            if not was_open and signal >= 0:
                signal_row = e.copy()
            closed = e.copy()
        # Execution-time MTM, including fills following a bar-boundary decision.
        marks[nm] = (e[21], cash + d * (e[20] - entry) * quantity * unit)
        nm += 1
        previous = e.copy()
    if final and quantity:
        e = events[-1]
        price = e[20] * (1 - d * slippage)
        fee = quantity * unit * price * fee_rate
        cash += d * (price - entry) * quantity * unit - fee
        fills[nf] = (
            float(offset + len(events) - 1),
            e[21],
            -d * quantity * unit,
            price,
            fee,
            8.0,
            signal_bucket,
            initial_stop,
            target,
        )
        nf += 1
        marks[nm] = (e[21], cash)
        nm += 1
        quantity = 0
    updated = np.full((4, 22), np.nan)
    updated[0, :13] = np.array([quantity, original, entry, stop, risk, target, best, cash,
                               signal, used, partial_done, signal_bucket, initial_stop])
    updated[1], updated[2], updated[3] = previous, closed, signal_row
    return fills[:nf], marks[:nm], updated


def parameters(cfg):
    return (
        cfg.direction,
        cfg.timeframe_minutes,
        cfg.sl_buffer,
        cfg.reward_risk,
        cfg.trail_fraction,
        ("none", "half_1r_2r", "quarter_1p5r_2p5r").index(cfg.partial),
        RULES.index(cfg.stop_rule),
        RULES.index(cfg.target_rule),
    )
