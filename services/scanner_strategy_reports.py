"""Persistent, account-owned paper/backtest reports; CSV is the only download."""

import csv
import io
import json
from pathlib import Path

from sqlalchemy import text

from database.engine_factory import create_db_engine


def metrics(trades):
    closed = [t for t in trades if t.get("exit_ts") is not None]
    net = [t["net_pnl"] for t in closed]
    wins = sum(max(0, n) for n in net)
    losses = -sum(min(0, n) for n in net)
    events = []
    for t in trades:
        amount = t["entry"] * t["quantity"]
        events.append((t["entry_ts"], 0, amount))
        if t.get("exit_ts") is not None:
            events.append((t["exit_ts"], 1, -amount))
    current = peak = equity = high = drawdown = 0.0
    # Entries before exits at equal timestamps: conservative capital requirement.
    for _, _, change in sorted(events):
        current += change
        peak = max(peak, current)
    for t in sorted(closed, key=lambda x: x["exit_ts"]):
        equity += t["net_pnl"]
        high = max(high, equity)
        drawdown = max(drawdown, high - equity)
    return {
        "trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "gross_pnl": sum(t["gross_pnl"] for t in closed),
        "charges": sum(t["fees"] for t in trades),
        "net_pnl": sum(net),
        "peak_capital": peak,
        "current_capital": max(0, round(current, 8)),
        "win_rate": 100 * sum(n > 0 for n in net) / len(net) if net else 0,
        "profit_factor": wins / losses if losses else None,
        "best_trade": max(net, default=0),
        "worst_trade": min(net, default=0),
        "realized_drawdown": drawdown,
        "return_on_peak_capital": 100 * sum(net) / peak if peak else 0,
    }


class ReportStore:
    def __init__(self, path="db/scanner_strategy_reports.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_db_engine("sqlite:///" + Path(path).resolve().as_posix())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS reports "
                    "(owner TEXT, id TEXT, day TEXT, payload TEXT, "
                    "PRIMARY KEY(owner,id))"
                )
            )

    def save(self, owner, report):
        # Recalculate each scenario separately; never add OLHC and OHLC together.
        report["metrics"] = {
            p: metrics([t for t in report["trades"] if t["path"] == p]) for p in report["paths"]
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO reports VALUES(:u,:i,:d,:p) "
                    "ON CONFLICT(owner,id) DO UPDATE SET payload=:p"
                ),
                {
                    "u": owner,
                    "i": report["id"],
                    "d": report["day"],
                    "p": json.dumps(report, allow_nan=False),
                },
            )

    def claim(self, owner, report):
        """Atomically reserve one paper session, including concurrent processes."""
        report["metrics"] = {p: metrics([]) for p in report["paths"]}
        with self.engine.begin() as conn:
            result = conn.execute(
                text("INSERT INTO reports VALUES(:u,:i,:d,:p) ON CONFLICT(owner,id) DO NOTHING"),
                {"u": owner, "i": report["id"], "d": report["day"],
                 "p": json.dumps(report, allow_nan=False)},
            )
            return result.rowcount == 1

    def list(self, owner):
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id,day,json_extract(payload,'$.kind') AS kind, "
                    "json_extract(payload,'$.status') AS status FROM reports WHERE owner=:u "
                    "ORDER BY day DESC,id DESC LIMIT 100"
                ),
                {"u": owner},
            )
            return [{"id": r.id, "day": r.day, "kind": r.kind, "status": r.status} for r in rows]

    def get(self, owner, report_id):
        with self.engine.connect() as conn:
            payload = conn.execute(
                text("SELECT payload FROM reports WHERE owner=:u AND id=:i"),
                {"u": owner, "i": report_id},
            ).scalar()
        return json.loads(payload) if payload else None

    def close(self):
        self.engine.dispose()


def trades_csv(report):
    fields = [
        "symbol",
        "path",
        "signal_ts",
        "entry_ts",
        "exit_ts",
        "entry",
        "exit",
        "quantity",
        "stop",
        "target",
        "gross_pnl",
        "fees",
        "net_pnl",
        "reason",
        "entry_order",
        "exit_order",
        "entry_order_state",
        "exit_order_state",
        "trail_armed_at",
        "entry_order_latency_us",
        "exit_order_latency_us",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for trade in report["trades"]:
        row = dict(trade)
        # Prevent spreadsheet formula execution in downloaded symbol/reason fields.
        for key in ("symbol", "path", "reason"):
            value = row.get(key)
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                row[key] = "'" + value
        writer.writerow(row)
    return output.getvalue()
