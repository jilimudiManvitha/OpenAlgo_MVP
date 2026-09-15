"""Offline single-worker BTC replay, accounting reconciliation and HTML report."""

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.offline
import vectorbt as vbt

from backtesting.ethfut_404.data import write_json
from backtesting.btcfut_404.engine import REASONS
from backtesting.ha_bb_vwap_v1_20260911.replay import definitions


def iso(us):
    return datetime.fromtimestamp(float(us) / 1e6, UTC).isoformat()


def csv_write(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reconcile(fills, net):
    if not len(fills):
        assert net == 0
        return
    prices = pd.Series(fills[:, 3])
    pf = vbt.Portfolio.from_orders(
        prices,
        size=fills[:, 2],
        price=prices,
        fees=0,
        fixed_fees=fills[:, 4],
        direction="both",
        init_cash=1e8,
        allow_partial=False,
        freq="1min",
    )
    # Large reconciliation cash permits fixed-notional opportunity accounting.
    # It is not the report's capital denominator or a funding assertion.
    assert len(pf.orders.records) == len(fills)
    np.testing.assert_allclose(pf.total_profit(), net, atol=1e-6)
    np.testing.assert_allclose(fills[:, 2].sum(), 0, atol=1e-8)


def summarize(sid, cfg, fills, marks, output):
    trades, fill_rows = [], []
    trade = None
    qty = 0.0
    peak_notional = 0.0
    for f in fills:
        reason = REASONS[int(f[5])]
        row = {
            "time": iso(f[1]),
            "side": "buy" if f[2] > 0 else "sell",
            "btc": abs(f[2]),
            "price": f[3],
            "fees": f[4],
            "reason": reason,
            "signal_start": iso(f[6]),
            "initial_stop": f[7],
            "target": f[8],
        }
        fill_rows.append(row)
        if reason == "entry":
            assert trade is None
            qty = abs(f[2])
            peak_notional = max(peak_notional, qty * f[3])
            trade = {
                "entry_time": row["time"],
                "entry_price": f[3],
                "btc": qty,
                "signal_start": row["signal_start"],
                "initial_stop": f[7],
                "target": f[8],
                "gross_pnl": 0.0,
                "fees": f[4],
                "partial_exits": 0,
            }
        else:
            assert trade is not None
            trade["gross_pnl"] += cfg.direction * (f[3] - trade["entry_price"]) * abs(f[2])
            trade["fees"] += f[4]
            qty -= abs(f[2])
            if reason == "partial_first":
                trade["partial_exits"] += 1
            if abs(qty) < 1e-8:
                trade.update(
                    exit_time=row["time"],
                    exit_price=f[3],
                    exit_reason=reason,
                    net_pnl=trade["gross_pnl"] - trade["fees"],
                    holding_hours=(
                        f[1] / 1e6 - datetime.fromisoformat(trade["entry_time"]).timestamp()
                    )
                    / 3600,
                )
                trades.append(trade)
                trade = None
    assert trade is None
    net = sum(x["net_pnl"] for x in trades)
    reconcile(fills, net)
    np.testing.assert_allclose(marks[-1, 1], net, atol=1e-6)
    curve = np.r_[0.0, marks[:, 1]]
    peaks = np.maximum.accumulate(curve)
    dd = peaks - curve
    date_index = pd.to_datetime(marks[:, 0].astype("int64"), unit="us", utc=True)
    daily = pd.Series(marks[:, 1], index=date_index).resample("1D").last().ffill()
    daily_pnl = daily.diff().fillna(daily.iloc[0])
    daily_returns = daily_pnl / 100000
    wins = [x["net_pnl"] for x in trades if x["net_pnl"] > 0]
    losses = [x["net_pnl"] for x in trades if x["net_pnl"] < 0]
    sharpe = (
        float(daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(365))
        if daily_returns.std(ddof=1)
        else None
    )
    negative = np.minimum(daily_returns.to_numpy(), 0)
    downside = np.sqrt(np.mean(negative**2))
    sortino = float(daily_returns.mean() / downside * np.sqrt(365)) if downside else None
    gross = sum(x["gross_pnl"] for x in trades)
    summary = {
        "id": sid,
        "name": cfg.name,
        "side": cfg.side,
        "minutes": cfg.timeframe_minutes,
        "rr": cfg.reward_risk,
        "buffer": cfg.sl_buffer,
        "trail": cfg.trail_fraction,
        "partial": cfg.partial,
        "stop_rule": cfg.stop_rule,
        "target_rule": cfg.target_rule,
        "trades": len(trades),
        "gross_pnl": gross,
        "fees": float(fills[:, 4].sum()),
        "net_pnl": net,
        "return_pct": net / 1000,
        "max_drawdown": float(dd.max()),
        "max_drawdown_pct": float(np.max(dd / (100000 + peaks)) * 100),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "best_trade": max(wins + losses, default=0),
        "worst_trade": min(wins + losses, default=0),
        "average_win": float(np.mean(wins)) if wins else 0.0,
        "average_loss": float(np.mean(losses)) if losses else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "peak_entry_notional": peak_notional,
        "mean_holding_hours": float(np.mean([x["holding_hours"] for x in trades]))
        if trades
        else 0.0,
        "overnight_trades": sum(x["entry_time"][:10] != x["exit_time"][:10] for x in trades),
        "funding_cost_included": False,
        "min_reference_equity": float(100000 + curve.min()),
    }
    csv_write(
        output / f"{sid}_fills.csv",
        fill_rows,
        [
            "time",
            "side",
            "btc",
            "price",
            "fees",
            "reason",
            "signal_start",
            "initial_stop",
            "target",
        ],
    )
    csv_write(
        output / f"{sid}_trades.csv",
        trades,
        [
            "entry_time",
            "entry_price",
            "btc",
            "signal_start",
            "initial_stop",
            "target",
            "gross_pnl",
            "fees",
            "partial_exits",
            "exit_time",
            "exit_price",
            "exit_reason",
            "net_pnl",
            "holding_hours",
        ],
    )
    daily_rows = [
        {
            "date": str(d.date()),
            "cumulative_pnl": float(value),
            "daily_pnl": float(daily_pnl.loc[d]),
        }
        for d, value in daily.items()
    ]
    csv_write(output / f"{sid}_daily.csv", daily_rows)
    return summary, daily_rows


def benchmark(t, p):
    entry, exit_ = p[0] * 1.0005, p[-1] * 0.9995
    quantity = np.floor(100000 / (entry * 0.01)) * 0.01
    entry_fee, exit_fee = quantity * entry * 0.0005, quantity * exit_ * 0.0005
    curve = quantity * (p - entry) - entry_fee
    curve[-1] = quantity * (exit_ - entry) - entry_fee - exit_fee
    curve = np.r_[0.0, curve]
    peaks = np.maximum.accumulate(curve)
    daily = (
        pd.Series(curve[1:], index=pd.to_datetime(t, unit="us", utc=True))
        .resample("1D")
        .last()
        .ffill()
    )
    r = daily.diff().fillna(daily.iloc[0]) / 100000
    down = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return {
        "net_pnl": float(curve[-1]),
        "return_pct": float(curve[-1] / 1000),
        "max_drawdown": float((peaks - curve).max()),
        "max_drawdown_pct": float(np.max((peaks - curve) / (100000 + peaks)) * 100),
        "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(365)),
        "sortino": float(r.mean() / down * np.sqrt(365)) if down else None,
        "fees": float(entry_fee + exit_fee),
        "btc": float(quantity),
        "daily": [{"date": str(k.date()), "cumulative_pnl": float(v)} for k, v in daily.items()],
    }


def report(summaries, daily, audit, bench, output):
    ranked = sorted(summaries, key=lambda x: -x["net_pnl"])
    csv_write(output / "rankings.csv", ranked)
    winners = [
        max(
            [s for s in summaries if s["side"] == side and s["minutes"] == m],
            key=lambda s: s["net_pnl"],
        )
        for side in ("buy", "sell")
        for m in (1, 5)
    ]
    lines = [
        "# BTCFUT 404-strategy backtest",
        "",
        f"Completed: 404/404 versions; {audit['rows']:,} supplied BTCUSD trades.",
        f"Period: {audit['first']} to {audit['last']}.",
        "",
        "24/7 entries and exits; positions carry through midnight. No daily square-off.",
        "USD model: $100,000 fixed notional per version, 0.01 BTC increments, 0.05% fee per fill and 0.05% adverse slippage.",
        "Net results are after modeled trading fees and slippage, BEFORE funding and tax. Rates and contract sizing are research assumptions, not verified historical broker terms.",
        "UTC is assumed for naive input timestamps; VWAP resets at UTC midnight. Prices are actual supplied trades, not an invented OHLC path.",
        "Continuous HA; at most 600 prior nonempty bars initialize forming OpenAlgo indicators. No missing candles or trades are fabricated.",
        "Completed-bar orders execute at the next source trade; forming orders at the triggering trade plus slippage. Final open positions are liquidated at the last source trade.",
        "Same-trade fills omit latency, spread, depth and participation constraints. Gaps can delay exit fills.",
        f"Coverage: {audit['gaps_over_5_minutes']} gaps >5 minutes; largest {audit['largest_gap_seconds'] / 60:.2f} minutes. Coverage is limited to the supplied archive timestamps.",
        "All versions are independent fixed-notional opportunity tests, without compounding or a shared portfolio. USD is not INR. Margin, leverage, liquidation and funding histories are unavailable.",
        "Daily Sharpe/Sortino use fixed-capital daily P&L / $100,000, 365-day annualization and zero risk-free rate. Drawdown uses every replay observation.",
        "",
        "| Group | Version | Net USD | Return | Max DD USD | Trades | Win rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for s in winners:
        lines.append(
            f"| {s['side']} {s['minutes']}m | {s['id']} | {s['net_pnl']:,.2f} | {s['return_pct']:.2f}% | {s['max_drawdown']:,.2f} | {s['trades']} | {s['win_rate']:.2f}% |"
        )
    lines += [
        "",
        f"BTC buy-and-hold: net ${bench['net_pnl']:,.2f}, return {bench['return_pct']:.2f}%, max drawdown ${bench['max_drawdown']:,.2f}.",
        f"Profitable versions after modeled costs: {sum(s['net_pnl'] > 0 for s in summaries)}/404.",
        "Ranks are retrospective across the supplied period; this is not an out-of-sample strategy selection test. Ties remain in rankings.csv.",
        "See index.html for searchable rankings, all-version equity curves and individual fill/trade/daily CSVs.",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    payload = json.dumps({"rows": ranked, "daily": daily, "benchmark": bench}, allow_nan=False)
    import html

    prose = "<br>".join(html.escape(x) for x in lines[2:16])
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><title>BTCFUT | 404 strategy report</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><script src="plotly.min.js"></script>
<style>body{background:#0b1220;color:#e2e8f0;font:15px system-ui;margin:30px}h1{color:#67e8f9}a{color:#67e8f9}p{line-height:1.6;max-width:1200px}input,select{padding:10px;background:#182337;color:white;border:1px solid #475569;border-radius:6px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:10px;border-bottom:1px solid #273449;text-align:right}th{position:sticky;top:0;background:#182337}td:first-child,td:nth-child(2){text-align:left}#tablebox{overflow:auto;max-height:600px}.green{color:#4ade80}.red{color:#fb7185}#stats{line-height:1.8}</style>
<h1>BTCFUT · All 404 strategies · 24/7</h1><p>April–May 2024 · actual supplied BTCUSD trades · completed historical replay</p>
<p>PROSE</p><p><a href="report.md">Written findings</a> · <a href="rankings.csv">All rankings CSV</a> · <a href="source_audit.json">Data audit</a> · <a href="validation.json">Validation</a></p>
<h2>Explore a strategy</h2><select id="choice"></select><p id="stats"></p><div id="chart"></div>
<h2>All versions ranked by net P&amp;L</h2><input id="search" placeholder="Filter ID, side, timeframe, rule" aria-label="Filter strategies"><p id="count"></p>
<div id="tablebox"><table><thead><tr><th>ID</th><th>Group / RR</th><th>Net USD</th><th>Return %</th><th>Fees</th><th>Max DD</th><th>Trades</th><th>Win %</th><th>PF</th><th>Sharpe</th><th>Ledgers</th></tr></thead><tbody id="rows"></tbody></table></div>
<script>const DATA=PAYLOAD;const f=x=>x==null?'N/A':Number(x).toLocaleString('en-US',{maximumFractionDigits:2});
const choice=document.getElementById('choice');choice.innerHTML=DATA.rows.map(s=>`<option value="${s.id}">${s.id} · ${s.side} ${s.minutes}m · RR ${s.rr} · $${f(s.net_pnl)}</option>`).join('');
function select(){const s=DATA.rows.find(x=>x.id===choice.value), d=DATA.daily[s.id], b=DATA.benchmark;
document.getElementById('stats').innerHTML=`${s.name}<br>Net: <b>$${f(s.net_pnl)}</b> · Return: ${f(s.return_pct)}% · Max drawdown: $${f(s.max_drawdown)} (${f(s.max_drawdown_pct)}%) · Fees: $${f(s.fees)}<br>${s.trades} trades · Win ${f(s.win_rate)}% · Profit factor ${f(s.profit_factor)} · Sharpe ${f(s.sharpe)} · Sortino ${f(s.sortino)} · Overnight trades: ${s.overnight_trades}<br>Best/worst trade: $${f(s.best_trade)} / $${f(s.worst_trade)} · Peak entry notional: $${f(s.peak_entry_notional)}<br>BTC buy-and-hold: $${f(b.net_pnl)} (${f(b.return_pct)}%) · Max DD $${f(b.max_drawdown)} · Sharpe ${f(b.sharpe)} · Sortino ${f(b.sortino)}<br><a href="${s.id}_trades.csv">Trades</a> · <a href="${s.id}_fills.csv">Fills</a> · <a href="${s.id}_daily.csv">Daily P&L</a>`;
let peak=0;const dd=d.map(x=>{peak=Math.max(peak,x.cumulative_pnl);return x.cumulative_pnl-peak});
Plotly.newPlot('chart',[{x:d.map(x=>x.date),y:d.map(x=>x.cumulative_pnl),name:s.id+' cumulative P&L',line:{color:'#22d3ee'}},{x:b.daily.map(x=>x.date),y:b.daily.map(x=>x.cumulative_pnl),name:'BTC buy & hold',line:{color:'#a78bfa'}},{x:d.map(x=>x.date),y:dd,name:'Daily sampled drawdown',yaxis:'y2',fill:'tozeroy',line:{color:'#fb7185'}}],{paper_bgcolor:'#0b1220',plot_bgcolor:'#0b1220',font:{color:'#cbd5e1'},height:560,xaxis:{anchor:'y2'},yaxis:{domain:[.4,1],title:'P&L USD'},yaxis2:{domain:[0,.25],title:'Daily DD USD'},legend:{orientation:'h'},margin:{t:30}},{responsive:true});}
function filter(){const q=document.getElementById('search').value.toLowerCase();const list=DATA.rows.filter(s=>(s.id+' '+s.name+' '+s.minutes+'m').toLowerCase().includes(q));document.getElementById('count').textContent=list.length+' / 404 versions';document.getElementById('rows').innerHTML=list.map(s=>`<tr><td><a href="#choice" onclick="choice.value='${s.id}';select()">${s.id}</a></td><td>${s.side} ${s.minutes}m / ${s.rr}R</td><td class="${s.net_pnl>=0?'green':'red'}">${f(s.net_pnl)}</td><td>${f(s.return_pct)}</td><td>${f(s.fees)}</td><td>${f(s.max_drawdown)}</td><td>${s.trades}</td><td>${f(s.win_rate)}</td><td>${f(s.profit_factor)}</td><td>${f(s.sharpe)}</td><td><a href="${s.id}_trades.csv">CSV</a></td></tr>`).join('')};choice.onchange=select;document.getElementById('search').oninput=filter;select();filter();</script></html>"""
    (output / "index.html").write_text(
        page.replace("PROSE", prose).replace("PAYLOAD", payload), encoding="utf-8"
    )
    (output / "plotly.min.js").write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")
    write_json(
        output / "summary.json",
        {"strategies": ranked, "benchmark": bench, "group_leaders": winners},
    )

