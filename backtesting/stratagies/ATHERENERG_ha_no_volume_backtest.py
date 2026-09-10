"""Backtest supplied HA candles with Astra rules, RVOL disabled, and real fills."""
from __future__ import annotations

import argparse
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


def run(ha_path, real_path, out, breakout_source="close", exit_mode="target"):
    out.mkdir(parents=True, exist_ok=True)
    cfg = strategy.Config(volume_filter=False, breakout_source=breakout_source, exit_mode=exit_mode)
    raw = strategy.read_candles(real_path)
    symbols = raw.symbol.unique()
    if len(symbols) != 1:
        raise ValueError("This visual report requires one symbol")
    symbol = symbols[0]
    ha = pd.read_csv(ha_path)
    ha["timestamp"] = pd.DatetimeIndex([strategy.ist_timestamp(v) for v in ha.timestamp])
    ha = ha.set_index("timestamp").sort_index()
    d = strategy.indicators(raw, cfg)
    if not ha.index.equals(d.index) or not ha.symbol.eq(symbol).all():
        raise ValueError("HA and real candles must have identical timestamps and symbols")
    # Read the user's already converted OHLC; never convert that file a second time.
    # Verify correspondence to the real data used for VWAP and trade execution.
    for col in ["open", "high", "low", "close"]:
        np.testing.assert_allclose(ha[col], d[f"ha_{col}"], rtol=1e-12)
        d[f"ha_{col}"] = ha[col]
    d["bb_middle"] = d.ha_close.rolling(cfg.bb_length).mean()
    dev = d.ha_close.rolling(cfg.bb_length).std(ddof=0)
    d["bb_upper"] = d.bb_middle + cfg.bb_std * dev
    d["bb_lower"] = d.bb_middle - cfg.bb_std * dev
    d["bb_exit_level"] = d.bb_middle.shift(1)
    d["signal"], d["confirmation"] = strategy.pattern_flags(d, cfg)
    d["signal_stop"] = d.ha_low.shift()
    trades = strategy.simulate({symbol: d}, cfg)
    if trades.empty:
        raise ValueError("No trades under the unchanged entry/exit rules with RVOL disabled")
    trades.to_csv(out / "trades.csv", index=False)
    d.to_csv(out / "indicators.csv", index_label="timestamp")
    equity = pd.Series(cfg.capital, index=d.index)
    for t in trades.itertuples():
        active = (d.index >= t.entry_time) & (d.index < t.exit_time)
        equity.loc[active] += t.quantity * (d.loc[active, "close"] - t.entry)
        equity.loc[active] -= t.quantity * (d.loc[active, "close"] + t.entry) * cfg.fee_bps / 10000
        equity.loc[d.index >= t.exit_time] += t.net_pnl
    dd = (equity / equity.cummax().clip(lower=cfg.capital) - 1) * 100
    pd.DataFrame({"equity": equity, "drawdown_pct": dd}).to_csv(out / "equity.csv")
    summary = dict(symbol=symbol, volume_filter=False, breakout_source=breakout_source, exit_mode=exit_mode, ha_source=str(ha_path.resolve()),
                   real_source=str(real_path.resolve()), signals=int(d.signal.sum()),
                   confirmations=int(d.confirmation.sum()), trades=len(trades),
                   capital=cfg.capital, risk_budget=cfg.capital*cfg.risk_fraction,
                   planned_reward_to_risk=2 if exit_mode=="target" else None, net_pnl=float(trades.net_pnl.sum()),
                   final_equity=float(equity.iloc[-1]), return_pct=float((equity.iloc[-1]/cfg.capital-1)*100),
                   max_drawdown_pct=float(-dd.min()), win_rate_pct=float((trades.net_pnl>0).mean()*100))
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    x = d.index.strftime("%Y-%m-%d %H:%M").tolist()
    colors = {"bb_upper": "#a78bfa", "bb_middle": "#94a3b8", "bb_lower": "#a78bfa", "vwap": "#fbbf24"}
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.065,
                        row_heights=[.44,.28,.16,.12],
                        subplot_titles=("Heikin Ashi signals + trade levels", "Real candles: execution and stop/target checks",
                                        "Equity after costs (INR)", "Drawdown (%)"))
    for panel, prefix in [(1,"ha_"),(2,"")]:
        fig.add_trace(go.Candlestick(x=x, open=d[prefix+"open"], high=d[prefix+"high"],
                                    low=d[prefix+"low"], close=d[prefix+"close"],
                                    increasing_line_color="#2dd4bf", decreasing_line_color="#fb7185",
                                    name="HA" if prefix else "Real OHLC"), row=panel, col=1)
    for col, color in colors.items():
        fig.add_trace(go.Scatter(x=x,y=d[col],name=col,line=dict(color=color,width=1.4)),row=1,col=1)
    for t in trades.itertuples():
        levels = [(t.entry,"Entry","#38bdf8"),(t.stop,"Initial stop","#fb7185")]
        if exit_mode == "target":
            levels.append((t.target,"Target (2R)","#2dd4bf"))
        active = (d.index >= t.entry_time) & (d.index <= t.exit_time)
        for panel in [1,2]:
            if exit_mode == "bb_middle":
                fig.add_trace(go.Scatter(x=np.array(x)[active],y=d.bb_exit_level[active].clip(lower=t.stop),
                                        name="Active exit level: prior BB / initial stop",showlegend=panel==1,
                                        line=dict(color="#2dd4bf",dash="dash",shape="hv")),row=panel,col=1)
            for price, label, color in levels:
                fig.add_trace(go.Scatter(x=[t.entry_time.strftime("%Y-%m-%d %H:%M"),t.exit_time.strftime("%Y-%m-%d %H:%M")],
                                        y=[price,price],mode="lines",line=dict(color=color,dash="dash"),
                                        name=f"{label}: {price:.2f}",showlegend=panel==1),row=panel,col=1)
            for stamp, price, label, color, marker in [
                (t.signal_time,d.loc[t.signal_time,"ha_high"],"Signal", "#fbbf24","circle-open"),
                (t.confirmation_time,d.loc[t.confirmation_time,"ha_high"],"Confirmation", "#a78bfa","diamond-open"),
                (t.entry_time,t.entry,"BUY", "#38bdf8","triangle-up"),
                (t.exit_time,t.exit,f"EXIT: {t.reason}", "#fb7185","triangle-down")]:
                if panel==2 and label in ["Signal","Confirmation"]:
                    continue
                fig.add_trace(go.Scatter(x=[stamp.strftime("%Y-%m-%d %H:%M")],y=[price],mode="markers",
                                        name=label,showlegend=panel==1,
                                        marker=dict(color=color,symbol=marker,size=13)),row=panel,col=1)
    fig.add_trace(go.Scatter(x=x,y=equity,name="Equity",line_color="#38bdf8"),row=3,col=1)
    fig.add_trace(go.Scatter(x=x,y=dd,name="Drawdown",fill="tozeroy",line_color="#fb7185"),row=4,col=1)
    fig.update_xaxes(type="category",rangeslider_visible=False,nticks=12)
    fig.update_layout(template="plotly_dark",height=1250,hovermode="x unified",
                      title=f"{symbol} | HA {breakout_source} breakout | {exit_mode} exit | RVOL disabled | Net P&L INR {summary['net_pnl']:.2f}",
                      legend=dict(orientation="h",y=-.10),margin=dict(t=90,b=150))
    fig.write_html(out / "trade_chart.html",include_plotlyjs=True,auto_open=False)

    # Focus the static image on the trade; HTML retains the full session.
    lo = max(0, d.index.get_loc(trades.signal_time.min())-6)
    hi = min(len(d), d.index.get_loc(trades.exit_time.max())+5)
    with plt.style.context("dark_background"):
        figure, axes = plt.subplots(3,1,figsize=(16,11),sharex=True,gridspec_kw={"height_ratios":[3,2,1]})
        for ax, prefix in [(axes[0],"ha_"),(axes[1],"")]:
            for i in range(lo,hi):
                row=d.iloc[i]; o,h,l,c=[row[prefix+k] for k in ["open","high","low","close"]]
                color="#2dd4bf" if c>=o else "#fb7185"
                ax.vlines(i,l,h,color=color,lw=1)
                ax.add_patch(Rectangle((i-.3,min(o,c)),.6,max(abs(c-o),.01),color=color))
        for col,color in colors.items():
            axes[0].plot(np.arange(lo,hi),d[col].iloc[lo:hi],label=col,color=color,lw=1.2)
        for t in trades.itertuples():
            a,b=d.index.get_loc(t.entry_time),d.index.get_loc(t.exit_time)
            levels = [(t.entry,"Entry","#38bdf8"),(t.stop,"Initial stop","#fb7185")]
            if exit_mode == "target":
                levels.append((t.target,"Target 2R","#2dd4bf"))
            for ax in axes[:2]:
                if exit_mode == "bb_middle":
                    ax.step(np.arange(a,b+1),d.bb_exit_level.iloc[a:b+1].clip(lower=t.stop),
                            where="post",color="#2dd4bf",ls="--",lw=1.7,label="Active exit (prior BB)")
                for price,label,color in levels:
                    ax.hlines(price,a,b+1,colors=color,linestyles="--",lw=1.4)
                    ax.text(b+1.2,price,f"{label} {price:.2f}",color=color,fontsize=10,va="center",
                            bbox=dict(facecolor="black",edgecolor="none",alpha=.85,pad=2))
                ax.scatter([a,b],[t.entry,t.exit],c=["#38bdf8","#fb7185"],s=85,zorder=5)
                ax.annotate(f"BUY {t.entry_time:%H:%M}\n{t.quantity} shares",(a,t.entry),xytext=(12,-50),
                            textcoords="offset points",color="#38bdf8",arrowprops=dict(arrowstyle="->",color="#38bdf8"))
                ax.annotate(f"{t.reason.upper()} {t.exit_time:%H:%M} bar\nFill {t.exit:.2f}",(b,t.exit),xytext=(-90,-50),
                            textcoords="offset points",color="#fb7185",arrowprops=dict(arrowstyle="->",color="#fb7185"))
            for stamp,label,offset in [(t.signal_time,"Signal",(-65,35)),(t.confirmation_time,"Confirm",(-15,60))]:
                i=d.index.get_loc(stamp)
                axes[0].annotate(f"{label} {stamp:%H:%M}",(i,d.loc[stamp,"ha_high"]),xytext=offset,
                                 textcoords="offset points",color="#fbbf24",arrowprops=dict(arrowstyle="->",color="#fbbf24"))
        axes[0].set_title("Heikin Ashi + BB(20, 2) + session VWAP",loc="left")
        axes[0].legend(loc="upper left",fontsize=9)
        axes[1].set_title("Real OHLC used for entry and exit",loc="left")
        for ax in axes[:2]:
            ax.margins(y=.25)
        axes[2].plot(np.arange(lo,hi),equity.iloc[lo:hi],color="#38bdf8")
        axes[2].axhline(cfg.capital,color="#94a3b8",ls="--",lw=.7)
        axes[2].set_ylabel("Equity / INR")
        axes[2].set_xticks(np.arange(lo,hi,2),d.index[lo:hi:2].strftime("%H:%M"))
        axes[2].set_xlabel("29 June 2026 | IST | candle opening timestamps")
        for ax in axes:
            ax.grid(alpha=.15)
            ax.set_xlim(lo-.7,hi+.5)
        exit_label = "BB middle exit; no fixed target" if exit_mode == "bb_middle" else "Planned risk/reward 1:2"
        figure.suptitle(f"ATHERENERG | HA {breakout_source} breakout | Volume filter OFF | {exit_label}\n"
                        f"Net P&L INR {summary['net_pnl']:.2f} | Final equity INR {summary['final_equity']:.2f}",fontsize=16)
        figure.tight_layout(rect=[0,0,1,.94])
        figure.savefig(out / "trade_chart.png",dpi=150)
        plt.close(figure)
    table = trades[["signal_time","confirmation_time","entry_time","entry","stop","target","quantity",
                    "exit_time","exit","reason","gross_pnl","costs","net_pnl"]].to_string(index=False)
    exit_rules = ("No fixed profit target. During each real candle, exit if its open or low falls strictly below "
                  "the previous completed candle's BB middle (SMA20 of HA close). Gap exits fill at the real "
                  "open; other breaks fill at the prior BB middle, both with adverse slippage and tick rounding. "
                  "The band is followed even if it declines; it is not ratcheted to its historical maximum. "
                  "The initial stop remains protective. If both levels are crossed intrabar, the higher "
                  "level is encountered first. No fixed reward/risk applies to this exit mode."
                  if exit_mode == "bb_middle" else
                  "Target: entry + 2*(entry-stop), rounded up. Exit at stop/target; stop takes priority "
                  "if both levels touch in one bar. Planned risk/reward is 1:2 before costs.")
    report = f"""# ATHERENERG: volume filter disabled

The supplied Heikin Ashi CSV supplies signal OHLC. Matching real OHLC supplies VWAP,
entry fills and stop/target checks. The HA file is validated against its real source.
Only RVOL eligibility is disabled. The first 19 candles still warm up BB(20, 2).

Entry: bullish HA candle with no lower wick makes a fresh HA {breakout_source} cross above the upper BB,
and its HA {breakout_source} exceeds VWAP. A fresh cross means the prior HA {breakout_source} was at or
below its upper BB. The immediate next bullish, wickless HA candle must close above the signal high;
its HA {breakout_source} must exceed the upper BB and VWAP, and its real close must exceed VWAP.
Buy the following real candle's open plus slippage. Conditions are evaluated on completed bars.
Initial stop: signal HA low rounded down. {exit_rules}
Square off at the 15:20 real open. Entry window ends at 15:00. At most three trades daily.

Assumptions: INR 10,000 capital, 0.5% risk budget (INR 50), integer shares, no leverage,
5 bps fees per side and 5 bps adverse slippage, tick rounding INR 0.01, all from the strategy defaults.
Actual loss can exceed 1R after costs and stop slippage.

```
{table}
```

Net P&L: INR {summary['net_pnl']:.2f}; final equity: INR {summary['final_equity']:.2f};
return: {summary['return_pct']:.4f}%; sampled bar-close drawdown: {summary['max_drawdown_pct']:.4f}%.
Signal/confirmation labels identify bar opens; their conditions are known five minutes later.
Intrabar exit timestamps identify the five-minute interval, not the exact second.
This single-session sample does not establish strategy performance.

Open trade_chart.html for the interactive full-session chart or trade_chart.png for the trade close-up.
"""
    (out / "REPORT.md").write_text(report,encoding="utf-8")
    print(json.dumps(summary,indent=2))
    print(f"Charts and report: {out.resolve()}")


if __name__ == "__main__":
    base=Path(__file__).resolve().parents[1]/"stratagies_Backtest_output"/"ATHERENERG_HA_BB_VWAP"
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ha-csv",type=Path,default=base/"ATHERENERG_heikin_ashi_5m.csv")
    parser.add_argument("--real-csv",type=Path,default=base/"ATHERENERG_normalized_real_ohlcv.csv")
    parser.add_argument("--out",type=Path,default=base/"no_volume_filter")
    parser.add_argument("--breakout-source",choices=["close","high"],default="close")
    parser.add_argument("--exit-mode",choices=["target","bb_middle"],default="target")
    args=parser.parse_args()
    run(args.ha_csv,args.real_csv,args.out,args.breakout_source,args.exit_mode)
