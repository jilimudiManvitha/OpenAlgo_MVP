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
        from database.sandbox_db import db_session
        from sandbox.order_manager import OrderManager

        try:
            self.manager = OrderManager(owner)
        finally:
            db_session.remove()
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
        with dispatch_lock(self.lock_path):
            return self._place_locked(trade, side, quote)

    def _place_locked(self, trade, side, quote):
        from database.auth_db import db_session as auth_session
        from database.sandbox_db import db_session as sandbox_session
        from database.symbol import db_session as symbol_session

        field = "entry_order" if side == "BUY" else "exit_order"
        trade[field + "_state"] = "dispatch_intent"
        started = time.perf_counter_ns()
        try:
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
                    raise RuntimeError(
                        "Uncertain Sandbox dispatch; inspect paper orders before restarting"
                    )
                return False
            if response.get("mode") != "analyze":
                raise RuntimeError("Unexpected non-Sandbox execution response")
            trade[field] = response["orderid"]
            self.persist()
            ok, response, _ = self.manager.get_order_status(trade[field])
            fill = response.get("data", {})
            if (
                not ok
                or fill.get("order_status") != "complete"
                or fill.get("filled_quantity") != trade["quantity"]
            ):
                trade[field + "_state"] = "unresolved"
                self.persist()
                raise RuntimeError("Sandbox fill is not complete; reconcile the saved order ID")
            price = float(fill["average_price"])
            if not math.isfinite(price) or price <= 0:
                raise RuntimeError("Invalid Sandbox fill price")
            trade[field + "_state"] = "complete"
            trade[field + "_latency_us"] = (time.perf_counter_ns() - started) / 1000
            return price
        finally:
            sandbox_session.remove()
            auth_session.remove()
            symbol_session.remove()

    def enter(self, trade, quote, tick):
        price_bound = max(float(quote["ltp"]), float(quote.get("ask") or 0))
        if not math.isfinite(price_bound) or price_bound <= trade["stop"]:
            return False
        trade["quantity"] = int(10000 // price_bound)
        if trade["quantity"] <= 0:
            return False
        price = self.place(trade, "BUY", quote)
        if price is False:
            return False
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
        return True

    def exit(self, trade, stamp, quote, reason):
        if time.monotonic() < trade.get("exit_retry_after", 0):
            return False
        price = self.place(trade, "SELL", quote)
        if price is False:
            trade["exit_retry_after"] = time.monotonic() + 1
            return False
        gross = (price - trade["entry"]) * trade["quantity"]
        trade.update(
            exit=price, exit_ts=stamp, reason=reason, gross_pnl=gross, net_pnl=gross, fees=0
        )
        self.persist()
        return True
