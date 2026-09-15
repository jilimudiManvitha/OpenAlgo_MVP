"""Bounded per-day portfolio accumulation and exact cross-day drawdown folding."""

import calendar
from datetime import date, datetime, timedelta

import numpy as np

from .source import bounds


def microseconds(stamp):
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    return round(stamp.timestamp() * 1_000_000)


class DayAccumulator:
    def __init__(self, day):
        self.day = day
        start, end = bounds(day)
        self.start = start
        self.minute_times = [start + timedelta(minutes=i) for i in range(376)]
        self.ticks = sorted(
            {
                microseconds(start + timedelta(minutes=m, seconds=i / 9 * 59.999))
                for m in range(375)
                for i in range(10)
            }
            | {microseconds(end)}
        )
        self.index = {stamp: i for i, stamp in enumerate(self.ticks)}
        self.capital_delta = np.zeros(len(self.ticks))
        self.open_delta = np.zeros(len(self.ticks), dtype=np.int32)
        self.equity = np.zeros(376)
        self.sums = dict.fromkeys(
            (
                "net_pnl",
                "gross_pnl",
                "fees",
                "brokerage",
                "slippage_cost",
                "winning_pnl",
                "losing_pnl",
                "entry_notional",
                "turnover",
            ),
            0.0,
        )
        self.trades = self.orders = self.wins = self.losses = self.rejected = (
            self.symbols_traded
        ) = 0
        self.best = self.worst = None

    def add(self, trades, marks, rejected=0):
        self.rejected += rejected
        self.symbols_traded += bool(trades)
        values = {microseconds(t): p for t, p in marks}
        last = 0.0
        for i, when in enumerate(self.minute_times):
            last = values.get(microseconds(when), last)
            self.equity[i] += last
        for t in trades:
            self.trades += 1
            self.wins += t["net_pnl"] > 0
            self.losses += t["net_pnl"] < 0
            for key in ("net_pnl", "gross_pnl", "fees", "slippage_cost"):
                self.sums[key] += t[key]
            self.sums["winning_pnl"] += max(0, t["net_pnl"])
            self.sums["losing_pnl"] += min(0, t["net_pnl"])
            self.sums["entry_notional"] += t["quantity"] * t["entry_price"]
            if t["net_pnl"] > 0 and (self.best is None or t["net_pnl"] > self.best["net_pnl"]):
                self.best = t
            if t["net_pnl"] < 0 and (self.worst is None or t["net_pnl"] < self.worst["net_pnl"]):
                self.worst = t
            for i, f in enumerate(t["fills"]):
                index = self.index[microseconds(f["time"])]
                entry = f["reason"] == "entry"
                self.capital_delta[index] += (1 if entry else -1) * f["quantity"] * t["entry_price"]
                self.open_delta[index] += 1 if entry else (-1 if i == len(t["fills"]) - 1 else 0)
                self.sums["brokerage"] += f["costs"]["brokerage"]
                self.sums["turnover"] += f["quantity"] * f["price"]
                self.orders += 1

    def finish(self):
        self.equity[-1] = self.sums["net_pnl"]
        capital = np.cumsum(self.capital_delta)
        counts = np.cumsum(self.open_delta)
        if abs(capital[-1]) > 1e-5 or counts[-1] != 0 or counts.min() < 0 or capital.min() < -1e-5:
            raise AssertionError("Unbalanced daily capital/concurrency")
        capital[np.abs(capital) < 1e-6] = 0
        dd = np.maximum.accumulate(self.equity) - self.equity
        trough = int(np.argmax(dd))
        peak = int(np.argmax(self.equity[: trough + 1]))
        cap_index, count_index = int(np.argmax(capital)), int(np.argmax(counts))
        duration = np.diff(self.ticks) / 1e6

        def tick_time(index):
            return datetime.fromtimestamp(self.ticks[index] / 1e6, self.start.tzinfo).isoformat()

        row = {
            "day": self.day,
            **self.sums,
            "trades": self.trades,
            "filled_orders": self.orders,
            "wins": self.wins,
            "losses": self.losses,
            "rejected_entries": self.rejected,
            "symbols_traded": self.symbols_traded,
            "peak_capital": float(capital[cap_index]),
            "peak_capital_time": tick_time(cap_index),
            "max_open_trades": int(counts[count_index]),
            "max_open_trades_time": tick_time(count_index),
            "capital_seconds": float(np.dot(capital[:-1], duration)),
            "open_trade_seconds": float(np.dot(counts[:-1], duration)),
            "session_seconds": 22500,
            "max_drawdown": float(dd[trough]),
            "drawdown_peak_time": self.minute_times[peak].isoformat(),
            "drawdown_trough_time": self.minute_times[trough].isoformat(),
            "session_peak": float(self.equity.max()),
            "session_peak_time": self.minute_times[int(np.argmax(self.equity))].isoformat(),
            "session_trough": float(self.equity.min()),
            "session_trough_time": self.minute_times[int(np.argmin(self.equity))].isoformat(),
            "max_win": self.best["net_pnl"] if self.best else 0,
            "max_win_id": self.best["id"] if self.best else None,
            "max_loss": self.worst["net_pnl"] if self.worst else 0,
            "max_loss_id": self.worst["id"] if self.worst else None,
        }
        series = []
        for i, when in enumerate(self.minute_times):
            index = self.index[microseconds(when)]
            series.append(
                [
                    when.isoformat(),
                    float(self.equity[i]),
                    float(capital[index]),
                    int(counts[index]),
                    float(dd[i]),
                ]
            )
        return row, series


def period(day, grouping, anchor=2017):
    d = date.fromisoformat(day)
    if grouping == "day":
        start, end = d, d
    elif grouping == "week":
        start = d - timedelta(days=d.weekday())
        end = start + timedelta(days=6)
    elif grouping in {"month", "quarter", "half_year"}:
        size = {"month": 1, "quarter": 3, "half_year": 6}[grouping]
        month = (d.month - 1) // size * size + 1
        start = date(d.year, month, 1)
        last_month = month + size - 1
        end = date(d.year, last_month, calendar.monthrange(d.year, last_month)[1])
    elif grouping in {"year", "five_year"}:
        year = d.year if grouping == "year" else anchor + (d.year - anchor) // 5 * 5
        start, end = date(year, 1, 1), date(year + (4 if grouping == "five_year" else 0), 12, 31)
    elif grouping == "all":
        return "All data", "0001-01-01", "9999-12-31"
    else:
        raise ValueError("Unknown calendar grouping")
    label = start.isoformat() if grouping == "day" else f"{start.isoformat()} – {end.isoformat()}"
    return label, start.isoformat(), end.isoformat()


def combine(days, capital_reference):
    """Use intraday extrema plus each day's internal DD; never max(daily DD) alone."""
    cumulative = high = max_dd = 0.0
    peak_time = days[0]["day"] + "T09:15:00+05:30" if days else None
    dd_peak = dd_trough = peak_time
    result = {
        k: sum(r[k] for r in days)
        for k in (
            "net_pnl",
            "gross_pnl",
            "fees",
            "brokerage",
            "slippage_cost",
            "winning_pnl",
            "losing_pnl",
            "entry_notional",
            "turnover",
            "trades",
            "filled_orders",
            "wins",
            "losses",
            "capital_seconds",
            "open_trade_seconds",
            "session_seconds",
            "rejected_entries",
        )
    }
    for r in days:
        cross_dd = high - (cumulative + r["session_trough"])
        if cross_dd > max_dd:
            max_dd, dd_peak, dd_trough = cross_dd, peak_time, r["session_trough_time"]
        if r["max_drawdown"] > max_dd:
            max_dd, dd_peak, dd_trough = (
                r["max_drawdown"],
                r["drawdown_peak_time"],
                r["drawdown_trough_time"],
            )
        if cumulative + r["session_peak"] > high:
            high, peak_time = cumulative + r["session_peak"], r["session_peak_time"]
        cumulative += r["net_pnl"]
    best = max(days, key=lambda r: r["max_win"], default={})
    worst = min(days, key=lambda r: r["max_loss"], default={})
    cap = max(days, key=lambda r: r["peak_capital"], default={})
    count = max(days, key=lambda r: r["max_open_trades"], default={})
    result.update(
        days=len(days),
        allocated_capital=capital_reference,
        max_drawdown=max_dd,
        drawdown_peak_time=dd_peak,
        drawdown_trough_time=dd_trough,
        max_win=best.get("max_win", 0),
        max_win_id=best.get("max_win_id"),
        max_loss=worst.get("max_loss", 0),
        max_loss_id=worst.get("max_loss_id"),
        peak_capital=cap.get("peak_capital", 0),
        peak_capital_time=cap.get("peak_capital_time"),
        max_open_trades=count.get("max_open_trades", 0),
        max_open_trades_time=count.get("max_open_trades_time"),
        average_capital=result["capital_seconds"] / result["session_seconds"]
        if result["session_seconds"]
        else 0,
        average_open_trades=result["open_trade_seconds"] / result["session_seconds"]
        if result["session_seconds"]
        else 0,
        average_trade_pnl=result["net_pnl"] / result["trades"] if result["trades"] else None,
        average_win=result["winning_pnl"] / result["wins"] if result["wins"] else None,
        average_loss=result["losing_pnl"] / result["losses"] if result["losses"] else None,
        win_rate=100 * result["wins"] / result["trades"] if result["trades"] else None,
        profit_factor=result["winning_pnl"] / -result["losing_pnl"]
        if result["losing_pnl"]
        else None,
        profit_factor_status="finite"
        if result["losing_pnl"]
        else ("no_losses" if result["wins"] else "no_trades"),
        return_pct=100 * result["net_pnl"] / capital_reference if capital_reference else None,
    )
    return result
