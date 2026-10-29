"""Protection matching for fresh baskets and carried positions; no I/O."""

from .selection import DataUnavailable


def protects(profile, short, long):
    strike = short["strike"] + (
        profile.hedge_width if short["kind"] == "CE" else -profile.hedge_width
    )
    return (
        long["side"] > 0
        and long["kind"] == short["kind"]
        and long["expiry"] == short["expiry"]
        and long["strike"] == strike
        and long["lot_size"] == short["lot_size"]
    )


def protected_quantity(profile, short, legs):
    return sum(leg["quantity"] for leg in legs if protects(profile, short, leg))


def missing_hedges(profile, legs, contracts):
    """Buy missing wings at existing quantities/expiry without resetting a cycle.

    Partial protection with inconsistent quantities is held for reconciliation.
    Do not infer a new position size or reuse another strategy's account netting.
    """
    result = []
    for short in legs:
        if short["side"] > 0:
            continue
        covered = protected_quantity(profile, short, legs)
        if covered >= short["quantity"]:
            continue
        if covered:
            raise DataUnavailable("Partial hedge quantity; reconcile the carried basket")
        candidates = [c for c in contracts if protects(profile, short, {**c, "side": 1})]
        if len(candidates) != 1:
            raise DataUnavailable("Required carried-position hedge is absent or ambiguous")
        contract = candidates[0]
        result.append({k: contract[k] for k in ("symbol", "expiry", "strike", "kind", "lot_size")})
        result[-1].update(side=1, quantity=short["quantity"], entry=None)
    return result


def stopped_spread_symbols(profile, legs, shorts):
    """Exit hit shorts plus only their matching long wings."""
    return [short["symbol"] for short in shorts] + [
        leg["symbol"] for leg in legs if any(protects(profile, short, leg) for short in shorts)
    ]
