"""Pure selection from a timestamped option chain; no order or network side effects."""

import math
from dataclasses import dataclass
from datetime import date, datetime

from .profiles import Policy, Profile


class DataUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class Option:
    symbol: str
    expiry: date
    strike: float
    kind: str
    price: float
    delta: float | None
    lot_size: int
    timestamp: datetime
    underlying: str = "NIFTY"
    exchange: str = "NFO"

    def __post_init__(self):
        if self.underlying != "NIFTY" or self.exchange != "NFO":
            raise DataUnavailable("Only NIFTY options on NFO are allowed")
        if self.kind not in {"CE", "PE"} or not self.symbol:
            raise DataUnavailable("Invalid option identity")
        if any(not math.isfinite(v) for v in (self.price, self.strike)):
            raise DataUnavailable("Non-finite quote/Greek")
        if (
            self.price <= 0
            or self.strike <= 0
            or type(self.lot_size) is not int
            or self.lot_size <= 0
        ):
            raise DataUnavailable("Positive premium, strike and integer lot size required")
        valid_delta = self.delta is None or (
            math.isfinite(self.delta)
            and (0 <= self.delta <= 1 if self.kind == "CE" else -1 <= self.delta <= 0)
        )
        if not valid_delta:
            raise DataUnavailable("Expected signed long-option delta")
        if self.timestamp.tzinfo is None:
            raise DataUnavailable("Quote timestamp must be timezone aware")


def select_expiry(day, expiries, bucket):
    """Nearest/second listed unexpired weekly cycle, including holiday adjustments.

    Caller must supply the full weekly expiry catalogue, not a filtered price chain.
    Missing current-expiry quotes must never turn next week into current week.
    """
    available = sorted({d for d in expiries if d >= day})
    index = {"current": 0, "next": 1}[bucket]
    if len(available) <= index:
        raise DataUnavailable(f"Missing {bucket} weekly expiry")
    chosen = available[index]
    if (chosen - day).days > (7 if index == 0 else 14):
        raise DataUnavailable("Incomplete weekly expiry catalogue")
    return chosen


def select_legs(profile: Profile, policy: Policy, options, expiry):
    chain = [
        o
        for o in options
        if o.expiry == expiry and (profile.family == "premium" or o.delta is not None)
    ]
    if len({o.timestamp for o in chain}) != 1:
        raise DataUnavailable("Selection requires a synchronized chain")
    if len({o.symbol for o in chain}) != len(chain):
        raise DataUnavailable("Duplicate option symbols")
    calls = [o for o in chain if o.kind == "CE"]
    puts = [o for o in chain if o.kind == "PE"]
    if not calls or not puts:
        raise DataUnavailable("Both CE and PE chains required")

    def near_premium(candidates):
        if profile.positional:
            if profile.family == "iron_condor":
                candidates = [o for o in candidates if 9 <= o.price <= 11]
            else:
                candidates = [o for o in candidates if 25 < o.price < 30]
        if not candidates:
            raise DataUnavailable("No contract in requested premium band")
        return min(candidates, key=lambda o: (abs(o.price - profile.premium_target), -o.strike))

    if profile.family == "delta" and not profile.positional:
        ce = min(calls, key=lambda o: (abs(o.delta - 0.30), -o.strike))
        pe = min(puts, key=lambda o: (abs(abs(o.delta) - 0.30), -o.strike))
        if max(abs(abs(o.delta) - 0.30) for o in (ce, pe)) > policy.delta_match_tolerance:
            raise DataUnavailable("No strikes sufficiently near 0.30 delta")
    else:
        ce = near_premium(calls)
        if profile.family == "iron_condor":
            # Absolute deltas match; among exact ties prefer the highest PE strike.
            pe = min(puts, key=lambda o: (round(abs(abs(o.delta) - ce.delta), 12), -o.strike))
        else:
            pe = near_premium(puts)
    if profile.family != "premium" and abs(ce.delta + pe.delta) > policy.delta_match_tolerance:
        raise DataUnavailable("Selected shorts exceed the configured delta-match tolerance")
    result = [(ce, -1), (pe, -1)]
    if profile.family == "iron_condor":
        for short, strike in ((ce, ce.strike + 200), (pe, pe.strike - 200)):
            hedge = next((o for o in chain if o.kind == short.kind and o.strike == strike), None)
            if hedge is None:
                raise DataUnavailable("Required 200-point hedge is unavailable")
            result.append((hedge, 1))
    if len({o.lot_size for o, _ in result}) != 1:
        raise DataUnavailable("Leg lot sizes disagree")
    if profile.family != "premium" and policy.neutrality == "all_legs":
        if abs(sum(o.delta * side for o, side in result)) > policy.delta_match_tolerance:
            raise DataUnavailable("Matched shorts do not yield a neutral hedged basket")
    return result
