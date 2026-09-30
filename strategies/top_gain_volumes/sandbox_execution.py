"""Authenticated, direct Sandbox-only execution using an already validated tick.

No live order router and no global Analyzer-mode change. Every intent is persisted
before dispatch; an uncertain response must be reconciled, never retried blindly.
"""

import hashlib
import math
import time

from strategies.top_gain_volumes.coordination import dispatch_lock
from strategies.top_gain_volumes.profiles import ROOT


class SandboxExecution:
    def __init__(self, owner, strategy, persist):
        from database.auth_db import db_session as auth_session
        from database.sandbox_db import db_session
        from database.symbol import db_session as symbol_session
        from sandbox.order_manager import OrderManager

        try:
            self.manager = OrderManager(owner)
        finally:
            db_session.remove()
            auth_session.remove()
            symbol_session.remove()
        self.strategy = "Four10K_" + strategy
        self.persist = persist
        self.lock_path = (
            ROOT
            / "db"
            / ("four-sandbox-" + hashlib.sha256(owner.encode()).hexdigest()[:16] + ".lock")
        )

    def place(self, trade, side, quote):
        # Sandbox positions/funds are shared by user, not strategy. Its existing
        # in-process lock alone cannot serialize four independent Python jobs.
        try:
            with dispatch_lock(self.lock_path):
                return self._place_locked(trade, side, quote)
        except TimeoutError:
            # No dispatch happened when acquisition timed out. Existing pending
            # orders still belong to this strategy and may never be duplicated.
            field = "entry_order" if side == "BUY" else "exit_order"
            return None if trade.get(field) or trade.get(field + "_state") == "uncertain" else False

    def _read_fill(self, trade, field):
        """None=pending/unknown, False=terminal unfilled, float=confirmed fill."""
        if not trade.get(field):
            return None
        ok, response, _ = self.manager.get_order_status(trade[field])
        fill = response.get("data", {})
        if not ok:
            return None
        if fill.get("order_status") in ("cancelled", "rejected") and not fill.get(
            "filled_quantity"
        ):
            trade[field + "_state"] = fill["order_status"]
            return False
        if (
            fill.get("order_status") != "complete"
            or fill.get("filled_quantity") != trade["quantity"]
        ):
            trade[field + "_state"] = "pending"
            return None
        price = float(fill["average_price"])
        if not math.isfinite(price) or price <= 0:
            trade[field + "_state"] = "uncertain"
            return None
        trade[field + "_state"] = "complete"
        return price

    def _place_locked(self, trade, side, quote):
        from database.auth_db import db_session as auth_session
        from database.sandbox_db import db_session as sandbox_session
        from database.symbol import db_session as symbol_session

        field = "entry_order" if side == "BUY" else "exit_order"
        started = time.perf_counter_ns()
        try:
            if trade.get(field + "_state") in (
                "pending",
                "uncertain",
                "dispatch_intent",
                "complete",
            ):
                return self._read_fill(trade, field)
            trade[field + "_state"] = "dispatch_intent"
            self.persist()
            ok, response, status = self.manager.place_order(
                {
                    "symbol": trade["symbol"],
                    "exchange": "NSE",
                    "action": side,
                    "quantity": trade["quantity"],
                    "price_type": "MARKET",
                    "product": "MIS",
                    "strategy": self.strategy,
                },
                prefetched_quote=quote,
            )
            if not ok:
                trade[field + "_state"] = "rejected" if status < 500 else "uncertain"
                self.persist()
                if status >= 500:
                    return None  # Disable fresh entries, continue managing other positions.
                return False
            if response.get("mode") != "analyze":
                raise RuntimeError("Unexpected non-Sandbox execution response")
            trade[field] = response["orderid"]
            self.persist()
            trade[field + "_state"] = "pending"
            price = self._read_fill(trade, field)
            trade[field + "_latency_us"] = (time.perf_counter_ns() - started) / 1000
            self.persist()
            return price
        finally:
            sandbox_session.remove()
            auth_session.remove()
            symbol_session.remove()

    def enter(self, trade, quote, tick):
        from sandbox.execution_engine import quote_looks_stale

        # Preserve the Sandbox's stale-price guard. Wait for a coherent quote
        # instead of knowingly submitting an order that cannot fill immediately.
        if quote_looks_stale(quote):
            return False
        price_bound = max(float(quote["ltp"]), float(quote.get("ask") or 0))
        if not math.isfinite(price_bound) or price_bound <= trade["stop"]:
            return False
        trade["quantity"] = int(10000 // price_bound)
        if trade["quantity"] <= 0:
            return False
        trade["entry_tick"] = tick
        price = self.place(trade, "BUY", quote)
        if price is False:
            return False
        if price is None:
            trade["reason"] = "ENTRY_PENDING"
            self.persist()
            return True  # Accepted intent: retain and poll this exact order ID.
        self._entry_filled(trade, price)
        return True

    def _entry_filled(self, trade, price):
        tick = trade["entry_tick"]
        trade.update(
            entry=price,
            target=math.ceil((price + 3 * (price - trade["stop"])) / tick - 1e-9) * tick,
            fees=0,
            gross_pnl=0,
            net_pnl=0,
            reason="OPEN",
            fee_basis="Sandbox does not book brokerage; charges excluded",
        )
        self.persist()

    def exit(self, trade, stamp, quote, reason):
        from sandbox.execution_engine import quote_looks_stale

        if trade.get("entry_order_state") != "complete":
            return False
        if quote_looks_stale(quote):
            return False
        if time.monotonic() < trade.get("exit_retry_after", 0):
            return False
        trade["exit_requested_at"] = stamp
        trade["exit_reason"] = reason
        price = self.place(trade, "SELL", quote)
        if price is False:
            trade["exit_retry_after"] = time.monotonic() + 1
            return False
        if price is None:
            self.persist()
            return False
        self._exit_filled(trade, price, stamp)
        return True

    def _exit_filled(self, trade, price, stamp):
        gross = (price - trade["entry"]) * trade["quantity"]
        trade.update(
            exit=price,
            exit_ts=stamp,
            reason=trade["exit_reason"],
            gross_pnl=gross,
            net_pnl=gross,
            fees=0,
        )
        self.persist()

    def reconcile(self, trade, stamp, cancel_entry=False):
        """Poll known orders without new dispatch; keep filled positions managed."""
        from database.auth_db import db_session as auth_session
        from database.sandbox_db import db_session
        from database.symbol import db_session as symbol_session

        try:
            with dispatch_lock(self.lock_path):
                if trade.get("entry_order_state") != "complete":
                    price = self._read_fill(trade, "entry_order")
                    if price is None and cancel_entry and trade.get("entry_order"):
                        self.manager.cancel_order(trade["entry_order"])
                        db_session.remove()
                        price = self._read_fill(trade, "entry_order")
                    if price is False:
                        self.persist()
                        return "rejected"
                    if price is None:
                        return "pending"
                    self._entry_filled(trade, price)
                if trade.get("exit_order") and trade.get("exit_order_state") != "complete":
                    price = self._read_fill(trade, "exit_order")
                    if price is not None and price is not False:
                        self._exit_filled(trade, price, stamp)
                        return "closed"
                return "open"
        except TimeoutError:
            return "pending"
        finally:
            db_session.remove()
            auth_session.remove()
            symbol_session.remove()
