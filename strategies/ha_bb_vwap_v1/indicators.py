"""Causal reference adapter using the installed openalgo.ta indicator library.

Supply real candles, not HA-only CSVs. Recomputes the supplied prefix; retains
no history. For future tick-scale use, share/calculate snapshots upstream rather
than recomputing them for every configuration. No data is fetched here.
"""

from collections.abc import Sequence

import numpy as np
from openalgo import ta

from .models import IST, Candle, Indicators, Snapshot


def build_snapshot(history: Sequence[Candle], current: Candle, timeframe_minutes: int) -> Snapshot:
    """History contains completed bars strictly before the current forming/final bar."""
    current.validate(timeframe_minutes)
    bars = [*history, current]
    previous = None
    for bar in bars:
        bar.validate(timeframe_minutes)
        if previous is not None and bar.start <= previous:
            raise ValueError("History must be chronological, unique, and exclude current")
        if bar is not current and not bar.complete:
            raise ValueError("History may contain only completed candles")
        previous = bar.start

    real = np.array([(b.open, b.high, b.low, b.close, b.volume) for b in bars], dtype=float)
    ha_close = real[:, :4].mean(axis=1)
    ha_open = np.empty(len(bars))
    ha_open[0] = (real[0, 0] + real[0, 3]) / 2
    for i in range(1, len(bars)):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
    ha_high = np.maximum.reduce((real[:, 1], ha_open, ha_close))
    ha_low = np.minimum.reduce((real[:, 2], ha_open, ha_close))
    missing = np.full(len(bars), np.nan)
    upper, middle, lower = (
        ta.bbands(ha_close, period=20, std_dev=2.0)
        if len(bars) >= 20
        else (missing, missing, missing)
    )
    macd, macd_signal, _ = (
        ta.macd(ha_close, fast_period=12, slow_period=26, signal_period=9)
        if len(bars) >= 35
        else (missing, missing, missing)
    )
    st, direction = (
        ta.supertrend(ha_high, ha_low, ha_close, period=14, multiplier=2.0)
        if len(bars) >= 15
        else (missing, missing)
    )
    today = current.start.astimezone(IST).date()
    session = real[[b.start.astimezone(IST).date() == today for b in bars]]
    # Feed only today's raw prices: reset at each IST session, no HA-price VWAP.
    vwap = (
        ta.vwap(session[:, 1], session[:, 2], session[:, 3], session[:, 4])
        if session[:, 4].sum() > 0
        else missing
    )
    values = Indicators(
        bb_upper=float(upper[-1]),
        bb_mid=float(middle[-1]),
        bb_lower=float(lower[-1]),
        vwap=float(vwap[-1]) if session[:, 4].sum() > 0 else float("nan"),
        sma9=float(ta.sma(ha_close, 9)[-1]) if len(bars) >= 9 else float("nan"),
        ema9=float(ta.ema(ha_close, 9)[-1]) if len(bars) >= 9 else float("nan"),
        ema21=float(ta.ema(ha_close, 21)[-1]) if len(bars) >= 21 else float("nan"),
        rsi=float(ta.rsi(ha_close, 14)[-1]) if len(bars) >= 15 else float("nan"),
        macd=float(macd[-1]),
        macd_signal=float(macd_signal[-1]),
        supertrend=float(st[-1]),
        supertrend_direction=float(direction[-1]),
    )
    return Snapshot(
        current,
        float(ha_open[-1]),
        float(ha_high[-1]),
        float(ha_low[-1]),
        float(ha_close[-1]),
        values,
    )
