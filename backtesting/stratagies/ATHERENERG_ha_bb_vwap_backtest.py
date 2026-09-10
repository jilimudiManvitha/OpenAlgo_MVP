"""CSV adapter and visual report for the unchanged Astra HA/BB/VWAP strategy.

Run with backtesting/.venv/Scripts/python.exe and --csv PATH.
Insufficient warmup produces a diagnostic report, never fabricated trades.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import ha_bb_vwap_strategy_astra as strategy


TRADE_COLUMNS = [
    "symbol", "signal_time", "confirmation_time", "entry_time", "entry", "stop",
    "target", "quantity", "signal_rvol", "exit_time", "exit", "reason",
    "gross_pnl", "costs", "net_pnl", "net_R", "equity_after",
]


def run(csv: Path, out: Path, symbol: str):
    out.mkdir(parents=True, exist_ok=True)
    cfg = strategy.Config()
    raw = pd.read_csv(csv)
    raw.columns = raw.columns.str.strip().str.lower()
    if "timestamp" not in raw:
        raw["timestamp"] = raw["date"].astype(str) + " " + raw["time"].astype(str)
    raw["symbol"] = symbol
    raw = raw[["timestamp", "symbol", "open", "high", "low", "close", "volume"]]
    normalized = out / "ATHERENERG_normalized_real_ohlcv.csv"
    raw.to_csv(normalized, index=False)
    raw = strategy.read_candles(normalized)
    # Preserve the supplied implementation, including its HA seed, BB population
    # deviation, real-price VWAP, daily RVOL, costs and execution semantics.
    d = strategy.indicators(raw, cfg)
    sessions = int(raw.timestamp.dt.date.nunique())
    eligible = sessions > cfg.volume_days
    bullish = d.ha_close > d.ha_open
    wickless = (d.ha_low - d.ha_open).abs() <= np.maximum(1e-8, abs(d.ha_open) * 1e-10)
    d["fresh_bb_cross"] = (d.ha_close > d.bb_upper) & (d.ha_close.shift() <= d.bb_upper.shift())
    d["rvol_available"] = d.rvol.notna()
    # Price-only diagnostics do not enter the simulation or create trades.
    diagnostic = d.copy()
    diagnostic["rvol"] = np.inf
    d["price_candidate"], d["price_confirmation"] = strategy.pattern_flags(diagnostic, cfg)
    d["bullish"] = bullish
    d["zero_lower_wick"] = wickless
    d["signal_close_ist"] = d.index + strategy.FIVE
    d.to_csv(out / "ATHERENERG_indicators_and_diagnostics.csv", index_label="timestamp")
    ha = d[["symbol", "ha_open", "ha_high", "ha_low", "ha_close", "volume"]].rename(
        columns={f"ha_{c}": c for c in ("open", "high", "low", "close")})
    ha.to_csv(out / "ATHERENERG_heikin_ashi_5m.csv", index_label="timestamp")

    log = io.StringIO()
    if eligible:
        with contextlib.redirect_stdout(log):
            trades = strategy.simulate({symbol: d}, cfg)
    else:
        trades = pd.DataFrame(columns=TRADE_COLUMNS)
        log.write(f"Backtest unavailable: {sessions} complete session(s); need at least {cfg.volume_days + 1}.\n")
    if trades.empty:
        trades = pd.DataFrame(columns=TRADE_COLUMNS)
    trades.to_csv(out / "ATHERENERG_trades.csv", index=False)
    equity = pd.Series(cfg.capital, index=d.index, dtype=float)
    for _, trade in trades.iterrows():
        active = (d.index >= trade.entry_time) & (d.index < trade.exit_time)
        equity.loc[active] += trade.quantity * (d.loc[active, "close"] - trade.entry)
        equity.loc[active] -= trade.quantity * (d.loc[active, "close"] + trade.entry) * cfg.fee_bps / 10000
        equity.loc[d.index >= trade.exit_time] += trade.net_pnl
    peak = equity.cummax().clip(lower=cfg.capital)
    drawdown = 100 * (equity / peak - 1)
    reference = 100 * (d.close / d.open.iloc[0] - 1)
    status = "Backtest completed" if eligible else "INSUFFICIENT HISTORY - full strategy not evaluated"
    summary = {
        "status": status, "source_csv": str(csv.resolve()),
        "source_sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        "strategy_file": str(Path(strategy.__file__).resolve()),
        "strategy_sha256": hashlib.sha256(Path(strategy.__file__).read_bytes()).hexdigest(),
        "symbol": symbol, "bars": len(d), "complete_sessions": sessions,
        "start_ist": str(d.index[0]), "end_bar_open_ist": str(d.index[-1]),
        "required_sessions": cfg.volume_days + 1,
        "rvol_valid_bars": int(d.rvol.notna().sum()),
        "bb_valid_bars": int(d.bb_upper.notna().sum()),
        "fresh_bb_crosses": int(d.fresh_bb_cross.sum()),
        "price_only_candidates": int(d.price_candidate.sum()),
        "price_only_confirmations": int(d.price_confirmation.sum()),
        "qualified_signals": int(d.signal.sum()),
        "qualified_confirmations": int(d.confirmation.sum()),
        "executed_trades": len(trades) if eligible else None,
        "initial_capital": cfg.capital,
        "net_pnl": float(equity.iloc[-1] - cfg.capital) if eligible else None,
        "return_pct": float((equity.iloc[-1] / cfg.capital - 1) * 100) if eligible else None,
        "max_drawdown_pct": float(-drawdown.min()) if eligible else None,
        "raw_open_to_final_close_pct_before_costs": float(reference.iloc[-1]),
        "config": {k: str(v) if hasattr(v, "isoformat") else v for k, v in vars(cfg).items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    pd.DataFrame({"equity": equity if eligible else np.nan,
                  "drawdown_pct": drawdown if eligible else np.nan,
                  "raw_price_change_pct": reference}).to_csv(out / "equity.csv", index_label="timestamp")

    x = d.index.strftime("%Y-%m-%d %H:%M").tolist()
    fig = make_subplots(rows=5, cols=1, shared_xaxes=True,
                        row_heights=[.20, .36, .14, .16, .14], vertical_spacing=.055,
                        subplot_titles=("Normal OHLC candles", "Heikin Ashi + BB(20, 2) + real-price VWAP",
                                        "Volume", "Cumulative RVOL / prior 20-session average",
                                        "Strategy return and drawdown"))
    for row, prefix, name in [(1, "", "Real OHLC"), (2, "ha_", "Heikin Ashi")]:
        fig.add_trace(go.Candlestick(x=x, open=d[prefix+"open"], high=d[prefix+"high"],
                                    low=d[prefix+"low"], close=d[prefix+"close"], name=name,
                                    increasing_line_color="#2dd4bf", decreasing_line_color="#fb7185"), row=row, col=1)
    for col, name, color in [("bb_upper", "Upper BB", "#a78bfa"), ("bb_middle", "BB SMA20", "#94a3b8"),
                             ("bb_lower", "Lower BB", "#a78bfa"), ("vwap", "Session VWAP (real HLC3)", "#fbbf24")]:
        fig.add_trace(go.Scatter(x=x, y=d[col], name=name, line=dict(color=color, width=1.5)), row=2, col=1)
    for col, name, color, marker in [
        ("price_candidate", "Price candidate only - RVOL unverified", "#fbbf24", "triangle-up-open"),
        ("price_confirmation", "Price confirmation only - RVOL unverified", "#38bdf8", "diamond-open"),
        ("signal", "Qualified signal", "#2dd4bf", "triangle-up"),
    ]:
        mask = d[col].to_numpy()
        fig.add_trace(go.Scatter(x=np.array(x)[mask], y=d.ha_high[mask] + 3, mode="markers", name=name,
                                marker=dict(symbol=marker, color=color, size=12)), row=2, col=1)
    for _, trade in trades.iterrows():
        for when, price, name, color, marker in [(trade.entry_time, trade.entry, "Entry", "#2dd4bf", "triangle-up"),
                                                 (trade.exit_time, trade.exit, "Exit", "#fb7185", "triangle-down")]:
            fig.add_trace(go.Scatter(x=[when.strftime("%Y-%m-%d %H:%M")], y=[price], mode="markers",
                                    name=name, marker=dict(color=color, symbol=marker, size=12)), row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=d.volume, name="Volume", marker_color="#64748b"), row=3, col=1)
    fig.add_trace(go.Scatter(x=x, y=d.rvol, name="RVOL", line_color="#38bdf8"), row=4, col=1)
    fig.add_hline(y=cfg.volume_multiple, line_dash="dash", line_color="#fbbf24", row=4, col=1)
    if eligible:
        fig.add_trace(go.Scatter(x=x, y=(equity/cfg.capital-1)*100, name="Strategy return %"), row=5, col=1)
        fig.add_trace(go.Scatter(x=x, y=drawdown, name="Drawdown %", fill="tozeroy"), row=5, col=1)
    else:
        fig.add_annotation(text="RVOL unavailable on all bars: 20 prior sessions missing", x=.5, y=.5,
                           xref="x4 domain", yref="y4 domain", showarrow=False, font_color="#fbbf24")
        fig.add_annotation(text="P&L / equity / drawdown: N/A - no eligible backtest period", x=.5, y=.5,
                           xref="x5 domain", yref="y5 domain", showarrow=False, font_color="#fbbf24")
    fig.update_layout(template="plotly_dark", height=1350, title=f"{symbol} | 5-minute candles | {status}",
                      margin=dict(t=110, b=100), legend=dict(orientation="h", y=-.09), hovermode="x unified")
    fig.update_xaxes(type="category", rangeslider_visible=False, nticks=12)
    fig.write_html(out / "ATHERENERG_visual_backtest.html", include_plotlyjs=True, auto_open=False)

    # A standalone PNG gives the user a preview without a browser or server.
    with plt.style.context("dark_background"):
        preview, axes = plt.subplots(3, 1, figsize=(17, 10), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1, 1]})
        xx = np.arange(len(d))
        for i, row in enumerate(d.itertuples()):
            color = "#2dd4bf" if row.ha_close >= row.ha_open else "#fb7185"
            axes[0].vlines(i, row.ha_low, row.ha_high, color=color, linewidth=.8)
            axes[0].add_patch(Rectangle((i-.32, min(row.ha_open, row.ha_close)), .64,
                                        max(abs(row.ha_close-row.ha_open), .01), color=color))
        for col, color in [("bb_upper", "#a78bfa"), ("bb_middle", "#94a3b8"),
                           ("bb_lower", "#a78bfa"), ("vwap", "#fbbf24")]:
            axes[0].plot(xx, d[col], label=col, color=color, linewidth=1.1)
        mask = d.price_candidate.to_numpy()
        axes[0].scatter(xx[mask], d.ha_high[mask]+3, marker="^", facecolors="none", edgecolors="#fbbf24",
                        s=85, label="Price candidate (RVOL unverified)")
        axes[0].legend(loc="upper left", fontsize=9)
        axes[0].set_ylabel("HA price / INR")
        axes[1].bar(xx, d.volume/1000, color="#64748b")
        axes[1].set_ylabel("Volume / 1,000")
        if eligible:
            axes[2].plot(xx, equity, color="#2dd4bf")
            axes[2].set_ylabel("Equity / INR")
        else:
            axes[2].text(.5, .55, "Backtest unavailable: only 1 session; 20 prior sessions required.\n"
                         "RVOL, P&L, win rate and drawdown cannot be evaluated.",
                         transform=axes[2].transAxes, ha="center", va="center", color="#fbbf24", fontsize=12)
            axes[2].set_yticks([])
        ticks = xx[::max(1, len(d)//12)]
        axes[2].set_xticks(ticks, [x[i] for i in ticks], rotation=25, ha="right", fontsize=8)
        for ax in axes:
            ax.grid(alpha=.12)
        preview.suptitle(f"{symbol} | {d.index[0].date()} | 5-minute Heikin Ashi + BB + VWAP\n{status}", fontsize=15)
        preview.tight_layout(rect=[0, 0, 1, .94])
        preview.savefig(out / "ATHERENERG_chart.png", dpi=150)
        plt.close(preview)

    report = f"""# {symbol}: Astra HA / BB / VWAP report

**{status}**

Input: `{csv}`. Data covers {d.index[0]} through {d.index[-1]} (bar-open timestamps),
{len(d)} candles and {sessions} complete regular session(s). The export filename date is not the candle date.

The original strategy functions perform the Heikin Ashi conversion and all indicators.
HA close = (O+H+L+C)/4; first HA open = (O+C)/2; subsequent HA open =
(previous HA open + previous HA close)/2. HA high/low include the real high/low and HA open/close.
Volume is unchanged. HA is seeded at the beginning of this file; preceding history could change early candles.
BB uses 20 HA closes and population standard deviation; the first 19 bars are warmup.
VWAP uses real HLC3 and resets each session. Execution uses real OHLC with the original next-bar rules.
Synthetic HA prices are unsuitable as executable prices; see
[TradingView's explanation](https://www.tradingview.com/support/solutions/43000481029-strategy-produces-unrealistic-results-on-non-standard-chart-types-heikin-ashi-renko-etc/).

The default cumulative-volume filter requires 20 prior full sessions. Available RVOL bars: {summary['rvol_valid_bars']}.
Minimum required input is 21 sessions (1,575 complete five-minute bars).
No missing history is filled, no filters are relaxed, and unavailable RVOL is not treated as zero.
Price-only markers are diagnostics and are not trade signals. Markers label the candle opening time;
their conditions become knowable five minutes later at candle close.

| Diagnostic | Count |
|---|---:|
| Valid BB bars | {summary['bb_valid_bars']} |
| Fresh HA-close upper-BB crosses | {summary['fresh_bb_crosses']} |
| Price-only signal candidates | {summary['price_only_candidates']} |
| Price-only confirmations | {summary['price_only_confirmations']} |
| Qualified signals | {summary['qualified_signals']} |
| Qualified confirmations | {summary['qualified_confirmations']} |

| Comparison | Strategy | ATHERENERG raw price reference |
|---|---|---|
| Return | {str(summary['return_pct'])+'%' if eligible else 'N/A: missing warmup'} | {reference.iloc[-1]:.4f}% |
| Max drawdown | {str(summary['max_drawdown_pct'])+'%' if eligible else 'N/A'} | Not calculated as a portfolio |
| Sharpe / Sortino / win rate / profit factor | Not reported | Not applicable |

The reference is the first real open to final real close, before costs, without share sizing.
It is not a strategy profit or a NIFTY benchmark. NIFTY data was not supplied; a benchmark or
annualized risk statistic would not repair the missing strategy warmup.
Initial capital assumption: INR {cfg.capital:,.0f}; risk {cfg.risk_fraction:.1%} per trade;
fees {cfg.fee_bps} bps per side; adverse slippage {cfg.slippage_bps} bps; no leverage.
These are the supplied script's illustrative defaults, not a verified broker charge schedule.

`ATHERENERG_visual_backtest.html` is interactive and self-contained, with real/HA candles,
BB/VWAP, volume, RVOL and performance panels. `ATHERENERG_chart.png` is the static preview.
`ATHERENERG_heikin_ashi_5m.csv` contains synthetic OHLC and must not be fed back into the strategy
as raw candles (that would convert twice). The normalized real OHLC CSV is the correct strategy input.
The trade CSV has headers even when no evaluable trades exist. See `summary.json` for status and hashes.

Engine output:
```
{log.getvalue().strip()}
```
"""
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Saved report and charts: {out.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--symbol", default="ATHERENERG")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] /
                        "stratagies_Backtest_output" / "ATHERENERG_HA_BB_VWAP")
    args = parser.parse_args()
    run(args.csv, args.out, args.symbol)
