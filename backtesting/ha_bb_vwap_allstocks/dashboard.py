"""Loopback-only, read-only report server; there is deliberately no run endpoint."""

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from plotly.offline import get_plotlyjs

from strategies.ha_bb_vwap_v1.models import IST

from .configuration import HERE
from .statistics import combine, microseconds, period
from .storage import decode, read_connection


class Reports:
    def __init__(self, output):
        self.path = Path(output) / "results.sqlite"

    def meta(self):
        if not self.path.is_file():
            return {
                "state": "not_run",
                "message": "Historical backtest has not been run. This dashboard is ready for future results.",
                "strategies": [],
                "days": [],
            }
        with read_connection(self.path) as db:
            manifest = json.loads(
                db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0]
            )
            strategies = [
                dict(r)
                for r in db.execute("SELECT id,name,side,minutes FROM strategies ORDER BY id")
            ]
            days = [
                dict(r)
                for r in db.execute(
                    "SELECT day,symbols,tested,skipped,benchmark FROM days ORDER BY day"
                )
            ]
        return {
            "state": "demo"
            if manifest["demo"]
            else ("complete" if len(days) == len(manifest["planned_days"]) else "partial"),
            "manifest": manifest,
            "strategies": strategies,
            "days": days,
        }

    def selection(self, q):
        meta = self.meta()
        if meta["state"] == "not_run":
            raise ValueError(meta["message"])
        strategy = q.get("strategy", meta["strategies"][0]["id"])
        if strategy not in {r["id"] for r in meta["strategies"]}:
            raise ValueError("Unknown strategy")
        config = meta["manifest"]["config"]
        path = q.get("path", config["paths"][0])
        if path not in config["paths"]:
            raise ValueError("Unknown path")
        start, end = q.get("start", config["start"]), q.get("end", config["end"])
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("Start is after end")
        return meta, strategy, path, start, end

    def report(self, q):
        meta, strategy, path, start, end = self.selection(q)
        grouping = q.get("group", "month")
        anchor = meta["manifest"]["config"]["five_year_anchor"]
        period(start, grouping, anchor)
        with read_connection(self.path) as db:
            rows = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM daily WHERE strategy=? AND scenario=? AND day BETWEEN ? AND ? ORDER BY day",
                    (strategy, path, start, end),
                )
            ]
        capital = meta["manifest"]["capital_reference"]
        groups = defaultdict(list)
        for r in rows:
            groups[period(r["day"], grouping, anchor)].append(r)
        planned = meta["manifest"]["planned_days"]
        result = []
        for (label, a, b), data in groups.items():
            first, last = max(a, start), min(b, end)
            if grouping == "all":
                first, last = start, end
            expected = sum(first <= d <= last for d in planned)
            result.append(
                {
                    "period": label,
                    "start": first,
                    "end": last,
                    "covered_from": data[0]["day"],
                    "covered_to": data[-1]["day"],
                    "planned_days": expected,
                    "partial": len(data) != expected
                    or (grouping != "all" and (start > a or end < b)),
                    **combine(data, capital),
                }
            )
        curve, cumulative, high = [], 0.0, 0.0
        for r in rows:
            high = max(high, cumulative + r["session_peak"])
            cumulative += r["net_pnl"]
            curve.append(
                {
                    "day": r["day"],
                    "net_pnl": cumulative,
                    "daily_pnl": r["net_pnl"],
                    "drawdown_eod": high - cumulative,
                    "trades": r["trades"],
                    "peak_capital": r["peak_capital"],
                    "max_open_trades": r["max_open_trades"],
                }
            )
        benchmark = [d["benchmark"] for d in meta["days"] if start <= d["day"] <= end]
        benchmark_available = (
            bool(benchmark)
            and len(benchmark) == len(rows)
            and all(v is not None for v in benchmark)
        )
        benchmark_result = {
            "available": benchmark_available,
            "label": "NIFTY session open-to-close, price-only, fixed reference capital",
            "return_pct": 100 * sum(benchmark) if benchmark_available else None,
            "note": "No API fetch. Missing/incomplete index sessions make the comparison unavailable. This is an intraday price reference, not a traded portfolio.",
        }
        return {
            "summary": combine(rows, capital),
            "periods": result,
            "curve": curve,
            "benchmark": benchmark_result,
            "coverage": {
                "completed_days": len(rows),
                "planned_days": sum(start <= d <= end for d in planned),
                "skipped_symbol_sessions": sum(
                    d["skipped"] for d in meta["days"] if start <= d["day"] <= end
                ),
            },
        }

    def day(self, q):
        _, strategy, path, _, _ = self.selection(q)
        day = date.fromisoformat(q["day"]).isoformat()
        with read_connection(self.path) as db:
            row = db.execute(
                "SELECT payload FROM series WHERE strategy=? AND scenario=? AND day=?",
                (strategy, path, day),
            ).fetchone()
            coverage = [
                dict(r)
                for r in db.execute(
                    "SELECT symbol,status,details FROM coverage WHERE day=? ORDER BY status,symbol LIMIT 500",
                    (day,),
                )
            ]
        return {
            "series": decode(row[0]) if row else [],
            "coverage": coverage,
            "coverage_limit": 500,
        }

    def trades(self, q):
        _, strategy, path, start, end = self.selection(q)
        limit = min(200, max(1, int(q.get("limit", 50))))
        offset = max(0, int(q.get("offset", 0)))
        where, params = (
            "strategy=? AND scenario=? AND day BETWEEN ? AND ?",
            [strategy, path, start, end],
        )
        if q.get("symbol"):
            where += " AND symbol=?"
            params.append(q["symbol"])
        with read_connection(self.path) as db:
            count = db.execute(f"SELECT count(*) FROM trades WHERE {where}", params).fetchone()[0]
            rows = [
                dict(r)
                for r in db.execute(
                    f"SELECT id,day,symbol,side,quantity,entry_us,exit_us,net,fees,brokerage FROM trades WHERE {where} ORDER BY entry_us,id LIMIT ? OFFSET ?",
                    [*params, limit, offset],
                )
            ]
        return {"rows": rows, "total": count, "offset": offset, "limit": limit}

    def trade(self, q):
        with read_connection(self.path) as db:
            row = db.execute("SELECT payload FROM trades WHERE id=?", (q["id"],)).fetchone()
            if not row:
                raise ValueError("Trade not found")
            trade = decode(row[0])
            bars = db.execute(
                "SELECT payload FROM candles WHERE day=? AND symbol=? AND minutes=?",
                (trade["day"], trade["symbol"], trade["minutes"]),
            ).fetchone()
        return {
            "trade": trade,
            "candles": decode(bars[0]) if bars else [],
            "charts_stored": bool(bars),
        }

    def open_positions(self, q):
        _, strategy, path, _, _ = self.selection(q)
        day = date.fromisoformat(q["day"]).isoformat()
        stamp = datetime.fromisoformat(day + "T" + q.get("at", "10:00:00")).replace(tzinfo=IST)
        if not "09:15:00" <= stamp.strftime("%H:%M:%S") <= "15:30:00":
            raise ValueError("Choose 09:15–15:30 IST")
        us = microseconds(stamp)
        with read_connection(self.path) as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT t.id,t.symbol,t.side,t.entry_price,
                t.quantity-COALESCE((SELECT sum(f.quantity) FROM fills f WHERE f.trade_id=t.id AND f.seq>0 AND f.time_us<=?),0) remaining
                FROM trades t WHERE t.strategy=? AND t.scenario=? AND t.day=? AND t.entry_us<=? AND t.exit_us>?
                ORDER BY t.symbol""",
                    (us, strategy, path, day, us, us),
                )
            ]
            counters = db.execute(
                "SELECT COALESCE(sum(entry_us<=?),0),COALESCE(sum(exit_us<=?),0) FROM trades WHERE strategy=? AND scenario=? AND day=?",
                (us, us, strategy, path, day),
            ).fetchone()
            cash = db.execute(
                """SELECT COALESCE(sum(CASE WHEN f.seq=0 THEN -f.fees ELSE
                (CASE WHEN t.side='buy' THEN 1 ELSE -1 END)*(f.price-t.entry_price)*f.quantity-f.fees END),0)
                FROM fills f JOIN trades t ON t.id=f.trade_id
                WHERE t.strategy=? AND t.scenario=? AND t.day=? AND f.time_us<=?""",
                (strategy, path, day, us),
            ).fetchone()[0]
        return {
            "time": stamp.isoformat(),
            "positions": rows,
            "open_trades": len(rows),
            "capital_used": sum(r["remaining"] * r["entry_price"] for r in rows),
            "entries_so_far": counters[0],
            "closed_so_far": counters[1],
            "realized_pnl_less_paid_fees": cash,
        }

    def export_rows(self, q):
        kind = q.get("kind", "periods")
        if kind == "periods":
            yield from self.report(q)["periods"]
            return
        _, strategy, path, start, end = self.selection(q)
        if kind == "trades":
            sql = "SELECT id,day,symbol,side,quantity,entry_us,exit_us,net,gross,fees,brokerage FROM trades WHERE strategy=? AND scenario=? AND day BETWEEN ? AND ? ORDER BY entry_us,id"
        elif kind == "fills":
            sql = "SELECT t.id,t.day,t.symbol,f.seq,f.time_us,f.side,f.quantity,f.price,f.fees,f.brokerage,f.reason,f.costs FROM fills f JOIN trades t ON t.id=f.trade_id WHERE t.strategy=? AND t.scenario=? AND t.day BETWEEN ? AND ? ORDER BY f.time_us,t.id,f.seq"
        else:
            raise ValueError("Export kind must be periods, trades or fills")
        with read_connection(self.path) as db:
            cursor = db.execute(sql, (strategy, path, start, end))
            while batch := cursor.fetchmany(500):
                for row in batch:
                    yield dict(row)


def make_server(output, port=8777):
    reports = Reports(output)
    plotly_js = get_plotlyjs().encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data, content_type="application/json", status=200):
            body = data if isinstance(data, bytes) else json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            target = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(target.query).items()}
            try:
                static = {
                    "/": ("index.html", "text/html"),
                    "/app.js": ("app.js", "application/javascript"),
                    "/style.css": ("style.css", "text/css"),
                }
                if target.path in static:
                    name, mime = static[target.path]
                    self.reply((HERE / "web" / name).read_bytes(), mime)
                elif target.path == "/plotly.min.js":
                    self.reply(plotly_js, "application/javascript")
                elif target.path == "/api/meta":
                    self.reply(reports.meta())
                elif target.path in {
                    "/api/report",
                    "/api/day",
                    "/api/trades",
                    "/api/trade",
                    "/api/open",
                }:
                    method = {"/api/open": reports.open_positions}.get(target.path)
                    if method is None:
                        method = getattr(reports, target.path.split("/")[-1])
                    self.reply(method(q))
                elif target.path == "/api/export":
                    iterator = reports.export_rows(q)
                    first = next(iterator, None)  # Validate before sending headers.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header(
                        "Content-Disposition", "attachment; filename=backtest-report.csv"
                    )
                    self.end_headers()
                    if first:
                        buffer = io.StringIO(newline="")
                        writer = csv.DictWriter(buffer, fieldnames=list(first))
                        writer.writeheader()
                        writer.writerow(first)
                        self.wfile.write(buffer.getvalue().encode())
                        for row in iterator:
                            buffer.seek(0)
                            buffer.truncate(0)
                            writer.writerow(row)
                            self.wfile.write(buffer.getvalue().encode())
                else:
                    self.reply({"error": "Not found"}, status=404)
            except (ValueError, KeyError) as error:
                self.reply({"error": str(error)}, status=400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                self.reply({"error": f"Report unavailable: {error}"}, status=500)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(output, port=8777):
    server = make_server(output, port)
    print(
        f"Read-only dashboard: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)", flush=True
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
