"""Build a single offline comparison dashboard from completed replay ledgers."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
from plotly.offline import get_plotlyjs

from .history import atomic_json
from .reporting import daily_returns


def build(folder):
    folder = Path(folder)
    metadata = json.loads((folder / "verification.json").read_text())
    summaries = json.loads((folder / "summary.json").read_text())
    inputs = {}

    def read(name, csv=False):
        source = folder / name
        inputs[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        return pd.read_csv(source) if csv else json.loads(source.read_text())

    read("verification.json")
    read("summary.json")
    benchmark = read("benchmark.csv", True)
    bench_daily, _ = daily_returns(
        benchmark.rename(columns={"close": "equity"}), benchmark["close"].iloc[0]
    )
    scenarios = {}
    total_curves = {}
    for original in summaries:
        row = dict(original)
        prefix = f"{row['path']}/{row['strategy']}"
        state = read(prefix + "/state.json")
        trades = read(prefix + "/trades.csv", True) if row["closed_legs"] else pd.DataFrame()
        curve = read(prefix + "/equity.csv", True)
        total_curves.setdefault(row["path"], []).append(curve.set_index("timestamp")["equity"])
        breakdown = None
        if metadata.get("broker") not in (None, "legacy"):
            from services.report_brokerage import COMPONENTS, order_cost, tariff

            rates = tariff(metadata["broker"])
            breakdown = dict.fromkeys(COMPONENTS, 0.0)
            executions = []
            for trade in trades.to_dict("records"):
                executions.extend(
                    (
                        (
                            trade["entry"],
                            trade["side"],
                            trade["quantity"],
                            trade["entry_ts"],
                            trade["entry_fee"],
                        ),
                        (
                            trade["exit"],
                            -trade["side"],
                            trade["quantity"],
                            trade["exit_ts"],
                            trade["exit_fee"],
                        ),
                    )
                )
            executions.extend(
                (leg["entry"], leg["side"], leg["quantity"], leg["entry_ts"], leg["entry_fee"])
                for leg in state["legs"]
            )
            for price, side, qty, stamp, fee in executions:
                parts = order_cost(
                    price * qty, "BUY" if side > 0 else "SELL", "NFO", "options", stamp[:10], rates
                )
                assert abs(sum(parts.values()) - fee) < 0.011
                for key, value in parts.items():
                    breakdown[key] += value
            assert abs(sum(breakdown.values()) - row["fees"]) < 0.011
        row.update(
            gross_pnl=row["net_pnl"] + row["fees"],
            charge_breakdown=breakdown,
            unrealized_pnl=row["net_pnl"] - row["realized_pnl"],
        )
        row["contracts"] = []
        if not trades.empty:
            for symbol, group in trades.groupby("symbol"):
                row["contracts"].append(
                    {
                        "symbol": symbol,
                        "trades": len(group),
                        "wins": int((group.net_pnl > 0).sum()),
                        "losses": int((group.net_pnl < 0).sum()),
                        "gross": float(group.gross_pnl.sum()),
                        "charges": float((group.entry_fee + group.exit_fee).sum()),
                        "net": float(group.net_pnl.sum()),
                    }
                )
        cycles = []
        if not trades.empty:
            for cycle, group in trades.groupby("cycle", sort=True):
                cycles.append(
                    {
                        "cycle": int(cycle),
                        "complete": not (state["legs"] and cycle == state["cycle"]),
                        "pnl": float(group["net_pnl"].sum()),
                        "entry": group["entry_ts"].min(),
                        "exit": group["exit_ts"].max(),
                        "legs": len(group),
                    }
                )
        completed = pd.Series([c["pnl"] for c in cycles if c["complete"]], dtype=float)
        wins, losses = completed[completed > 0], completed[completed < 0]
        profit, loss = float(wins.sum()), float(-losses.sum())
        win_rate = 100 * len(wins) / len(completed) if len(completed) else None
        factor = profit / loss if loss else None
        assert len(completed) == row["completed_cycles"]
        if win_rate is not None:
            assert abs(win_rate - row["cycle_win_rate_pct"]) < 1e-8
        if factor is not None:
            assert abs(factor - row["cycle_profit_factor"]) < 1e-8
        daily, _ = daily_returns(curve, row["capital"])
        month_end = daily.groupby(daily.index.strftime("%Y-%m")).last()
        monthly = month_end.diff()
        monthly.iloc[0] = month_end.iloc[0] - row["capital"]
        assert abs(monthly.sum() - row["net_pnl"]) < 0.01
        row.update(
            winning_profit=profit,
            losing_loss=loss,
            wins=len(wins),
            losses=len(losses),
            breakeven=int((completed == 0).sum()),
            win_rate=win_rate,
            profit_factor=factor,
            profit_factor_display="Infinity"
            if not loss and profit
            else "N/A"
            if not loss
            else None,
            average_win=float(wins.mean()) if len(wins) else None,
            average_loss=float(-losses.mean()) if len(losses) else None,
            payoff_ratio=float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
            expectancy=float(completed.mean()) if len(completed) else None,
            best_trade=float(completed.max()) if len(completed) else None,
            worst_trade=float(completed.min()) if len(completed) else None,
            completed_trade_pnl=float(completed.sum()),
            open_cycles=int(bool(state["legs"])),
            cycles=cycles,
            dates=daily.index.strftime("%Y-%m-%d").tolist(),
            returns=((daily / row["capital"] - 1) * 100).tolist(),
            drawdowns=((daily / daily.cummax().clip(lower=row["capital"]) - 1) * 100).tolist(),
            monthly=monthly.to_dict(),
        )
        scenarios.setdefault(row["path"], []).append(row)
    overall = {}
    for path, curves in total_curves.items():
        combined = pd.concat(curves, axis=1, join="inner").sum(axis=1)
        capital = sum(r["capital"] for r in scenarios[path])
        values = pd.Series([capital, *combined.tolist()])
        overall[path] = {
            "max_drawdown_inr": float((values - values.cummax()).min()),
            "common_mark_minutes": len(combined),
        }
    payload = {
        "start": metadata["start"],
        "end": metadata["end"],
        "sessions": metadata["trading_sessions"],
        "costs": metadata["costs"],
        "overall": overall,
        "scenarios": scenarios,
        "benchmark": {
            **read("benchmark_stats.json"),
            "dates": bench_daily.index.strftime("%Y-%m-%d").tolist(),
            "returns": ((bench_daily / benchmark["close"].iloc[0] - 1) * 100).tolist(),
        },
    }
    # JSON must stay valid JavaScript and must not terminate the data script tag.
    encoded = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("dashboard.html")
    html = template.read_text().replace("__PLOTLY__", get_plotlyjs()).replace("__DATA__", encoded)
    output = folder / "combined_dashboard.html"
    output.write_text(html)
    flat = [
        {
            k: v
            for k, v in r.items()
            if k
            not in {
                "cycles",
                "dates",
                "returns",
                "drawdowns",
                "monthly",
                "contracts",
                "charge_breakdown",
            }
        }
        for rows in scenarios.values()
        for r in rows
    ]
    pd.DataFrame(flat).to_csv(folder / "combined_metrics.csv", index=False)
    atomic_json(folder / "combined_dashboard_data.json", payload)
    audit = {
        "scenarios": len(flat),
        "strategies_per_path": {p: len(r) for p, r in scenarios.items()},
        "checks": "Cycle win rates/counts/profit factors match replay summaries; monthly marked P&L reconciles to total.",
        "input_hashes": inputs,
        "generator_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), template)
        },
        "dashboard_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    atomic_json(folder / "combined_dashboard_verification.json", audit)
    return {"dashboard": str(output), "scenarios": len(flat)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    print(json.dumps(build(parser.parse_args().folder), indent=2))
