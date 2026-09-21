"""Pure, causal Bollinger crossings. Prices are ordinary closes, not HA candles."""

import math
from statistics import fmean, pstdev

INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def epoch(value):
    if isinstance(value, bool):
        raise ValueError("Invalid timestamp")
    result = float(value)
    if result > 100_000_000_000:
        result /= 1000
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Invalid timestamp")
    return result


def price(value):
    if isinstance(value, bool):
        raise ValueError("Invalid price")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Invalid price")
    return result


def bands(closes, period, deviation):
    if len(closes) < period:
        raise ValueError("Waiting for enough completed candles")
    window = closes[-period:]
    middle = fmean(window)
    width = deviation * pstdev(window)
    return {"middle": middle, "upper": middle + width, "lower": middle - width}


def history_rows(rows):
    """Reject conflicting duplicates; never manufacture missing candles."""
    result = {}
    for row in rows:
        ts, close = epoch(row["timestamp"]), price(row["close"])
        if ts in result and result[ts] != close:
            raise ValueError("Conflicting historical candles")
        result[ts] = close
    return sorted(result.items())


class Crossing:
    def __init__(self, period=20, deviation=2.0, side="both"):
        self.period, self.deviation, self.side = period, deviation, side
        self.previous = None
        self.last_timestamp = 0
        self.last_price = None
        self.last_bar = None
        self.fired = set()

    def reset(self):
        # A reconnect must establish a new baseline, not replay an unseen crossing.
        self.previous = None
        self.last_timestamp = 0
        self.last_price = None

    def observe(self, closes, timestamp, bar):
        if timestamp < self.last_timestamp or (
            timestamp == self.last_timestamp and closes[-1] == self.last_price
        ):
            return None, None
        levels = bands(closes, self.period, self.deviation)
        current = closes[-1]
        relation = (current > levels["upper"], current < levels["lower"])
        if bar != self.last_bar:
            self.fired.clear()
            self.last_bar = bar
        event = None
        if self.previous is not None:
            for index, side in enumerate(("upper", "lower")):
                if (
                    relation[index]
                    and not self.previous[index]
                    and side not in self.fired
                    and self.side in ("both", side)
                ):
                    self.fired.add(side)
                    event = {
                        "band": side,
                        "price": current,
                        "timestamp": timestamp,
                        "bar": bar,
                        **levels,
                    }
        self.previous = relation
        self.last_timestamp = timestamp
        self.last_price = current
        return event, {"price": current, "timestamp": timestamp, **levels}
