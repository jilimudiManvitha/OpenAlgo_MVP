"""Direct Sandbox-only order adapter with persistent, uniquely tagged intents.

There is no live order-router import. A crash between dispatch and saving the
order ID is reconciled by the unique intent tag. A missing ambiguous order is
never resubmitted automatically.
"""

import hashlib
import math
import uuid
from datetime import datetime

from strategies.top_gain_volumes.coordination import dispatch_lock

from .engine import apply_close
from .hedges import protected_quantity
from .profiles import ROOT


def cleanup_sessions():
    from database.auth_db import db_session as auth
    from database.sandbox_db import db_session as sandbox
    from database.symbol import db_session as symbols

    for session in (sandbox, auth, symbols):
        session.remove()


class SandboxExecutor:
    def __init__(self, owner, profile, state, persist):
        self.owner, self.profile, self.state, self.persist = owner, profile, state, persist
        from sandbox.order_manager import OrderManager

        try:
            self.manager = OrderManager(owner)
        finally:
            cleanup_sessions()
        suffix = hashlib.sha256(owner.encode()).hexdigest()[:16]
        # Same lock as existing stock sandbox strategies, since funds are shared.
        self.lock = ROOT / "db" / ("four-sandbox-" + suffix + ".lock")

    def begin(self, action, legs, now):
        if self.state["pending"]:
            raise RuntimeError("Reconcile pending action before creating another")
        opening = action["action"] in {"open", "add_hedges"}
        if action["action"] == "add_hedges" and any(leg["side"] != 1 for leg in legs):
            raise ValueError("Hedge recovery may only buy protective options")
        if action.get("halt"):
            self.state["halted"] = True
        steps = []
        for leg in sorted(legs, key=lambda leg: -leg["side"] if opening else leg["side"]):
            steps.append(
                {
                    "leg": dict(leg),
                    "side": leg["side"] if opening else -leg["side"],
                    "tag": "Nifty12_" + uuid.uuid4().hex,
                    "status": "prepared",
                    "orderid": None,
                }
            )
        self.state["pending"] = {
            "action": action,
            "steps": steps,
            "created_at": now.isoformat(),
            "opening": opening,
            "initialized": False,
        }
        self.persist("intent", self.state["pending"])

    def advance(self, quotes, now):
        from database.sandbox_db import SandboxOrders, db_session
        from database.token_db import get_symbol_info
        from sandbox.execution_engine import quote_looks_stale

        pending = self.state["pending"]
        if not pending:
            return
        try:
            with dispatch_lock(self.lock):
                opening = pending["opening"]
                action = pending["action"]
                for step in pending["steps"]:
                    if step["status"] == "filled":
                        continue
                    leg = step["leg"]
                    existing = (
                        db_session.query(SandboxOrders)
                        .filter_by(user_id=self.owner, strategy=step["tag"])
                        .all()
                    )
                    if len(existing) > 1:
                        raise RuntimeError(
                            "Duplicate sandbox intent tag; manual reconciliation required"
                        )
                    if existing:
                        order = existing[0]
                        if order.symbol != leg["symbol"] or order.quantity != leg["quantity"]:
                            raise RuntimeError("Order intent identity mismatch")
                        step["orderid"] = order.orderid
                        if order.order_status in {"rejected", "cancelled"}:
                            self._abort(pending, "order_" + order.order_status, now)
                            return
                        if order.order_status != "complete":
                            self.persist("pending_order", {"orderid": order.orderid})
                            return
                        price = float(order.average_price or 0)
                        if (
                            order.filled_quantity != leg["quantity"]
                            or not math.isfinite(price)
                            or price <= 0
                        ):
                            raise RuntimeError("Invalid sandbox fill; reconcile manually")
                        self._fill(pending, step, price, now)
                        db_session.remove()
                        continue
                    if step["status"] != "prepared":
                        raise RuntimeError(
                            "Ambiguous dispatch without an order record; manual reconciliation required"
                        )
                    held = self.state["legs"]
                    if opening and held and all(leg["symbol"] in quotes for leg in held):
                        pnl = self.state["cycle_realized"] + sum(
                            (float(quotes[leg["symbol"]]["ltp"]) - leg["entry"])
                            * leg["side"]
                            * leg["quantity"]
                            for leg in held
                        )
                        if pnl <= -self.profile.loss_limit:
                            self._abort(pending, "capital_stop", now)
                            return
                    if opening and (
                        now.date() != datetime.fromisoformat(pending["created_at"]).date()
                        or (now - datetime.fromisoformat(pending["created_at"])).total_seconds()
                        > 60
                        or (
                            action.get("new_cycle", False)
                            and not pending["initialized"]
                            and now.strftime("%H:%M") >= "09:31"
                        )
                        or (action["action"] != "add_hedges" and now.strftime("%H:%M") >= "15:20")
                    ):
                        self._abort(pending, "stale_opening_intent", now)
                        return
                    if (
                        opening
                        and leg["side"] < 0
                        and protected_quantity(self.profile, leg, held) < leg["quantity"]
                    ):
                        self._abort(pending, "short_without_confirmed_hedge", now)
                        return
                    quote = quotes.get(leg["symbol"])
                    if not quote or quote_looks_stale(quote):
                        return
                    info = get_symbol_info(leg["symbol"], "NFO")
                    if not info or not info.lotsize or leg["quantity"] % int(info.lotsize) != 0:
                        raise RuntimeError("Live symbol master/lot-size validation failed")
                    step["status"] = "dispatching"
                    self.persist("dispatch", {"tag": step["tag"]})
                    ok, response, status = self.manager.place_order(
                        {
                            "symbol": leg["symbol"],
                            "exchange": "NFO",
                            "action": "BUY" if step["side"] > 0 else "SELL",
                            "quantity": leg["quantity"],
                            "price_type": "MARKET",
                            # The account-wide MIS engine exits at 15:15.
                            # Use NRML for this package; its own clock controls
                            # the user's 15:20 intraday exit and attribution.
                            "product": "NRML",
                            "strategy": step["tag"],
                        },
                        prefetched_quote=quote,
                    )
                    if not ok:
                        if status < 500:
                            step["status"] = "rejected"
                            self._abort(pending, "order_rejected", now)
                            return
                        self.persist("uncertain_dispatch", {"tag": step["tag"]})
                        return
                    if response.get("mode") != "analyze":
                        raise RuntimeError("Unexpected non-sandbox response")
                    step["orderid"] = response["orderid"]
                    step["status"] = "submitted"
                    self.persist("submitted", {"tag": step["tag"], "orderid": step["orderid"]})
                    return  # Reconcile the committed order before the next leg.
                self.state["pending"] = None
                if opening:
                    self.state["needs_reentry"] = False
                elif not self.state["legs"]:
                    self.state["needs_reentry"] = (
                        action.get("reenter", False) and not self.state["halted"]
                    )
                self.persist("action_complete", action)
        finally:
            cleanup_sessions()

    def _fill(self, pending, step, price, now):
        leg, action = step["leg"], pending["action"]
        if pending["opening"]:
            if not pending["initialized"] and action["action"] != "add_hedges":
                if action["new_cycle"]:
                    self.state.update(
                        cycle=self.state["cycle"] + 1,
                        cycle_realized=0.0,
                        halted=False,
                        cycle_start=now.isoformat(),
                    )
                self.state.update(
                    expiry=action["expiry"],
                    last_entry_day=now.date().isoformat(),
                    last_adjustment=now.isoformat(),
                )
                # Bind the quote to the actually started basket. Merely requesting
                # margin must not overwrite the prior cycle's executed evidence.
                self.state["capital_snapshot"] = action.get("capital_snapshot")
                pending["initialized"] = True
            if action["action"] == "add_hedges":
                pending["initialized"] = True
            self.state["legs"].append(
                {**leg, "entry": price, "entry_ts": now.isoformat(), "orderid": step["orderid"]}
            )
        else:
            trades = apply_close(
                self.state,
                {leg["symbol"]: (price, 0)},
                now,
                action["reason"],
                reenter=action.get("reenter", False),
                halt=action.get("halt", False),
            )
            self.state["pending"] = pending
            self.persist("trade", trades)
        step["status"] = "filled"
        self.persist("fill", {"tag": step["tag"], "price": price})

    def _abort(self, pending, reason, now):
        # Confirmed filled legs are already in state; cover all shorts before
        # selling hedges. A rejected close is held for reconciliation, not retried.
        if not pending["opening"]:
            self.persist("close_rejected", {"reason": reason})
            raise RuntimeError("Sandbox close rejected; positions persist for reconciliation")
        self.state["pending"] = None
        self.state["halted"] = True
        if pending["action"]["action"] != "add_hedges":
            self.state["last_entry_day"] = now.date().isoformat()
        self.state["expiry"] = pending["action"].get("expiry", self.state["expiry"])
        self.persist("opening_aborted", {"reason": reason})
        if self.state["legs"]:
            self.begin(
                {"action": "close_all", "reason": reason, "halt": True}, self.state["legs"], now
            )
