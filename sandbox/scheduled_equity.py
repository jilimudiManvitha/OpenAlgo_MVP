"""Bounded 15:15 close window for the bundled equity Sandbox runners.

Entry remains blocked at the normal MIS cutoff. Known strategy exit orders may
net against one another for 60 seconds before the account-wide safety square-off.
No permissions for arbitrary strategy tags or live broker orders are added.
"""

from datetime import time, timedelta

from sqlalchemy import func

from database.sandbox_db import SandboxOrders, db_session, ist_now
from strategies.short_equity.profiles import PROFILES as SHORTS
from strategies.top_gain_volumes.profiles import PROFILES as LONGS

ENTRY_SIDES = {
    **{"Four10K_" + p: "BUY" for p in LONGS},
    **{"Short10K_" + p: "SELL" for p in SHORTS},
}


def in_close_window(current_time, square_off_time):
    return square_off_time == time(15, 15) and time(15, 15) <= current_time < time(15, 16)


def is_exit(strategy, action):
    entry = ENTRY_SIDES.get(strategy)
    return entry is not None and action == ("SELL" if entry == "BUY" else "BUY")


def balances(owner, symbol):
    start = ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db_session.query(
            SandboxOrders.strategy,
            SandboxOrders.action,
            SandboxOrders.order_status,
            func.sum(SandboxOrders.filled_quantity),
            func.sum(SandboxOrders.pending_quantity),
        )
        .filter(
            SandboxOrders.user_id == owner,
            SandboxOrders.order_timestamp >= start,
            SandboxOrders.order_timestamp < start + timedelta(days=1),
            SandboxOrders.symbol == symbol,
            SandboxOrders.exchange == "NSE",
            SandboxOrders.product == "MIS",
            SandboxOrders.strategy.in_(ENTRY_SIDES),
        )
        .group_by(SandboxOrders.strategy, SandboxOrders.action, SandboxOrders.order_status)
        .all()
    )
    result = {}
    for strategy, action, status, filled, pending in rows:
        item = result.setdefault(strategy, [0, 0])
        item[0] += (filled or 0) * (1 if action == ENTRY_SIDES[strategy] else -1)
        if is_exit(strategy, action) and status in ("open", "trigger pending"):
            item[1] += pending or 0
    return result


def permits_exit(owner, symbol, strategy, action, quantity):
    if not is_exit(strategy, action):
        return False
    filled, reserved = balances(owner, symbol).get(strategy, (0, 0))
    return 0 < quantity <= filled - reserved


def has_exposure(owner, symbol):
    return any(filled > 0 for filled, _ in balances(owner, symbol).values())
