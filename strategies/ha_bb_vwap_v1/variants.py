"""Named variant families and lazy enumeration of the full parameter product."""

from dataclasses import replace
from itertools import product

from .models import EXIT_RULES, OFFSETS, PARTIALS, REWARDS, TRAILS, Config

FULL_COUNT = 4 * len(OFFSETS) * len(REWARDS) * len(TRAILS) * len(PARTIALS) * len(EXIT_RULES) ** 2


def iter_all():
    """One stop indicator AND one target indicator (each optional), OR exits.

    This is the Cartesian product of the listed alternatives, not arbitrary
    AND/OR Boolean formulas or a powerset of simultaneous indicator conditions.
    Nothing is materialized in memory or executed by iterating these configs.
    """
    for side, minutes, offset, reward, trail, partial, stop_rule, target_rule in product(
        ("buy", "sell"), (1, 5), OFFSETS, REWARDS, TRAILS, PARTIALS, EXIT_RULES, EXIT_RULES
    ):
        yield Config(side, minutes, offset, reward, trail, partial, stop_rule, target_rule)


def listed_variants():
    """Every listed alternative separately, other choices at their defaults."""
    for side, minutes in product(("buy", "sell"), (1, 5)):
        base = Config(side=side, timeframe_minutes=minutes)
        yield base
        for field, choices in (
            ("sl_buffer", OFFSETS),
            ("reward_risk", REWARDS),
            ("trail_fraction", TRAILS),
            ("partial", PARTIALS),
            ("stop_rule", EXIT_RULES),
            ("target_rule", EXIT_RULES),
        ):
            for value in choices:
                if value != getattr(base, field):
                    yield replace(base, **{field: value})
