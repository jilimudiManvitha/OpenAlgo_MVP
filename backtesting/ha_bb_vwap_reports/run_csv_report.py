"""Reproduce the saved ATHERENERG strategy and export audited P&L reports."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import html
import json
from pathlib import Path
import sys
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd
import openstatz as ostz
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stratagies"))
import ha_bb_vwap_strategy_astra as strategy
from polars_data import aggregate_pnl, export_heikin_ashi, prepare_historify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--capital", type=float, default=100_000)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg = strategy.Config(capital=args.capital, volume_filter=False,
                          breakout_source="high", exit_mode="bb_middle")
    now = pd.Timestamp.now(tz=strategy.TZ)
    prepared = prepare_historify(args.csv, now=now)
    prepared.write(out)
    exclusions = prepared.exclusions
    raw = prepared.to_strategy()
    d = strategy.indicators(raw, cfg)
    export_heikin_ashi(d, out)
    trades = strategy.simulate({"ATHERENERG": d}, cfg)
    if trades.empty:
        raise ValueError("No trades: report requires empty-trade handling")
    trades.insert(0, "trade_id", range(1, len(trades) + 1))
    trades.to_csv(out / "trades.csv", index=False)

    # Equity includes accrued round-trip fees on open positions, matching engine.
    equity = pd.Series(cfg.capital, index=d.index, dtype=float)
    for t in trades.itertuples():
        active = (d.index >= t.entry_time) & (d.index < t.exit_time)
        equity.loc[active] += t.quantity * (d.loc[active, "close"] - t.entry)
        equity.loc[active] -= t.quantity * (d.loc[active, "close"] + t.entry) * cfg.fee_bps / 10000
        equity.loc[d.index >= t.exit_time] += t.net_pnl
    dd = (equity / equity.cummax().clip(lower=cfg.capital) - 1) * 100
    dd_rupees = equity.cummax().clip(lower=cfg.capital) - equity
    pd.DataFrame({"equity": equity, "drawdown_pct": dd}).to_csv(out / "equity_5m.csv")
    daily_equity = equity.groupby(equity.index.normalize()).last()
    returns = daily_equity.pct_change()
    returns.iloc[0] = daily_equity.iloc[0] / cfg.capital - 1
    returns.index = returns.index.tz_localize(None)
    returns.name = "ATHERENERG HA high breakout / BB middle exit"
    daily, monthly, by_exit = aggregate_pnl(trades, daily_equity, cfg.capital)
    daily.to_csv(out / "daily_pnl.csv", index_label="date")
    monthly.to_csv(out / "monthly_pnl.csv", index_label="month")
    by_exit.to_csv(out / "exit_breakdown.csv")

    # Same-dataset reference: whole-share buy-and-hold, before costs, no external data.
    quantity = int(cfg.capital // d.open.iloc[0])
    benchmark_equity = cfg.capital + quantity * (d.close - d.open.iloc[0])
    benchmark_daily = benchmark_equity.groupby(d.index.normalize()).last()
    benchmark = benchmark_daily.pct_change()
    benchmark.iloc[0] = benchmark_daily.iloc[0] / cfg.capital - 1
    benchmark.index = benchmark.index.tz_localize(None)
    benchmark.name = "ATHERENERG buy & hold (before costs)"
    comparison = pd.DataFrame({"Strategy": [returns.add(1).prod()-1,
            ostz.stats.sharpe(returns), ostz.stats.sortino(returns), ostz.stats.max_drawdown(returns)],
        benchmark.name: [benchmark.add(1).prod()-1, ostz.stats.sharpe(benchmark),
            ostz.stats.sortino(benchmark), ostz.stats.max_drawdown(benchmark)]},
        index=["Total return (fraction)", "Daily Sharpe (252, rf=0)", "Daily Sortino (252, rf=0)",
               "Daily max drawdown (fraction)"])
    comparison.to_csv(out / "benchmark_comparison.csv")
    returns.to_frame("strategy_return").join(benchmark.rename("benchmark_return")).to_csv(out / "daily_returns.csv")
    wins, losses = trades.net_pnl[trades.net_pnl > 0], trades.net_pnl[trades.net_pnl < 0]
    summary = dict(symbol="ATHERENERG", capital=cfg.capital, source_bars=prepared.source_bars,
        included_bars=len(d), included_sessions=len(daily), excluded_sessions=exclusions,
        start_ist=str(d.index[0]), last_bar_open_ist=str(d.index[-1]),
        source_last_bar_open_ist=prepared.source_last_timestamp,
        trades=len(trades), wins=len(wins), losses=len(losses), breakeven=int(trades.net_pnl.eq(0).sum()),
        gross_pnl=float(trades.gross_pnl.sum()), fees=float(trades.costs.sum()),
        net_pnl=float(trades.net_pnl.sum()), final_equity=float(equity.iloc[-1]),
        return_pct=float((equity.iloc[-1] / cfg.capital - 1) * 100),
        win_rate_pct=float(len(wins) / len(trades) * 100),
        profit_factor=float(wins.sum() / -losses.sum()) if len(losses) else None,
        max_drawdown_pct=float(-dd.min()), max_drawdown_rupees=float(dd_rupees.max()),
        daily_max_drawdown_pct=float(-ostz.stats.max_drawdown(returns) * 100),
        daily_sharpe=float(ostz.stats.sharpe(returns)), daily_sortino=float(ostz.stats.sortino(returns)),
        average_trade=float(trades.net_pnl.mean()), best_trade=float(trades.net_pnl.max()),
        worst_trade=float(trades.net_pnl.min()), active_days=int((daily.trades > 0).sum()),
        config={k:str(v) if hasattr(v, "isoformat") else v for k,v in asdict(cfg).items()},
        source_csv=str(args.csv.resolve()), source_sha256=hashlib.sha256(args.csv.read_bytes()).hexdigest(),
        strategy_sha256=hashlib.sha256(Path(strategy.__file__).read_bytes()).hexdigest(),
        generated_ist=str(now), data_processing="Polars CSV preparation and P&L aggregation; existing pandas/NumPy strategy",
        benchmark="Same-dataset ATHERENERG buy-and-hold before costs; NIFTY not supplied",
        cost_note="5 bps fees per side, 5 bps adverse slippage with tick rounding. Illustrative existing assumptions, not verified broker charges.")
    # Financial reconciliations and timing checks are independent of presentation.
    np.testing.assert_allclose(trades.gross_pnl - trades.costs, trades.net_pnl, atol=1e-8)
    np.testing.assert_allclose(cfg.capital + trades.net_pnl.cumsum(), trades.equity_after, atol=1e-8)
    np.testing.assert_allclose(daily.net_pnl.sum(), summary["net_pnl"], atol=1e-8)
    np.testing.assert_allclose(monthly.net_pnl.sum(), summary["net_pnl"], atol=1e-8)
    np.testing.assert_allclose(equity.iloc[-1], cfg.capital + summary["net_pnl"], atol=1e-8)
    np.testing.assert_allclose(returns.add(1).prod(), equity.iloc[-1] / cfg.capital, atol=1e-10)
    assert (trades.entry_time == trades.confirmation_time + strategy.FIVE).all()
    assert (trades.entry_time.dt.date == trades.exit_time.dt.date).all()
    assert trades.groupby(trades.entry_time.dt.date).size().max() <= cfg.max_trades
    assert trades.quantity.ge(1).all() and trades.quantity.mod(1).eq(0).all()
    assert (trades.exit_time.dt.time <= cfg.square_off).all()
    summary["validation"] = "PASS: trade/daily/monthly/equity reconciliations, delayed entries, same-day exits, integer quantities, daily limits"
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    ostz.dashboard(returns, benchmark=benchmark, output=str(out / "interactive_tearsheet.html"),
                   title="ATHERENERG | INR 100,000 | Latest saved strategy", open_browser=False)
    fig = make_subplots(rows=3, cols=1, vertical_spacing=.10,
                        subplot_titles=["Account equity (INR)", "5-minute sampled drawdown (%)", "Monthly net P&L (INR)"])
    fig.add_trace(go.Scatter(x=equity.index, y=equity, name="Account equity"), row=1,col=1)
    fig.add_trace(go.Scatter(x=dd.index, y=dd, fill="tozeroy", name="Drawdown"), row=2,col=1)
    fig.add_trace(go.Bar(x=monthly.index, y=monthly.net_pnl, name="Net P&L",
        marker_color=np.where(monthly.net_pnl >= 0, "#14b8a6", "#ef4444")), row=3,col=1)
    fig.update_layout(template="plotly_dark", height=1000, title="ATHERENERG | INR 100,000 P&L")
    fig.write_html(out / "pnl_charts.html", include_plotlyjs=True, auto_open=False)

    metrics = pd.DataFrame([
        ("Starting capital", f"INR {cfg.capital:,.2f}"), ("Gross P&L (slippage already in fills)", f"INR {summary['gross_pnl']:,.2f}"),
        ("Modeled fees", f"INR {summary['fees']:,.2f}"), ("Net P&L", f"INR {summary['net_pnl']:,.2f}"),
        ("Ending capital", f"INR {summary['final_equity']:,.2f}"), ("Return", f"{summary['return_pct']:.2f}%"),
        ("Trades / wins / losses", f"{len(trades)} / {len(wins)} / {len(losses)}"),
        ("Trade win rate", f"{summary['win_rate_pct']:.2f}%"), ("Trade profit factor", f"{summary['profit_factor']:.3f}"),
        ("Maximum sampled drawdown", f"{summary['max_drawdown_pct']:.2f}% / INR {summary['max_drawdown_rupees']:,.2f}"),
        ("Average net P&L per trade", f"INR {summary['average_trade']:,.2f}"),
        ("Best / worst trade", f"INR {summary['best_trade']:,.2f} / {summary['worst_trade']:,.2f}"),
        ("Daily Sharpe / Sortino (rf=0)", f"{summary['daily_sharpe']:.3f} / {summary['daily_sortino']:.3f}")],
        columns=["Metric", "Result"])
    metrics.to_csv(out / "pnl_summary.csv", index=False)
    notes = [
        "Latest saved strategy: HA high breakout, BB(20,2), real-price VWAP; RVOL disabled.",
        "Confirmation on the next completed HA bar; buy the following real bar open.",
        "Initial signal HA-low stop; exit below prior completed BB middle; square off at 15:20.",
        "Whole shares, no leverage, 0.5% of current equity risk per trade (initially INR 500); max 3/day.",
        "Fees: 0.05% per side; adverse slippage: 0.05%; tick assumption INR 0.01.",
        "These are existing illustrative cost assumptions, not a verified brokerage/tax schedule.",
        "Only complete regular sessions used. No missing bars filled and no parameter optimization.",
        "Excluded: 2025-05-06 (71 bars), 2025-10-21 (13 bars), 2026-09-09 (19 bars).",
        "Latest CSV ends 2026-09-09 10:45; today's unfinished session is excluded.",
        "OpenStatz win rate/profit factor use daily returns; P&L report uses individual trades.",
        "OpenStatz drawdown uses day-end equity; main report samples every 5-minute close.",
        "Reference: same CSV ATHERENERG buy-and-hold before costs; NIFTY data not supplied.",
        "Corporate-action adjustment status is unverified. Results use the supplied prices as-is."]
    period = f"{d.index[0].date()} to {d.index[-1].date()} | {len(daily)} complete sessions | {len(d):,} bars"
    table = monthly.reset_index().rename(columns={"index":"month"})
    body = f"<h1>ATHERENERG P&amp;L report</h1><p>{period}</p>" + metrics.to_html(index=False)
    body += '<p><a href="interactive_tearsheet.html">Interactive tearsheet</a> | <a href="pnl_charts.html">P&amp;L charts</a> | <a href="tearsheet.pdf">Printable PDF</a> | <a href="trades.csv">Trade ledger</a> | <a href="ATHERENERG_heikin_ashi_5m.csv">Heikin Ashi candles</a> | <a href="real_vs_heikin_ashi.csv">Real vs HA candles</a></p>'
    body += "<h2>Monthly P&amp;L</h2>" + table.to_html(index=False, float_format=lambda x:f"{x:,.2f}")
    body += "<h2>Exit reasons</h2>" + by_exit.to_html(float_format=lambda x:f"{x:,.2f}")
    body += "<h2>Assumptions and data coverage</h2><ul>" + "".join(f"<li>{html.escape(n)}</li>" for n in notes) + "</ul>"
    body += "<p>" + html.escape(summary["validation"]) + "</p>"
    (out / "REPORT.html").write_text('<!doctype html><html><head><meta charset="utf-8"><title>ATHERENERG P&L</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#172033}table{border-collapse:collapse;width:100%;margin:24px 0}th,td{padding:10px;text-align:right;border-bottom:1px solid #dde2e9}th:first-child,td:first-child{text-align:left}a{color:#0369a1}li{margin:10px 0}</style></head><body>'+body+'</body></html>', encoding="utf-8")
    (out / "REPORT.md").write_text("# ATHERENERG P&L\n\n"+period+"\n\n"+metrics.to_markdown(index=False)+"\n\n"+"\n".join("- "+n for n in notes), encoding="utf-8")
    with PdfPages(out / "tearsheet.pdf") as pdf:
        page, ax = plt.subplots(figsize=(11.69, 8.27)); ax.axis("off")
        page.suptitle("ATHERENERG | INR 100,000 | P&L tearsheet", fontsize=18)
        ax.set_title(period, fontsize=10)
        tab = ax.table(cellText=metrics.values, colLabels=metrics.columns, loc="center", cellLoc="left", colWidths=[.57,.43])
        tab.auto_set_font_size(False); tab.set_fontsize(10); tab.scale(1, 2)
        pdf.savefig(page, bbox_inches="tight"); plt.close(page)
        page, axes = plt.subplots(3,1,figsize=(11.69,8.27), constrained_layout=True)
        axes[0].plot(equity.index, equity, color="#0284c7"); axes[0].set_title("Account equity / INR")
        axes[1].fill_between(dd.index, dd, 0, color="#e11d48", alpha=.7); axes[1].set_title("5-minute sampled drawdown / %")
        axes[2].bar(monthly.index, monthly.net_pnl, color=np.where(monthly.net_pnl>=0,"#0d9488","#e11d48"))
        axes[2].set_title("Monthly net P&L / INR"); axes[2].tick_params(axis="x", rotation=60)
        page.savefig(out / "tearsheet.png", dpi=140); pdf.savefig(page); plt.close(page)
        page, ax = plt.subplots(figsize=(11.69,8.27)); ax.axis("off"); ax.set_title("Monthly P&L", fontsize=16)
        formatted = table.copy()
        for c in formatted.select_dtypes(include="number").columns:
            formatted[c] = formatted[c].map(lambda v:f"{v:,.2f}")
        tab = ax.table(cellText=formatted.values,colLabels=formatted.columns,loc="center",cellLoc="right")
        tab.auto_set_font_size(False); tab.set_fontsize(9); tab.scale(1,1.7)
        pdf.savefig(page,bbox_inches="tight"); plt.close(page)
        page, ax = plt.subplots(figsize=(11.69,8.27)); ax.axis("off"); ax.set_title("Strategy assumptions and data coverage", fontsize=16)
        ax.text(0,.95,"\n\n".join(notes),va="top",fontsize=10,transform=ax.transAxes)
        pdf.savefig(page,bbox_inches="tight"); plt.close(page)
    archive = out.parent / (out.name + "_reports.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in out.iterdir():
            if p.is_file(): z.write(p, arcname=out.name + "/" + p.name)
        for p in [Path(__file__), Path(__file__).with_name("polars_data.py"),
                  Path(__file__).with_name("requirements.txt"), Path(strategy.__file__)]:
            z.write(p, arcname=out.name + "/" + p.name)
    print(json.dumps(summary, indent=2))
    print(f"REPORT: {out / 'REPORT.html'}\nBUNDLE: {archive}")


if __name__ == "__main__":
    main()
