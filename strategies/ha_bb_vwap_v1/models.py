"""Typed, broker-independent contracts for the September 12 strategy briefs."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OFFSETS = (0.10, 0.15, 0.20, 0.25, 0.30)
REWARDS = tuple(n / 2 for n in range(4, 61))
TRAILS = (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
PARTIALS = ("none", "half_1r_2r", "quarter_1p5r_2p5r")
EXIT_RULES = ("none",) + tuple(
    f"{indicator}_{mode}"
    for indicator in ("bb_mid", "vwap", "supertrend", "sma9", "ema9", "ema21", "rsi", "macd")
    for mode in ("tick", "full")
)


def number_label(value: float) -> str:
    return f"{value:g}".replace(".", "p")


@dataclass(frozen=True)
class Config:
    side: str = "buy"
    timeframe_minutes: int = 5
    sl_buffer: float = 0.10
    reward_risk: float = 2.0
    trail_fraction: float = 0.0
    partial: str = "none"
    stop_rule: str = "none"
    target_rule: str = "none"
    short_stop_anchor: str = "high"
    trail_basis: str = "target_distance"
    capital: float = 100_000.0

    def __post_init__(self):
        if self.side not in ("buy", "sell") or self.timeframe_minutes not in (1, 5):
            raise ValueError("Use buy/sell and 1/5 minutes")
        if self.sl_buffer not in OFFSETS or self.reward_risk not in REWARDS:
            raise ValueError("Buffer must be 0.10..0.30 step 0.05; RR 2..30 step 0.5")
        if self.trail_fraction not in TRAILS or self.partial not in PARTIALS:
            raise ValueError("Unknown trail or partial-exit preset")
        if self.stop_rule not in EXIT_RULES or self.target_rule not in EXIT_RULES:
            raise ValueError("Unknown indicator exit rule")
        if self.short_stop_anchor not in ("high", "low"):
            raise ValueError("short_stop_anchor must be high or low")
        if self.trail_basis not in ("target_distance", "profit_reached"):
            raise ValueError("Unknown trailing distance basis")
        if self.capital != 100_000.0:
            raise ValueError("The brief fixes capital at Rs 100,000 per trade")

    @property
    def direction(self):
        return 1 if self.side == "buy" else -1

    @property
    def name(self):
        name = (
            f"V1_{self.side}_{self.timeframe_minutes}m_HA_BB20x2_VWAP"
            f"_SL{number_label(self.sl_buffer)}_RR{number_label(self.reward_risk)}"
            f"_TR{int(self.trail_fraction * 100)}_PX{self.partial}"
            f"_SX{self.stop_rule}_TX{self.target_rule}"
        )
        if self.side == "sell" and self.short_stop_anchor != "high":
            name += f"_SA{self.short_stop_anchor}"
        if self.trail_basis != "target_distance":
            name += f"_TB{self.trail_basis}"
        return name


@dataclass(frozen=True)
class Candle:
    """Real, cumulative OHLCV for one interval; start and observed_at are aware."""

    start: datetime
    observed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool = False

    def validate(self, timeframe_minutes):
        if self.start.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("Timezone-aware timestamps are required")
        if not all(isfinite(x) for x in (self.open, self.high, self.low, self.close, self.volume)):
            raise ValueError("Nonfinite OHLCV")
        if (
            not 0
            < self.low
            <= min(self.open, self.close)
            <= max(self.open, self.close)
            <= self.high
        ):
            raise ValueError("Invalid real OHLC range")
        if self.volume < 0:
            raise ValueError("Negative volume")
        end = self.start + timedelta(minutes=timeframe_minutes)
        if self.complete and self.observed_at != end:
            raise ValueError("A completed candle must be observed at its interval end")
        if not self.complete and not self.start <= self.observed_at < end:
            raise ValueError("Forming update outside its interval")
        local = self.start.astimezone(IST)
        if local.second or local.microsecond or local.minute % timeframe_minutes:
            raise ValueError("Candle timestamp is not aligned to its timeframe")
        if not time(9, 15) <= local.time() < time(15, 30):
            raise ValueError("Only regular-session candles, 09:15..15:30 IST, are supported")


@dataclass(frozen=True)
class Indicators:
    bb_upper: float
    bb_mid: float
    bb_lower: float
    vwap: float
    sma9: float
    ema9: float
    ema21: float
    rsi: float
    macd: float
    macd_signal: float
    supertrend: float
    supertrend_direction: float  # openalgo: -1 green/up; +1 red/down


@dataclass(frozen=True)
class Snapshot:
    """HA and causal indicators evaluated only using information observed so far."""

    candle: Candle
    ha_open: float
    ha_high: float
    ha_low: float
    ha_close: float
    indicators: Indicators


@dataclass(frozen=True)
class OrderIntent:
    """A request for a future execution adapter; never an executed broker order."""

    order_id: int
    side: str
    quantity: int
    reference_price: float
    reason: str
    observed_at: datetime


@dataclass
class Position:
    quantity: int
    original_quantity: int
    entry: float
    initial_stop: float
    stop: float
    risk: float
    target: float
    best_price: float
    partial_done: bool = False
