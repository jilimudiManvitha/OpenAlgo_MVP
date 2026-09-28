"""BUY HA1m BB20x2 VWAP SL0.10 TP3R; open-low-high-close execution scenario.

See STRATEGY.md for the complete six-part strategy document.
"""

from engine import replay


def backtest(raw, ha, eligible_sessions, is_fo, tick, fee_bps=5, slippage_bps=5, steps=32):
    return replay(
        raw,
        ha,
        eligible_sessions,
        905 if is_fo else 920,
        0,
        tick,
        slippage_bps / 10000,
        fee_bps / 10000,
        100000.0,
        3.0,
        0.10,
        steps,
    )
