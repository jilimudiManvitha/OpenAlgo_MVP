"""Daily scheduled Sandbox reports, separate from all historical replay outputs."""

from datetime import datetime

from services.scanner_strategy_reports import ReportStore


def trade_row(leg):
    closed = leg.get("exit_ts") is not None
    fee = float(leg.get("entry_fee", 0)) + float(leg.get("exit_fee", 0))
    gross = float(leg.get("gross_pnl", 0))
    return {
        **leg,
        "path": "PAPER",
        "signal_ts": datetime.fromisoformat(leg["entry_ts"]).timestamp(),
        "entry_ts": datetime.fromisoformat(leg["entry_ts"]).timestamp(),
        "exit_ts": datetime.fromisoformat(leg["exit_ts"]).timestamp() if closed else None,
        "exit": leg.get("exit"),
        "stop": None,
        "target": None,
        "fees": fee,
        "gross_pnl": gross,
        "net_pnl": gross - fee if closed else 0,
        "entry_order": leg.get("orderid"),
        "reason": ("SHORT · " if leg["side"] < 0 else "LONG · ")
        + leg.get("reason", "Open position; unrealized P&L not included"),
    }


class DailyReport:
    def __init__(self, owner, profile, day, state_store, path=None):
        self.owner, self.profile, self.day = owner, profile, day
        self.state_store = state_store
        self.store = ReportStore(path) if path is not None else ReportStore()

    def save(self, state, status, now, feed=None):
        closed = self.state_store.closed_trades(self.owner, self.profile.name, self.day)
        report = {
            "id": f"paper-{self.day}-nifty-options-{self.profile.name}",
            "day": str(self.day),
            "kind": "Sandbox · NIFTY · " + self.profile.name.replace("_", " "),
            "strategy_id": self.profile.name,
            "status": status,
            "updated_at": now.isoformat(),
            "paths": ["PAPER"],
            "trades": [trade_row(leg) for leg in closed + state["legs"]],
            "candles": {},
            "coverage": [],
            "pending_action": bool(state["pending"]),
            "streaming_symbols": len(feed.accepted) if feed else 0,
            "capital_snapshot": state.get("capital_snapshot"),
            "capital_allocation": self.profile.capital,
            "note": (
                "Scheduled NIFTY Sandbox session. Confirmed fills only; no backtest trades. "
                "P&L counts full leg profit realized on this date, including carried positions; "
                "not daily mark-to-market. Open-leg unrealized P&L and brokerage are excluded. "
                "Trade/win statistics count legs, not baskets. Capital metrics measure premium "
                "turnover, not option margin; strategy allocation is ₹20 lakh."
            ),
        }
        self.store.save(self.owner, report)
        return report

    def close(self):
        self.store.close()
