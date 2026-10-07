"""Read-only daily reports from mode-labelled Strategy Builder execution records.

Never infer a strategy from a broker's net position or the legacy unlabelled book.
Each order contributes only its persisted confirmed fill quantity/average price.
"""

import math
import os
import re
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from services.report_brokerage import IST


def database_path():
    url = make_url(os.environ.get("DATABASE_URL", "sqlite:///db/openalgo.db"))
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def stamp(value):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC).timestamp() if parsed.tzinfo is None else parsed.timestamp()


def fold(rows, scenario):
    """Match by run/leg/position/instrument, including shorts and partial exits."""
    lots = defaultdict(deque)
    trades = []
    for row in rows:
        qty, price = float(row["filled_qty"]), float(row["avg_fill_price"])
        if (
            not math.isfinite(qty)
            or not math.isfinite(price)
            or qty <= 0
            or price <= 0
            or not row["filled_at"]
            or row["action"] not in ("BUY", "SELL")
        ):
            raise ValueError("Strategy fill metadata is incomplete; report unavailable.")
        side = 1 if row["action"] == "BUY" else -1
        ts = stamp(row["filled_at"])
        key = (row["leg_id"], row["position_ref"], row["symbol"], row["exchange"], row["product"])
        queue = lots[key]
        if row["kind"] == "entry":
            if queue and queue[0]["side"] != side:
                raise ValueError("Overlapping strategy entries have ambiguous ownership.")
        elif not queue or queue[0]["side"] == side or qty > sum(lot["quantity"] for lot in queue):
            raise ValueError("Strategy exit cannot be matched to confirmed owned entries.")
        while qty and queue and queue[0]["side"] != side:
            entry = queue[0]
            matched = min(qty, entry["quantity"])
            gross = (price - entry["entry"]) * matched * entry["side"]
            trades.append(
                {
                    **entry,
                    "quantity": matched,
                    "exit": price,
                    "exit_ts": ts,
                    "exit_order": str(row["broker_order_id"] or f"sm-{row['id']}"),
                    "gross_pnl": gross,
                    "net_pnl": gross,
                    "reason": "Confirmed matched fills",
                }
            )
            qty -= matched
            entry["quantity"] -= matched
            if entry["quantity"] == 0:
                queue.popleft()
        if qty:
            queue.append(
                {
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "product": row["product"],
                    "path": scenario,
                    "side": side,
                    "quantity": qty,
                    "entry": price,
                    "entry_ts": ts,
                    "entry_order": str(row["broker_order_id"] or f"sm-{row['id']}"),
                    "exit": None,
                    "exit_ts": None,
                    "gross_pnl": 0,
                    "net_pnl": 0,
                    "fees": 0,
                    "stop": None,
                    "target": None,
                    "reason": "Open confirmed fill",
                }
            )
    return trades + [trade for queue in lots.values() for trade in queue]


def reports(owner, year, scenario, path=None, run_id=None):
    if scenario not in ("LIVE", "PAPER"):
        return []
    path = Path(path).resolve() if path else database_path()
    if path is None or not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"sm_strategy", "sm_strategy_run", "sm_strategy_order"}.issubset(tables):
            return []
        start = datetime(year, 4, 1, tzinfo=IST).astimezone(UTC).replace(tzinfo=None).isoformat(" ")
        end = (
            datetime(year + 1, 4, 1, tzinfo=IST).astimezone(UTC).replace(tzinfo=None).isoformat(" ")
        )
        params = [owner, "live" if scenario == "LIVE" else "sandbox", start, end, end]
        where = " AND r.id=?" if run_id is not None else ""
        if run_id is not None:
            params.append(run_id)
        # Include pre-year entries to retain cost basis on carried positions.
        rows = conn.execute(
            "SELECT o.*, r.broker, r.strategy_id, r.stopped_at, s.name AS strategy_name "
            "FROM sm_strategy_order o JOIN sm_strategy_run r ON o.run_id=r.id "
            "JOIN sm_strategy s ON r.strategy_id=s.id "
            "WHERE s.user_id=? AND r.mode=? AND o.filled_qty>0"
            " AND EXISTS (SELECT 1 FROM sm_strategy_order recent WHERE recent.run_id=r.id"
            " AND recent.filled_qty>0 AND recent.filled_at>=? AND recent.filled_at<?)"
            " AND (o.filled_at<? OR o.filled_at IS NULL)"
            + where
            + " ORDER BY r.id, o.filled_at, o.id LIMIT 20001",
            params,
        ).fetchall()
    if len(rows) > 20000:
        raise ValueError("Strategy execution history exceeds the journal's 20,000-order limit.")
    runs = defaultdict(list)
    for row in rows:
        runs[row["run_id"]].append(row)
    output = []
    for rid, fills in runs.items():
        trades = fold(fills, scenario)
        dates = {
            datetime.fromtimestamp(t[field], IST).date().isoformat()
            for t in trades
            for field in ("entry_ts", "exit_ts")
            if t.get(field) is not None
        }
        for day in sorted(dates):
            if not f"{year}-04-01" <= day < f"{year + 1}-04-01":
                continue
            output.append(
                {
                    "id": f"sm-{rid}-{day}",
                    "day": day,
                    "strategy_id": f"sm-{fills[0]['strategy_id']}",
                    "kind": fills[0]["strategy_name"],
                    "broker": fills[0]["broker"],
                    "paths": [scenario],
                    "trades": trades,
                    "status": "complete" if fills[0]["stopped_at"] else "running",
                    "candles": {},
                    "note": "Strategy Builder confirmed fills, matched FIFO within each leg/position. "
                    "Partial fills use the recorded cumulative average and fill timestamp. "
                    "Charges are estimates; original records contain no contract-note charges. "
                    "Days shown are fill days; no broker positions are inferred.",
                }
            )
    return output


def detail(owner, report_id, path=None):
    match = re.fullmatch(r"sm-(\d+)-(\d{4}-\d{2}-\d{2})", report_id)
    if not match:
        return None
    rid, day = match.groups()
    date = datetime.fromisoformat(day)
    year = date.year - (date.month < 4)
    for mode in ("LIVE", "PAPER"):
        for report in reports(owner, year, mode, path, int(rid)):
            if report["day"] == day:
                return report
    return None
