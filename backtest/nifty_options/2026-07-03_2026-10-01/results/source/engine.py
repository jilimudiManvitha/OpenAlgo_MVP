"""Causal basket decisions shared by historical replay and sandbox execution.

Pure decisions never imply fills. Executors acknowledge each fill and preserve
pending actions across crashes. A loss latch is set before exits are dispatched.
"""

import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .selection import DataUnavailable, select_expiry, select_legs
from .state import config_hash

IST = ZoneInfo("Asia/Kolkata")


def initial_state(profile, policy):
    return {
        "config_hash": config_hash(profile, policy),
        "legs": [],
        "pending": None,
        "cycle": 0,
        "cycle_realized": 0.0,
        "total_realized": 0.0,
        "fees": 0.0,
        "halted": False,
        "last_entry_day": None,
        "last_adjustment": None,
        "last_timestamp": None,
        "needs_reentry": False,
        "expiry": None,
        "cycle_start": None,
    }


def validate_state(state, profile, policy):
    if state["config_hash"] != config_hash(profile, policy):
        raise ValueError("Configuration changed; reconcile existing state before migration")


def marked_pnl(state, quotes):
    value = state["cycle_realized"]
    for leg in state["legs"]:
        if leg["symbol"] not in quotes:
            raise DataUnavailable("Missing price for held leg " + leg["symbol"])
        value += (quotes[leg["symbol"]].price - leg["entry"]) * leg["side"] * leg["quantity"]
    return value


def net_delta(legs, quotes, include_hedges=True):
    # Per basket lot, signed BUY deltas positive / SELL deltas negative.
    if not legs:
        return 0.0
    if any(
        quotes[leg["symbol"]].delta is None for leg in legs if include_hedges or leg["side"] < 0
    ):
        raise DataUnavailable("Greek unavailable for a held leg")
    quantity = legs[0]["quantity"]
    return sum(
        quotes[leg["symbol"]].delta * leg["side"] * leg["quantity"] / quantity
        for leg in legs
        if include_hedges or leg["side"] < 0
    )


def lots_for_margin(profile, policy, margin_per_lot, reserve_per_lot=0.0):
    if (
        any(not math.isfinite(v) or v < 0 for v in (margin_per_lot, reserve_per_lot))
        or margin_per_lot <= 0
    ):
        raise ValueError("A positive verified basket margin is required")
    affordable = int(profile.capital // (margin_per_lot + reserve_per_lot))
    lots = min(affordable, policy.lots) if policy.lots is not None else affordable
    if lots < 1:
        raise DataUnavailable("One complete lot does not fit strategy capital")
    return lots


def risk_decision(profile, policy, state, prices, timestamp):
    """Risk exits use actual prices; Greek solver availability cannot block exits."""
    now = timestamp.astimezone(IST)
    legs = state["legs"]
    if not legs or state["pending"]:
        return None
    day = now.date().isoformat()
    if state["halted"]:
        return {"action": "close_all", "reason": "capital_stop", "halt": True}
    if all(leg["symbol"] in prices for leg in legs):
        pnl = state["cycle_realized"] + sum(
            (prices[leg["symbol"]] - leg["entry"]) * leg["side"] * leg["quantity"] for leg in legs
        )
        if pnl <= -profile.loss_limit:
            return {"action": "close_all", "reason": "capital_stop", "halt": True}
    if not profile.positional and (
        now.time() >= time.fromisoformat(policy.intraday_exit) or day != state["last_entry_day"]
    ):
        return {"action": "close_all", "reason": "intraday_squareoff"}
    if profile.positional and (
        day > state["expiry"]
        or (day == state["expiry"] and now.time() >= time.fromisoformat(policy.positional_exit))
    ):
        return {"action": "close_all", "reason": "expiry_squareoff"}
    hit = [
        leg
        for leg in legs
        if leg["side"] < 0
        and profile.leg_stop_multiple
        and leg["symbol"] in prices
        and prices[leg["symbol"]] >= leg["entry"] * profile.leg_stop_multiple
    ]
    if hit:
        if profile.family == "iron_condor":
            return {"action": "close_all", "reason": "four_times_stop", "reenter": True}
        return {
            "action": "close_legs",
            "reason": "thirty_percent_stop",
            "symbols": [leg["symbol"] for leg in hit],
        }
    return None


def opening_plan(profile, policy, options, expiry, margin_per_lot, reserve_per_lot=0.0):
    selected = select_legs(profile, policy, options, expiry)
    lots = lots_for_margin(profile, policy, margin_per_lot, reserve_per_lot)
    legs = []
    for option, side in selected:
        legs.append(
            {
                "symbol": option.symbol,
                "expiry": expiry.isoformat(),
                "strike": option.strike,
                "kind": option.kind,
                "side": side,
                "quantity": lots * option.lot_size,
                "lot_size": option.lot_size,
                "entry": None,
            }
        )
    # Open hedges first; every SELL waits for confirmation of preceding BUY fills.
    return sorted(legs, key=lambda leg: -leg["side"])


def decision(profile, policy, state, options, timestamp, expiries):
    """Return an action; a caller must persist it before executing.

    Missing/incoherent held quotes abort the snapshot, never value a leg at zero.
    An expiry is fixed for the full positional cycle, including adjustments.
    """
    validate_state(state, profile, policy)
    if timestamp.tzinfo is None:
        raise ValueError("Timezone-aware event required")
    now = timestamp.astimezone(IST)
    if state["pending"]:
        return {"action": "resume"}
    quotes = {o.symbol: o for o in options}
    if len(quotes) != len(options) or any(o.timestamp != timestamp for o in options):
        raise DataUnavailable("Snapshot must be unique and synchronized")
    if state["last_timestamp"] and timestamp.isoformat() <= state["last_timestamp"]:
        return {"action": "wait", "reason": "duplicate_or_old_snapshot"}
    legs = state["legs"]
    day = now.date().isoformat()
    if legs:
        risk = risk_decision(
            profile, policy, state, {s: o.price for s, o in quotes.items()}, timestamp
        )
        if risk:
            return risk
        if profile.family == "premium" or now.time() >= time.fromisoformat(policy.reentry_cutoff):
            return {"action": "wait", "reason": "hold"}
        marked_pnl(state, quotes)  # Require a complete held-leg price snapshot.
        if profile.family != "premium":
            if (
                profile.family == "delta"
                and not profile.positional
                and policy.delta_trigger != "imbalance"
            ):
                if any(quotes[leg["symbol"]].delta is None for leg in legs if leg["side"] < 0):
                    raise DataUnavailable("Greek unavailable for a held short")
                short_deltas = [abs(quotes[leg["symbol"]].delta) for leg in legs if leg["side"] < 0]
                breached = (any if policy.delta_trigger == "either_050" else all)(
                    d >= 0.50 for d in short_deltas
                )
            else:
                breached = (
                    abs(net_delta(legs, quotes, policy.neutrality == "all_legs"))
                    >= policy.imbalance
                )
            last = (
                datetime.fromisoformat(state["last_adjustment"])
                if state["last_adjustment"]
                else None
            )
            cooled = (
                last is None
                or (timestamp - last).total_seconds() >= policy.adjustment_cooldown_seconds
            )
            if breached and cooled and now.time() < time.fromisoformat(policy.reentry_cutoff):
                return {"action": "close_all", "reason": "delta_adjustment", "reenter": True}
        return {"action": "wait", "reason": "hold"}
    # An unfilled adjustment must not strand an intraday strategy overnight,
    # or a positional strategy beyond its old expiry.
    reentry = bool(
        state["needs_reentry"]
        and not state["halted"]
        and day <= state["expiry"]
        and (profile.positional or day == state["last_entry_day"])
    )
    if reentry and state["cycle_realized"] <= -profile.loss_limit:
        return {"action": "latch", "reason": "capital_stop"}
    if state["halted"]:
        # Positional risk cannot be reset by a restart, an adjustment or midnight.
        if day == state["last_entry_day"] or (profile.positional and day <= state["expiry"]):
            return {"action": "wait", "reason": "loss_latched"}
    if now.weekday() >= 5 or now.time() < time(9, 30):
        return {"action": "wait", "reason": "outside_entry_session"}
    cutoff = time.fromisoformat(policy.reentry_cutoff) if reentry else time(9, 31)
    if now.time() >= cutoff:
        return {"action": "wait", "reason": "entry_window_closed"}
    if state["last_entry_day"] == day and not reentry:
        return {"action": "wait", "reason": "already_entered_today"}
    if reentry:
        from datetime import date

        expiry = date.fromisoformat(state["expiry"])
        if expiry < now.date():
            return {"action": "wait", "reason": "expired_reentry"}
    else:
        expiry = select_expiry(now.date(), expiries, profile.expiry)
    return {"action": "open", "expiry": expiry.isoformat(), "new_cycle": not reentry}


def apply_open(state, profile, legs, fills, timestamp, expiry, new_cycle):
    """Apply confirmed fills only (simulation batches are transactional)."""
    if new_cycle:
        state.update(
            cycle=state["cycle"] + 1,
            cycle_realized=0.0,
            halted=False,
            cycle_start=timestamp.isoformat(),
        )
    state["legs"] = [
        {
            **leg,
            "entry": fills[leg["symbol"]][0],
            "entry_fee": fills[leg["symbol"]][1],
            "entry_ts": timestamp.isoformat(),
        }
        for leg in legs
    ]
    cost = sum(fills[leg["symbol"]][1] for leg in legs)
    state["cycle_realized"] -= cost
    state["total_realized"] -= cost
    state["fees"] += cost
    state.update(
        expiry=expiry,
        last_entry_day=timestamp.astimezone(IST).date().isoformat(),
        last_adjustment=timestamp.isoformat(),
        needs_reentry=False,
        pending=None,
    )


def apply_close(state, fills, timestamp, reason, reenter=False, halt=False):
    trades = []
    for leg in list(state["legs"]):
        if leg["symbol"] not in fills:
            continue
        price, fees = fills[leg["symbol"]]
        gross = (price - leg["entry"]) * leg["side"] * leg["quantity"]
        state["cycle_realized"] += gross - fees
        state["total_realized"] += gross - fees
        state["fees"] += fees
        trades.append(
            {
                **leg,
                "exit": price,
                "exit_ts": timestamp.isoformat(),
                "gross_pnl": gross,
                "exit_fee": fees,
                "reason": reason,
                "cycle": state["cycle"],
            }
        )
        state["legs"].remove(leg)
    state["halted"] = state["halted"] or halt
    if not state["legs"]:
        state["needs_reentry"] = reenter and not state["halted"]
    state["pending"] = None
    return trades
