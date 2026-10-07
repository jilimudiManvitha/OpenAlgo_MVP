"""Read-only, owner-scoped daily journal over existing strategy snapshots."""

import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from services.report_brokerage import COMPONENTS, estimate_report
from services.scanner_strategy_reports import metrics

IST = ZoneInfo("Asia/Kolkata")


def day_metrics(trades, day):
    start = datetime.combine(date.fromisoformat(day), time(), IST).timestamp()
    end = start + timedelta(days=1).total_seconds()
    # Ignore unconfirmed stock entry orders. Option report producers already
    # include only confirmed fills and do not set entry_order_state.
    trades = [t for t in trades if t.get("entry_order_state", "complete") == "complete"]
    realized = [t for t in trades if t.get("exit_ts") is not None and start <= t["exit_ts"] < end]
    active = [
        t
        for t in trades
        if t["entry_ts"] < end and (t.get("exit_ts") is None or t["exit_ts"] >= start)
    ]
    clipped = [{**t, "entry_ts": max(start, t["entry_ts"])} for t in active]
    result = metrics(clipped)
    result.update(
        trades=len(realized),
        total_trades=len(active),
        entries=sum(start <= t["entry_ts"] < end for t in active),
        open_trades=sum(t.get("exit_ts") is None or t["exit_ts"] >= end for t in active),
        wins=sum(t["net_pnl"] > 0 for t in realized),
        losses=sum(t["net_pnl"] < 0 for t in realized),
        breakeven=sum(t["net_pnl"] == 0 for t in realized),
        gross_pnl=sum(t["gross_pnl"] for t in realized),
        net_pnl=sum(t["net_pnl"] for t in realized),
        # Realized round-trip charges; open-position fees are excluded, as is
        # unrealized P&L. Avoid repeating entry fees on carried daily snapshots.
        charges=sum(t["fees"] for t in realized),
        win_rate=100 * sum(t["net_pnl"] > 0 for t in realized) / len(realized) if realized else 0,
    )
    breakdown_known = all("charge_breakdown" in t for t in realized)
    result["brokerage"] = (
        sum(t.get("charge_breakdown", {}).get("brokerage", 0) for t in realized)
        if breakdown_known
        else None
    )
    result["charge_breakdown"] = (
        {k: sum(t.get("charge_breakdown", {}).get(k, 0) for t in realized) for k in COMPONENTS}
        if breakdown_known
        else {}
    )
    result["open_entry_charges"] = sum(
        t.get("entry_estimated_fees", 0) for t in active if t.get("exit_ts") is None
    )
    result["unestimated_trades"] = sum(t.get("charge_status") == "unavailable" for t in realized)
    if result["unestimated_trades"]:
        for key in ("net_pnl", "charges", "brokerage", "wins", "losses", "breakeven", "win_rate"):
            result[key] = None
    return result


def streaks(days):
    best_win = best_loss = run = 0
    for day in sorted(days, key=lambda d: d["day"]):
        m = day["metrics"]
        if not m["trades"]:
            continue
        if m["net_pnl"] is None:
            run = 0
            continue
        sign = 1 if m["net_pnl"] > 0 else -1 if m["net_pnl"] < 0 else 0
        run = run + sign if run * sign > 0 else sign
        best_win, best_loss = max(best_win, run), max(best_loss, -run)
    return {"winning": best_win, "losing": best_loss, "current": run}


def journal(
    owner,
    year,
    scenario="PAPER",
    strategy="",
    symbol="",
    path="db/scanner_strategy_reports.db",
    session_broker="",
    charge_basis="recorded",
    extra_reports=(),
):
    """One financial year; stream candle-free payloads, never create/migrate a DB."""
    if not 2000 <= year <= 2100:
        raise ValueError("Financial year must be between 2000 and 2100.")
    if scenario not in ("PAPER", "LIVE", "OLHC", "OHLC"):
        raise ValueError("Unknown execution scenario.")
    if charge_basis not in ("recorded", "estimated"):
        raise ValueError("Unknown charges basis.")
    charge_infos = {}
    start, end = f"{year}-04-01", f"{year + 1}-04-01"
    grouped = defaultdict(list)
    strategies, symbols = {}, set()

    def saved_reports():
        db_path = Path(path).resolve()
        if db_path.is_file():
            with closing(
                sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5)
            ) as conn:
                rows = conn.execute(
                    "SELECT day,json_remove(payload,'$.candles','$.coverage') FROM reports "
                    "WHERE owner=? AND day>=? AND day<? ORDER BY day,id",
                    (owner, start, end),
                )
                for day, payload in rows:
                    yield day, json.loads(payload)
        for report in extra_reports:
            if start <= report["day"] < end:
                yield report["day"], report

    for day, report in saved_reports():
        if scenario not in report["paths"]:
            continue
        report = estimate_report(report, session_broker, charge_basis)
        info = report["charge_info"]
        charge_infos[(info["broker"], info["version"], info["broker_inferred"])] = info
        sid = report.get("strategy_id") or report["id"].replace(day, "session")
        name = report.get("kind", sid)
        strategies[sid] = name
        trades = [t for t in report["trades"] if t["path"] == scenario]
        symbols.update(t["symbol"] for t in trades)
        if strategy and sid != strategy:
            continue
        if symbol:
            trades = [t for t in trades if t["symbol"] == symbol]
            if not trades:
                continue
        grouped[day].append(
            {
                "id": report["id"],
                "strategy_id": sid,
                "name": name,
                "status": report["status"],
                "note": report.get("note", ""),
                "trades": trades,
                "charge_info": info,
            }
        )
    days = []
    for day, reports in sorted(grouped.items(), reverse=True):
        combined = []
        by_strategy = defaultdict(list)
        for report in reports:
            by_strategy[report["strategy_id"]].append(report)
        summaries = []
        for sid, sessions in by_strategy.items():
            trades = [t for s in sessions for t in s["trades"]]
            combined.extend(trades)
            by_stock = defaultdict(list)
            for trade in trades:
                by_stock[trade["symbol"]].append(trade)
            summaries.append(
                {
                    "strategy_id": sid,
                    "name": strategies[sid],
                    "reports": [
                        {k: s[k] for k in ("id", "status", "note", "charge_info")} for s in sessions
                    ],
                    "metrics": day_metrics(trades, day),
                    "stocks": [
                        {"symbol": stock, "metrics": day_metrics(ts, day)}
                        for stock, ts in sorted(by_stock.items())
                    ],
                }
            )
        stocks = defaultdict(list)
        for t in combined:
            stocks[t["symbol"]].append(t)
        days.append(
            {
                "day": day,
                "metrics": day_metrics(combined, day),
                "strategies": summaries,
                "stocks": [
                    {"symbol": s, "metrics": day_metrics(ts, day)}
                    for s, ts in sorted(stocks.items())
                ],
            }
        )
    totals = {
        k: sum(d["metrics"][k] for d in days)
        if all(d["metrics"][k] is not None for d in days)
        else None
        for k in (
            "gross_pnl",
            "net_pnl",
            "charges",
            "brokerage",
            "unestimated_trades",
            "trades",
            "entries",
            "wins",
            "losses",
            "breakeven",
        )
    }
    totals["peak_capital"] = max((d["metrics"]["peak_capital"] for d in days), default=0)
    return {
        "year": year,
        "scenario": scenario,
        "days": days,
        "totals": totals,
        "streaks": streaks(days),
        "strategies": [{"id": sid, "name": name} for sid, name in sorted(strategies.items())],
        "symbols": sorted(symbols),
        "charge_basis": charge_basis,
        "session_broker": session_broker,
        "charge_profiles": list(charge_infos.values()),
    }


def journal_detail(
    owner,
    report_id,
    session_broker="",
    charge_basis="estimated",
    path="db/scanner_strategy_reports.db",
):
    if charge_basis not in ("recorded", "estimated"):
        raise ValueError("Unknown charges basis.")
    if report_id.startswith("sm-"):
        from services.report_strategy_runs import detail

        raw = detail(owner, report_id)
    else:
        db_path = Path(path).resolve()
        if not db_path.is_file():
            return None
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            row = conn.execute(
                "SELECT payload FROM reports WHERE owner=? AND id=?", (owner, report_id)
            ).fetchone()
        raw = json.loads(row[0]) if row else None
    if raw is None:
        return None
    report = estimate_report(raw, session_broker, charge_basis)
    report["metrics"] = {
        p: day_metrics([t for t in report["trades"] if t["path"] == p], report["day"])
        for p in report["paths"]
    }
    return report
