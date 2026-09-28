"""One fixed long strategy, two explicitly modeled intraminute price paths."""

import math

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def indicators(raw):
    """Columns timestamp,O,H,L,C,V -> HA O,H,L,C,BB upper/mid/lower,VWAP."""
    n = len(raw)
    out = np.full((n, 8), np.nan)
    pv = vol = 0.0
    day = -1
    for i in range(n):
        t, o, h, low, c, v = raw[i]
        d = int(t + 19800) // 86400
        if d != day:
            pv = vol = 0.0
            day = d
        hc = (o + h + low + c) / 4
        ho = (o + c) / 2 if i == 0 else (out[i - 1, 0] + out[i - 1, 3]) / 2
        out[i, 0:4] = (ho, max(h, ho, hc), min(low, ho, hc), hc)
        if i >= 19:
            mean = 0.0
            for j in range(i - 19, i + 1):
                mean += out[j, 3] / 20
            var = 0.0
            for j in range(i - 19, i + 1):
                var += (out[j, 3] - mean) ** 2 / 20
            sd = math.sqrt(max(0.0, var))
            out[i, 4:7] = (mean + 2 * sd, mean, mean - 2 * sd)
        pv += (h + low + c) / 3 * v
        vol += v
        if vol > 0:
            out[i, 7] = pv / vol
    return out


@njit(cache=True)
def eligible(p, fraction, o, h, low, ho, volume, pv, vol, mean19, var19, signal_high):
    """Uses only a forming candle snapshot along the chosen modeled path."""
    hc = (o + h + low + p) / 4
    if low < ho - 1e-9 or hc <= ho or p <= signal_high or volume <= 0:
        return False
    mean = (19 * mean19 + hc) / 20
    variance = (var19 + 19 * (mean19 - mean) ** 2 + (hc - mean) ** 2) / 20
    upper = mean + 2 * math.sqrt(max(0.0, variance))
    cv = volume * fraction
    if vol + cv <= 0:
        return False
    vw = (pv + (h + low + p) / 3 * cv) / (vol + cv)
    return p > upper and p > vw


@njit(cache=True)
def buy_fill(p, slip, tick):
    return math.ceil((p * (1 + slip) - 1e-10) / tick) * tick


@njit(cache=True)
def sell_fill(p, slip, tick):
    return math.floor((p * (1 - slip) + 1e-10) / tick) * tick


@njit(cache=True, nogil=True)
def replay(
    raw,
    ha,
    allowed,
    cutoff,
    path,
    tick=0.05,
    slip=0.0005,
    fee=0.0005,
    capital=100000.0,
    rr=3.0,
    offset=0.10,
    steps=32,
):
    """Return trades (max one/day), with exact barrier exits on each modeled leg.

    Entry conditions sampled at 32 points/leg then bisected to first qualifying
    point in that bracket. This is a documented approximation, not recovered ticks.
    Exit reason 1 stop, 2 target, 3 scheduled. No final-bar forced liquidation:
    caller only allows sessions containing every minute through square-off.
    """
    n = len(raw)
    trades = np.zeros((n // 100 + 10, 18))
    count = 0
    day = -1
    used = False
    active = False
    pv = vol = 0.0
    entry = stop = target = qty = entry_time = entry_ref = 0.0
    sig_index = entry_index = 0
    for i in range(n):
        t, o, h, low, c, v = raw[i]
        d = int(t + 19800) // 86400
        minute = (int(t + 19800) % 86400) // 60
        if d != day:
            # Sessions are validated before replay, so no position can survive.
            assert not active
            day, used, pv, vol = d, False, 0.0, 0.0
        exit_ref = exit_time = reason = 0.0
        if active and minute >= cutoff:
            exit_ref, exit_time, reason = o, t, 3.0
        if allowed[i] and minute < cutoff:
            signal = False
            if not used and i >= 20 and raw[i - 1, 0] == t - 60:
                same_day = int(raw[i - 1, 0] + 19800) // 86400 == d
                signal = (
                    same_day
                    and ha[i - 1, 2] >= ha[i - 1, 0] - 1e-9
                    and ha[i - 1, 3] > ha[i - 1, 0]
                    and ha[i - 1, 1] > ha[i - 1, 4]
                    and ha[i - 1, 1] > ha[i - 1, 7]
                )
            if active or signal:
                vertices = np.array([o, low, h, c]) if path == 0 else np.array([o, h, low, c])
                run_h = run_l = o
                ho = ha[i, 0]
                mean19 = var19 = 0.0
                if signal:
                    for j in range(i - 19, i):
                        mean19 += ha[j, 3] / 19
                    for j in range(i - 19, i):
                        var19 += (ha[j, 3] - mean19) ** 2
                if active:
                    if o <= stop:
                        exit_ref, exit_time, reason = o, t, 1.0
                    elif o >= target:
                        # Resting limit target: conservatively fill at limit.
                        exit_ref, exit_time, reason = target, t, 2.0
                for leg in range(3):
                    if reason:
                        break
                    a, b = vertices[leg], vertices[leg + 1]
                    start_fraction = 0.0
                    if signal and not active and not used:
                        for k in range(steps + 1):
                            f = k / steps
                            p = a + (b - a) * f
                            hh, ll = max(run_h, p), min(run_l, p)
                            if eligible(
                                p,
                                (leg + f) / 3,
                                o,
                                hh,
                                ll,
                                ho,
                                v,
                                pv,
                                vol,
                                mean19,
                                var19,
                                ha[i - 1, 1],
                            ):
                                lo_f, hi_f = max(0.0, (k - 1) / steps), f
                                for _ in range(32):
                                    mid = (lo_f + hi_f) / 2
                                    mp = a + (b - a) * mid
                                    if eligible(
                                        mp,
                                        (leg + mid) / 3,
                                        o,
                                        max(run_h, mp),
                                        min(run_l, mp),
                                        ho,
                                        v,
                                        pv,
                                        vol,
                                        mean19,
                                        var19,
                                        ha[i - 1, 1],
                                    ):
                                        hi_f = mid
                                    else:
                                        lo_f = mid
                                start_fraction = hi_f
                                p = a + (b - a) * hi_f
                                entry = buy_fill(p, slip, tick)
                                # Round stop away from entry, target up to a valid tick.
                                stop = math.floor((ha[i - 1, 2] - offset + 1e-10) / tick) * tick
                                qty = math.floor(capital / entry)
                                if qty > 0 and entry > stop > 0:
                                    target = (
                                        math.ceil((entry + rr * (entry - stop) - 1e-10) / tick)
                                        * tick
                                    )
                                    entry_time = t + (leg + hi_f) * 20
                                    entry_ref, sig_index, entry_index = p, i - 1, i
                                    active = used = True
                                break
                    if active:
                        a2 = a + (b - a) * start_fraction
                        if b < a2 and b <= stop <= a2:
                            f = (stop - a) / (b - a)
                            exit_ref, exit_time, reason = stop, t + (leg + f) * 20, 1.0
                        elif b > a2 and a2 <= target <= b:
                            f = (target - a) / (b - a)
                            exit_ref, exit_time, reason = target, t + (leg + f) * 20, 2.0
                    run_h, run_l = max(run_h, b), min(run_l, b)
        if reason:
            # Profit target is a resting sell limit, never filled below its limit.
            exit_price = exit_ref if reason == 2 else sell_fill(exit_ref, slip, tick)
            gross = (exit_price - entry) * qty
            costs = (entry + exit_price) * qty * fee
            slippage = ((entry - entry_ref) + (exit_ref - exit_price)) * qty
            assert count < len(trades)
            trades[count] = (
                raw[sig_index, 0],
                entry_time,
                exit_time,
                entry,
                exit_price,
                qty,
                stop,
                target,
                gross,
                costs,
                gross - costs,
                reason,
                entry_ref,
                exit_ref,
                slippage,
                float(sig_index),
                float(entry_index),
                float(i),
            )
            count += 1
            active = False
        pv += (h + low + c) / 3 * v
        vol += v
    assert not active
    return trades[:count]
