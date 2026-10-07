"""The twelve requested variants. Money is INR; deltas are signed long-option deltas."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = ROOT / "backtesting" / "nifty_options"
CAPITAL = 2_000_000
SANDBOX_CAPITAL = 50_000_000


@dataclass(frozen=True)
class Profile:
    name: str
    family: str
    holding: str
    expiry: str
    capital: int = CAPITAL
    loss_limit: int = 20_000
    hedge_width: int = 200

    @property
    def positional(self):
        return self.holding == "positional"

    @property
    def leg_stop_multiple(self):
        return 4.0 if self.family == "iron_condor" else 1.3 if self.family == "premium" else None

    @property
    def premium_target(self):
        return (10.0 if self.family == "iron_condor" else 27.5) if self.positional else 50.0


PROFILES = {
    f"{family}_{holding}_{expiry}_week": Profile(
        f"{family}_{holding}_{expiry}_week", family, holding, expiry
    )
    for family in ("iron_condor", "delta", "premium")
    for holding in ("intraday", "positional")
    for expiry in ("current", "next")
}


@dataclass(frozen=True)
class Policy:
    """Unspecified trading decisions must be supplied; never silently invented."""

    lots: int | None
    intraday_exit: str
    positional_exit: str
    loss_reset: str
    delta_trigger: str
    imbalance: float
    neutrality: str
    condor_entry: str
    delta_match_tolerance: float
    adjustment_cooldown_seconds: int
    reentry_cutoff: str

    def __post_init__(self):
        if self.lots is not None and (type(self.lots) is not int or self.lots < 1):
            raise ValueError("lots must be a positive integer")
        for field in ("intraday_exit", "positional_exit", "reentry_cutoff"):
            value = getattr(self, field)
            if not isinstance(value, str) or len(value) != 5:
                raise ValueError(f"{field} must be HH:MM")
            parsed = time.fromisoformat(value)
            if not time(9, 45) <= parsed <= time(15, 29):
                raise ValueError(f"{field} must be 09:45 through 15:29 IST")
        if self.loss_reset != "cycle":
            raise ValueError("loss_reset must be cycle (daily for intraday, full positional trade)")
        if self.delta_trigger not in {"either_050", "both_050", "imbalance"}:
            raise ValueError("Select either_050, both_050 or imbalance")
        if self.neutrality not in {"shorts", "all_legs"}:
            raise ValueError("neutrality must be shorts or all_legs")
        if self.condor_entry != "at_0930":
            raise ValueError("condor_entry must be at_0930")
        for field in ("imbalance", "delta_match_tolerance"):
            value = getattr(self, field)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f"{field} must be between 0 and 1")
        if (
            type(self.adjustment_cooldown_seconds) is not int
            or self.adjustment_cooldown_seconds < 0
        ):
            raise ValueError("adjustment cooldown must be a nonnegative integer")

    @classmethod
    def load(cls, path):
        raw = json.loads(Path(path).read_text())
        missing = [
            key for key in cls.__dataclass_fields__ if key != "lots" and raw.get(key) is None
        ]
        if missing:
            raise ValueError("Trading rules need answers: " + ", ".join(missing))
        return cls(**{key: raw[key] for key in cls.__dataclass_fields__})

    def to_dict(self):
        return asdict(self)
