"""Read verified September 30 eight-strategy reports; export offline review artifacts."""

import csv
import hashlib
import html
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from services.scanner_strategy_reports import metrics, trades_csv
from strategies.top_gain_volumes.profiles import PROFILES
from strategies.top_gain_volumes.replay_four import verify_ledger

OUT = Path(__file__).resolve().parent
DAY = "2026-09-30"
IST = ZoneInfo("Asia/Kolkata")


def main():
    with closing(
        sqlite3.connect((ROOT / "db/scanner_strategy_reports.db").as_uri() + "?mode=ro", uri=True)
    ) as conn:
        reports = {
            json.loads(payload)["strategy_id"]: json.loads(payload)
            for (payload,) in conn.execute(
                "SELECT payload FROM reports WHERE day=? AND id LIKE ?", (DAY, "backtest-%")
            )
        }
    assert set(reports) == set(PROFILES)
    cache = ROOT / "db/scanner_backtest_cache" / (DAY + "-four-strategies")
    selection = json.loads((cache / "selection.json").read_text())
    bench_source = OUT / "nifty_session_source.json"
    benchmark = json.loads(bench_source.read_text())["candles"]
    assert len(benchmark) == len({r[0] for r in benchmark}) == 375
    opening = int(datetime(2026, 9, 30, 9, 15, tzinfo=IST).timestamp())
    cutoff = int(datetime(2026, 9, 30, 15, 0, tzinfo=IST).timestamp())
    bench_start = next(r[1] for r in benchmark if r[0] == opening)
    bench_end = next(r[1] for r in benchmark if r[0] == cutoff)
    benchmark_return = (bench_end / bench_start - 1) * 100
    (OUT / "nifty_benchmark.json").write_text(
        json.dumps(
            {
                "source": "FYERS",
                "start": opening,
                "end": cutoff,
                "start_open": bench_start,
                "end_open": bench_end,
                "gross_return_percent": benchmark_return,
                "sha256": hashlib.sha256(bench_source.read_bytes()).hexdigest(),
                "candles": benchmark,
            },
            indent=2,
        )
    )
    summary = []
    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=(
            "1-minute HA — cumulative realized net P&L",
            "5-minute HA — cumulative realized net P&L",
        ),
        vertical_spacing=0.13,
    )
    for ident, profile in PROFILES.items():
        report = reports[ident]
        expected = selection[
            "scanner_symbols" if profile["universe"] == "nifty500" else "watchlist_symbols"
        ]
        assert report["selection"]["symbols"] == expected
        assert report["timeframe_minutes"] == profile["timeframe_minutes"]
        assert len(report["coverage"]) == len(expected)
        excluded = {r["symbol"] for r in report["coverage"] if not r["eligible"]}
        assert excluded == (
            {"GANESHBE", "STLTECH"} if profile["universe"] == "watchlist" else set()
        )
        assert all(
            r["eligible"] or r["reason"] == "outside_scheduled_EQ_universe"
            for r in report["coverage"]
        )
        eligible_count = sum(r["eligible"] for r in report["coverage"])
        assert report["verification"]["passed"]
        verify_ledger(report["trades"])
        for symbol, sha in report["input_hashes"].items():
            assert hashlib.sha256((cache / (symbol + ".json")).read_bytes()).hexdigest() == sha
        (OUT / (ident + "_trades.csv")).write_text(trades_csv(report))
        for path in report["paths"]:
            trades = [t for t in report["trades"] if t["path"] == path]
            computed = metrics(trades)
            assert computed == report["metrics"][path]
            assert computed["open_trades"] == 0
            assert all(opening <= t["entry_ts"] < cutoff and t["exit_ts"] <= cutoff for t in trades)
            assert all(
                t.get("timeframe_minutes", 1) == profile["timeframe_minutes"] for t in trades
            )
            summary.append(
                {
                    "strategy": profile["name"],
                    "profile": ident,
                    "timeframe_minutes": profile["timeframe_minutes"],
                    "path": path,
                    "coverage": f"{eligible_count}/{len(expected)}",
                    **computed,
                    "nifty_gross_return_percent": benchmark_return,
                    "sharpe": "N/A — one session",
                    "sortino": "N/A — one session",
                }
            )
            equity = 0
            x, y = [datetime.fromtimestamp(opening, IST)], [0]
            for trade in sorted(trades, key=lambda t: t["exit_ts"]):
                equity += trade["net_pnl"]
                x.append(datetime.fromtimestamp(trade["exit_ts"], IST))
                y.append(equity)
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    name=profile["name"] + " " + path,
                    visible=True if path == "OLHC" else "legendonly",
                ),
                row=1 if profile["timeframe_minutes"] == 1 else 2,
                col=1,
            )
    with (OUT / "summary.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    fig.update_layout(
        template="plotly_dark",
        height=950,
        legend={"orientation": "h", "y": -0.12},
        margin={"b": 180},
        title="September 30, 2026 · Eight scheduled strategies",
    )
    fig.update_yaxes(title_text="Net P&L (INR)")
    fig.update_xaxes(type="date")
    chart = fig.to_html(full_html=False, include_plotlyjs=True)
    rows = []
    for row in summary:
        rows.append(
            "<tr>"
            + "".join(
                "<td>" + html.escape(str(v)) + "</td>"
                for v in [
                    row["strategy"],
                    row["path"],
                    row["coverage"],
                    row["trades"],
                    f"{row['net_pnl']:,.2f}",
                    f"{row['win_rate']:.1f}%",
                    f"{row['profit_factor']:.2f}" if row["profit_factor"] is not None else "N/A",
                    f"{row['realized_drawdown']:,.2f}",
                    f"{row['peak_capital']:,.2f}",
                    f"{row['return_on_peak_capital']:.2f}%",
                ]
            )
            + "</tr>"
        )
    links = "".join(
        f'<li><a href="{ident}_trades.csv">{html.escape(p["name"])} — trades CSV</a></li>'
        for ident, p in PROFILES.items()
    )
    doc = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Eight strategy backtests · September 30</title>
<style>body{font:16px system-ui;background:#101722;color:#e6edf3;margin:32px auto;padding:0 20px;max-width:1500px}a{color:#6ac6ff}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border-bottom:1px solid #334155;text-align:right}td:first-child,th:first-child{text-align:left}p{line-height:1.6;max-width:1150px}.table{overflow-x:auto}</style></head><body>
<h1>Eight scheduled strategies — September 30, 2026</h1>
<p>09:15–15:00 IST · ₹10,000 per trade · whole shares · stop 0.03% below signal HA low · fixed 3R or trail after 3R. Four 1m and four 5m HA profiles use their shared scheduled strategy calculations.</p>
<p><b>Coverage:</b> scanner 76/76; Wednesday watchlist 16/18. GANESHBE and STLTECH are BE-series stocks outside the scheduled strategies’ EQ-only universe and are excluded. Source: FYERS minute OHLCV, exact regular-session epoch requests, seven prior calendar days for warmup. Input hashes and ledger verification passed for every report.</p>
<p><b>Interpretation:</b> OLHC means open→low→high→close; OHLC means open→high→low→close. These are alternative modeled minute paths with eight samples per leg and uniform modeled volume, not actual exchange ticks or strict best/worst bounds. Do not add the two scenarios. Five-minute OHLCV is aggregated before HA/BB/VWAP, while entries/exits observe the modeled minute path.</p>
<p><b>Limitations:</b> the final 15:30 scanner basket and current Wednesday watchlist are applied retrospectively; intraday membership changes and order-book bid/ask/fill delays were not recorded. Results are hypothetical full-session replays, not the interrupted live Sandbox runs. Prices include 5 bps adverse slippage per side and costs use illustrative 5 bps per fill, not actual broker taxes/charges. No portfolio capital cap is modeled. Drawdown is realized-trade drawdown, not intratrade mark-to-market.</p>
"""
    doc += f"<p><b>NIFTY comparison:</b> 09:15 open {bench_start:,.2f} → 15:00 open {bench_end:,.2f}: <b>{benchmark_return:+.3f}% gross</b>. Strategy return below uses peak simultaneous entry notional; that differs from a continuously invested index. Sharpe/Sortino are not estimated from one session.</p>"
    doc += (
        '<div class="table"><table><thead><tr>'
        + "".join(
            f"<th>{v}</th>"
            for v in [
                "Strategy",
                "Path",
                "Coverage",
                "Trades",
                "Net ₹",
                "Win rate",
                "Profit factor",
                "Realized DD ₹",
                "Peak notional ₹",
                "Return / peak",
            ]
        )
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )
    doc += (
        chart
        + '<h2>Downloads</h2><p><a href="summary.csv">Summary CSV</a></p><ul>'
        + links
        + "</ul></body></html>"
    )
    (OUT / "index.html").write_text(doc)
    print(
        "Verified and exported",
        len(summary),
        "scenario rows; NIFTY gross return",
        round(benchmark_return, 4),
    )
    for row in summary:
        print(row["profile"], row["path"], row["trades"], round(row["net_pnl"], 2), row["coverage"])


if __name__ == "__main__":
    main()
