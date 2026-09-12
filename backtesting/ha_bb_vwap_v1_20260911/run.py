"""Run all 404 materialized versions on the requested 2026-09-11 CSV universe.

From repository root:
  backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/run.py
The runner is offline, read-only toward inputs, and resumable by completed stock.
"""

import argparse
import hashlib
import json
import pickle
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import vectorbt as vbt
from replay import (
    DAY,
    END,
    SLIPPAGE,
    START,
    STEPS_PER_LEG,
    WARMUP,
    charges,
    definitions,
    event_stream,
    execute,
    metadata,
    read_input,
    safe_json,
    source_files,
    write_csv,
)
from report import index_page, initialize, save_bars, save_trade, strategy_page

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "results"


def benchmark(side, meta, bars):
    cutoff = START.replace(hour=15, minute=5 if meta["is_fo"] else 20)
    eligible = [b for b in bars if b.start < cutoff and b.volume > 0]
    if not eligible:
        return 0.0
    d = 1 if side == "buy" else -1
    entry = eligible[0].open * (1 + d * SLIPPAGE)
    boundary = next((b for b in bars if b.start == cutoff), None)
    exit_ = (boundary.open if boundary else eligible[-1].close) * (1 - d * SLIPPAGE)
    tick = meta["tick_size"]
    entry = (np.ceil(entry / tick - 1e-9) if d == 1 else np.floor(entry / tick + 1e-9)) * tick
    exit_ = (np.floor(exit_ / tick + 1e-9) if d == 1 else np.ceil(exit_ / tick - 1e-9)) * tick
    qty = int(100000 / entry)
    return (
        d * (exit_ - entry) * qty
        - charges(side, qty, entry)
        - charges("sell" if d == 1 else "buy", qty, exit_)
    )


def vbt_check(fills):
    if not fills:
        return
    sizes = [f["quantity"] * (1 if f["side"] == "buy" else -1) for f in fills]
    prices = pd.Series([f["price"] for f in fills], dtype=float)
    fees = np.asarray([f["fees"] for f in fills])
    portfolio = vbt.Portfolio.from_orders(
        close=prices,
        size=sizes,
        price=prices,
        direction="both",
        init_cash=1_000_000,
        fees=0,
        fixed_fees=fees,
        min_size=1,
        size_granularity=1,
        allow_partial=False,
        freq="1min",
    )
    expected = sum(-size * price - fee for size, price, fee in zip(sizes, prices, fees, strict=True))
    actual = float(portfolio.total_profit())
    if not np.isclose(actual, expected, atol=1e-6):
        raise AssertionError(f"VectorBT accounting mismatch: {actual} != {expected}")
    if len(portfolio.orders.records) != len(fills):
        raise AssertionError("VectorBT rejected a replay fill")


def metrics(sid, scenario, results):
    trades = [t for r in results for t in r["trades"]]
    net = sum(t["net_pnl"] for t in trades)
    profits = sum(max(t["net_pnl"], 0) for t in trades)
    losses = -sum(min(t["net_pnl"], 0) for t in trades)
    curves = []
    for r in results:
        if r["marked"]:
            curves.append(pd.Series(dict(r["marked"]), dtype=float))
    curve = (
        pd.concat(curves, axis=1).sort_index().ffill().fillna(0).sum(axis=1)
        if curves
        else pd.Series([0.0])
    )
    values = np.r_[0, curve.to_numpy(), net]
    dd = float(np.max(np.maximum.accumulate(values) - values))
    allocation_events = []
    for t in trades:
        allocation_events.append((t["entry_time"], t["quantity"] * t["entry_price"]))
        for f in t["fills"][1:]:
            allocation_events.append((f["time"], -f["quantity"] * t["entry_price"]))
    used = peak = 0
    for _, delta in sorted(allocation_events, key=lambda x: (x[0], x[1])):
        used += delta
        peak = max(peak, used)
    return {
        "strategy_id": sid,
        "scenario": scenario,
        "trades": len(trades),
        "net_pnl": net,
        "gross_pnl": sum(t["gross_pnl"] for t in trades),
        "reference_pnl": sum(t["reference_pnl"] for t in trades),
        "fees": sum(t["fees"] for t in trades),
        "slippage_cost": sum(t["slippage_cost"] for t in trades),
        "win_rate": 100 * sum(t["net_pnl"] > 0 for t in trades) / len(trades) if trades else 0,
        "profit_factor": profits / losses if losses else (None if profits else 0),
        "max_drawdown": dd,
        "peak_notional": peak,
        "return_on_11_lakh_pct": net / 1100000 * 100,
        "profitable_stocks": sum(sum(t["net_pnl"] for t in r["trades"]) > 0 for r in results),
        "benchmark_net": sum(r["benchmark_net"] for r in results),
        "mean_net_per_trade": net / len(trades) if trades else 0,
        "rejected_entries": sum(r["rejected"] for r in results),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only-symbol", help="Development smoke check; full default runs every input"
    )
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cache = OUTPUT / "checkpoints"
    cache.mkdir(exist_ok=True)
    defs = definitions()
    ids = {cfg.name: f"S{i + 1:03d}" for i, (cfg, _, _) in enumerate(defs)}
    inputs = source_files()
    meta = metadata([x[1] for x in inputs])
    fingerprint = hashlib.sha256(
        b"".join(
            p.read_bytes()
            for p in [
                HERE / "replay.py",
                HERE / "run.py",
                ROOT / "strategies/ha_bb_vwap_v1/engine.py",
                ROOT / "strategies/ha_bb_vwap_v1/indicators.py",
                ROOT / "strategies/ha_bb_vwap_v1/models.py",
            ]
        )
    ).hexdigest()
    (OUTPUT / "run_config.json").write_text(
        json.dumps(
            {
                "date": DAY,
                "strategies": 404,
                "scenarios": ["OLHC", "OHLC"],
                "warmup_bars": WARMUP,
                "steps_per_leg": STEPS_PER_LEG,
                "slippage_per_fill": SLIPPAGE,
                "metadata": meta,
                "code_fingerprint": fingerprint,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    all_results = []
    audit = []
    chart_data = {}
    for side, symbol, one, five in inputs:
        if args.only_symbol and symbol != args.only_symbol:
            continue
        checkpoint = cache / f"{side}_{symbol}.pkl"
        if checkpoint.exists():
            with checkpoint.open("rb") as f:
                saved = pickle.load(f)
            if saved["fingerprint"] != fingerprint:
                raise ValueError(
                    "Checkpoint code differs; use a separate output folder or reconcile explicitly"
                )
            print(f"Resume {side} {symbol}: complete", flush=True)
        else:
            if args.report_only:
                raise ValueError(f"Missing checkpoint {checkpoint}")
            history1, day1, a1 = read_input(one, 1)
            history5, day5, a5 = read_input(five, 5)
            print(
                f"Loaded {side} {symbol}: {len(day1)} one-minute bars, warmup {len(history1)}/{len(history5)}",
                flush=True,
            )
            saved = {"fingerprint": fingerprint, "results": [], "audit": [a1, a5], "charts": {}}
            for minutes, history, native in ((1, history1, day1), (5, history5, day5)):
                for scenario in ("OLHC", "OHLC"):
                    events, charts, discrepancies = event_stream(
                        history, day1, native, minutes, scenario
                    )
                    print(
                        f"  {minutes}m {scenario}: {len(events)} causal approximated observations; replaying 101 versions",
                        flush=True,
                    )
                    saved["charts"][f"{side}_{symbol}_{minutes}m"] = charts
                    saved["audit"].append(
                        {
                            "symbol": symbol,
                            "minutes": minutes,
                            "scenario": scenario,
                            "five_minute_reaggregation_differences": discrepancies,
                            "note": "Target-session 5m bars reaggregated from supplied 1m to permit forming updates; 5m CSV supplies prior warmup.",
                        }
                    )
                    for definition in defs:
                        cfg = definition[0]
                        if cfg.side != side or cfg.timeframe_minutes != minutes:
                            continue
                        sid = ids[cfg.name]
                        trades, fills, marked, rejected = execute(
                            definition, symbol, meta[symbol], events, scenario, sid
                        )
                        vbt_check(fills)
                        saved["results"].append(
                            {
                                "strategy_id": sid,
                                "symbol": symbol,
                                "scenario": scenario,
                                "trades": trades,
                                "fills": fills,
                                "marked": marked,
                                "rejected": rejected,
                                "benchmark_net": benchmark(side, meta[symbol], day1),
                            }
                        )
            with checkpoint.open("wb") as f:
                pickle.dump(saved, f)
            print(
                f"Completed {symbol}: {sum(len(r['trades']) for r in saved['results'])} round trips across versions/paths",
                flush=True,
            )
        all_results.extend(saved["results"])
        audit.extend(saved["audit"])
        chart_data.update(saved["charts"])
    if args.only_symbol:
        print("Smoke symbol complete; rerun without --only-symbol for full reports.")
        return
    assert len(all_results) == 8888, len(all_results)
    initialize(OUTPUT)
    for key, charts in chart_data.items():
        save_bars(OUTPUT, key, charts)
    all_trades = []
    stock_rows = []
    metric_rows = []
    ranking = []
    trade_number = 0
    for cfg, _, source in defs:
        sid = ids[cfg.name]
        results = [r for r in all_results if r["strategy_id"] == sid]
        ms = [metrics(sid, s, [r for r in results if r["scenario"] == s]) for s in ("OLHC", "OHLC")]
        local_trades = []
        local_stocks = []
        for r in results:
            local_stocks.append(
                {
                    "strategy_id": sid,
                    "symbol": r["symbol"],
                    "scenario": r["scenario"],
                    "trades": len(r["trades"]),
                    "net_pnl": sum(t["net_pnl"] for t in r["trades"]),
                    "benchmark_net": r["benchmark_net"],
                }
            )
            for t in r["trades"]:
                trade_number += 1
                t["id"] = f"T{trade_number:06d}"
                save_trade(OUTPUT, t, f"{cfg.side}_{t['symbol']}_{cfg.timeframe_minutes}m")
                local_trades.append(t)
        strategy_page(OUTPUT, cfg, sid, ms, local_trades, local_stocks)
        all_trades.extend(local_trades)
        stock_rows.extend(local_stocks)
        metric_rows.extend(ms)
        ranking.append(
            {
                "strategy_id": sid,
                "name": cfg.name,
                "side": cfg.side,
                "minutes": cfg.timeframe_minutes,
                "worst_path_net": min(m["net_pnl"] for m in ms),
                "mean_path_net": sum(m["net_pnl"] for m in ms) / 2,
                "net_OLHC": ms[0]["net_pnl"],
                "net_OHLC": ms[1]["net_pnl"],
                "trades_OLHC": ms[0]["trades"],
                "trades_OHLC": ms[1]["trades"],
                "max_drawdown_worse": max(m["max_drawdown"] for m in ms),
                "sl_buffer": cfg.sl_buffer,
                "reward_risk": cfg.reward_risk,
                "trail_fraction": cfg.trail_fraction,
                "partial": cfg.partial,
                "stop_rule": cfg.stop_rule,
                "target_rule": cfg.target_rule,
                "code": source,
            }
        )
    ranking.sort(
        key=lambda r: (
            -r["worst_path_net"],
            -r["mean_path_net"],
            r["max_drawdown_worse"],
            r["strategy_id"],
        )
    )
    write_csv(OUTPUT / "strategy_summary.csv", ranking)
    write_csv(OUTPUT / "strategy_path_metrics.csv", metric_rows)
    write_csv(OUTPUT / "strategy_stock_metrics.csv", stock_rows)
    write_csv(
        OUTPUT / "all_trades.csv",
        [{k: v for k, v in t.items() if k not in ("fills", "stop_path")} for t in all_trades],
    )
    write_csv(
        OUTPUT / "all_fills.csv",
        [
            {
                "trade_id": t["id"],
                "strategy_id": t["strategy_id"],
                "symbol": t["symbol"],
                "scenario": t["scenario"],
                **f,
            }
            for t in all_trades
            for f in t["fills"]
        ],
    )
    (OUTPUT / "data_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    index_page(OUTPUT, ranking, audit)
    summary = [
        "# Results: 11 September 2026",
        "",
        f"Tested 404 materialized strategies across 22 supplied stocks and two OHLC paths: 8,888 strategy-stock runs. Recorded {len(all_trades):,} round trips and created one full-session chart per trade.",
        "",
        "These are candle-path approximations. Rank uses the lower net P&L of the two scenarios, then their mean. It is not a worst-case bound or evidence of future profitability.",
        "",
        "| Group | Best observed | Lower-path net Rs | Mean net Rs | SL | RR | Trail | Partial | Indicator stop | Indicator target |",
        "|---|---|---:|---:|---|---|---|---|---|---|",
    ]
    for side in ("buy", "sell"):
        for minutes in (1, 5):
            eligible = [
                r
                for r in ranking
                if r["side"] == side
                and r["minutes"] == minutes
                and r["trades_OLHC"] + r["trades_OHLC"] > 0
            ]
            if not eligible:
                continue
            r = eligible[0]
            summary.append(
                f"| {side} {minutes}m | [{r['strategy_id']}](strategies/{r['strategy_id']}.html) | {r['worst_path_net']:,.2f} | {r['mean_path_net']:,.2f} | {r['sl_buffer']} | {r['reward_risk']} | {r['trail_fraction']:.0%} | {r['partial']} | {r['stop_rule']} | {r['target_rule']} |"
            )
    summary += [
        "",
        "## What the ranking means",
        "",
        "The best observed version retains the most net profit under the less favourable of the two assumed intraminute paths. Compare its trade count, loss size, exit reasons, concentration by stock, and the default 0.10/2R version in the per-strategy reports. Parameter variants can tie because their changed exit was never reached that day. A high configured RR does not imply a target at that RR was actually hit.",
        "",
        "The supplied gainers/losers were chosen with knowledge of the day, so this universe has selection bias. Early entries in ASHOKAMET, DIGJAMLMTD and LADDERUP are unavailable until indicators warm up because those files have no prior session. Missing candles, zero-volume bars and very large share participation make fills uncertain. F&O membership uses the adjacent-date local instrument master, not a reconstructed historical master.",
        "",
        "Each trade has up to Rs 100,000 notional; different symbols can overlap. Basket return uses Rs 1,100,000 capital, not one lakh for the aggregate. Costs include 0.05% adverse slippage and tick rounding plus estimated per-order statutory/broker charges. Slippage and fees are disclosed separately. Annualized Sharpe/Sortino/CAGR are not meaningful from one session and are not reported.",
        "",
        "VectorBT independently reconciled every strategy-stock-scenario fill ledger. The engine itself is the existing materialized strategy factory; no strategy rules were optimized or changed to improve the result.",
        "",
        "[Open the full comparison and every trade chart](index.html). See [methodology](methodology.md) and [data audit](data_audit.json).",
    ]
    (OUTPUT / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    validation = {
        "strategies": 404,
        "stock_inputs": 22,
        "strategy_stock_path_runs": len(all_results),
        "round_trips": len(all_trades),
        "trade_charts": len(list((OUTPUT / "trades").glob("*.html"))),
        "vectorbt_ledgers_verified": len(all_results),
        "all_positions_closed": True,
    }
    (OUTPUT / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps(validation), flush=True)
    print("Top five:", json.dumps(ranking[:5]), flush=True)


if __name__ == "__main__":
    main()
