"""Offline analytics for saved option replays; no application Reports integration."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .history import atomic_json


def daily_returns(curve, capital):
    values = pd.Series(curve["equity"].to_numpy(), index=pd.to_datetime(curve["timestamp"]))
    daily = values.groupby(values.index.date).last()
    daily.index = pd.to_datetime(daily.index)
    returns = daily.pct_change()
    returns.iloc[0] = daily.iloc[0] / capital - 1
    return daily, returns


def ratios(returns):
    std = returns.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2))
    return {
        "sharpe_daily_annualized": float(returns.mean() / std * np.sqrt(252)) if std > 0 else None,
        "sortino_daily_annualized": float(returns.mean() / downside * np.sqrt(252))
        if downside > 0
        else None,
    }


def build(folder):
    import openstatz as ostz

    folder = Path(folder)
    summaries = json.loads((folder / "summary.json").read_text())
    benchmark_frame = pd.read_csv(folder / "benchmark.csv")
    benchmark_daily, benchmark_returns = daily_returns(
        benchmark_frame.rename(columns={"close": "equity"}), benchmark_frame["close"].iloc[0]
    )
    benchmark_returns.name = "NIFTY 50 gross"
    bprices = benchmark_frame["close"]
    benchmark = {
        "return_pct": float((bprices.iloc[-1] / bprices.iloc[0] - 1) * 100),
        "max_drawdown_pct": float((bprices / bprices.cummax() - 1).min() * 100),
        **ratios(benchmark_returns),
    }
    benchmark_rows, links = [], []
    figures = {
        family: make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            subplot_titles=("Cumulative return on allocated capital", "Drawdown at daily close"),
        )
        for family in ("iron_condor", "delta", "premium")
    }
    colors = ["#60a5fa", "#fbbf24", "#34d399", "#f472b6"]
    for summary in summaries:
        name, path = summary["strategy"], summary["path"]
        output = folder / path / name
        curve = pd.read_csv(output / "equity.csv")
        daily, returns = daily_returns(curve, summary["capital"])
        returns.name = name + " / " + path + " (modeled)"
        summary.update(ratios(returns))
        values = pd.Series([summary["capital"], *curve["equity"].tolist()])
        summary["max_drawdown_pct"] = float((values / values.cummax() - 1).min() * 100)
        summary["trading_sessions"] = len(daily)
        trades = pd.read_csv(output / "trades.csv") if summary["closed_legs"] else pd.DataFrame()
        gains = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
        summary["closed_leg_win_rate_pct"] = float((gains > 0).mean() * 100) if len(gains) else None
        losses = -gains[gains < 0].sum()
        summary["closed_leg_profit_factor"] = (
            float(gains[gains > 0].sum() / losses) if losses > 0 else None
        )
        state = json.loads((output / "state.json").read_text())
        cycles = []
        if not trades.empty:
            for cycle, group in trades.groupby("cycle"):
                complete = not (state["legs"] and cycle == state["cycle"])
                cycles.append(
                    {
                        "cycle": int(cycle),
                        "closed_legs": len(group),
                        "complete": complete,
                        "closed_leg_net_pnl": float(group["net_pnl"].sum()),
                        "first_entry": group["entry_ts"].min(),
                        "last_exit": group["exit_ts"].max(),
                    }
                )
        pd.DataFrame(cycles).to_csv(output / "cycles.csv", index=False)
        cycle_pnl = pd.Series(
            [c["closed_leg_net_pnl"] for c in cycles if c["complete"]], dtype=float
        )
        cycle_loss = -cycle_pnl[cycle_pnl < 0].sum()
        summary.update(
            cycles_started=state["cycle"],
            completed_cycles=len(cycle_pnl),
            cycle_win_rate_pct=float((cycle_pnl > 0).mean() * 100) if len(cycle_pnl) else None,
            cycle_profit_factor=float(cycle_pnl[cycle_pnl > 0].sum() / cycle_loss)
            if cycle_loss > 0
            else None,
        )
        atomic_json(output / "summary.json", summary)
        benchmark_rows.append(
            {
                "strategy": name,
                "path": path,
                **{k: summary[k] for k in benchmark},
                **{"nifty_" + k: v for k, v in benchmark.items()},
            }
        )
        # Dashboard statistics use daily marks. The main summary retains finer
        # minute-end drawdowns; neither captures unobserved intraminute equity.
        aligned_benchmark = benchmark_returns.reindex(returns.index)
        if aligned_benchmark.isna().any():
            raise ValueError("Benchmark missing a strategy session")
        ostz.dashboard(
            returns,
            benchmark=aligned_benchmark,
            output=str(output / "tearsheet.html"),
            title=returns.name,
            open_browser=False,
        )
        links.append(
            f"<li><a href='{path}/{name}/tearsheet.html'>{name} / {path}</a> "
            f"(<a href='{path}/{name}/trades.csv'>legs</a>, <a href='{path}/{name}/cycles.csv'>cycles</a>, "
            f"<a href='{path}/{name}/equity.csv'>minute equity</a>)</li>"
        )
        family = next(f for f in figures if name.startswith(f + "_"))
        variant = name.removeprefix(family + "_")
        index = (2 if "positional" in variant else 0) + (1 if "next" in variant else 0)
        line = {"color": colors[index], "dash": "solid" if path == "OLHC" else "dot"}
        for row, series in (
            (1, (daily / summary["capital"] - 1) * 100),
            (2, (daily / daily.cummax().clip(lower=summary["capital"]) - 1) * 100),
        ):
            figures[family].add_trace(
                go.Scatter(
                    x=daily.index,
                    y=series,
                    name=variant + " " + path,
                    legendgroup=name + path,
                    showlegend=row == 1,
                    line=line,
                ),
                row=row,
                col=1,
            )
    atomic_json(folder / "summary.json", summaries)
    pd.DataFrame(summaries).to_csv(folder / "summary.csv", index=False)
    comparison = pd.DataFrame(benchmark_rows)
    comparison.to_csv(folder / "benchmark_comparison.csv", index=False)
    atomic_json(folder / "benchmark_stats.json", benchmark)
    sections = []
    for i, (family, figure) in enumerate(figures.items()):
        figure.update_layout(template="plotly_dark", height=700, title=family.replace("_", " "))
        figure.update_yaxes(ticksuffix="%")
        sections.append(figure.to_html(full_html=False, include_plotlyjs=True if i == 0 else False))
    target = folder / "index.html"
    html = target.read_text().split("<!-- analytics -->")[0]
    html += (
        "<!-- analytics --><h2>Daily analytics</h2><p>Sharpe/Sortino use daily returns, "
        "252 sessions/year and zero risk-free rate. Three months is a short sample. "
        "Dashboard win rates are daily. Summary cycle win rates cover only fully closed trades, "
        "including their adjustments; leg win rates count individual option legs. "
        "No-data profit factors are blank. Costs and margin remain illustrative.</p>"
        + comparison.to_html(index=False, float_format=lambda x: f"{x:,.3f}")
        + "".join(sections)
        + "<h2>Per-strategy downloads and dashboards</h2><ul>"
        + "".join(links)
        + "</ul>"
    )
    html = html.replace("<table", "<div style='max-width:100%;overflow-x:auto'><table").replace(
        "</table>", "</table></div>"
    )
    target.write_text(html)
    return {"dashboards": len(links), "benchmark": benchmark}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    print(json.dumps(build(parser.parse_args().folder)))
