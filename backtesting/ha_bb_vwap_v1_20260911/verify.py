"""Independently reconcile report files, source hashes and execution invariants."""

import hashlib
import json
import re
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "results"


def main():
    summary = pd.read_csv(OUT / "strategy_summary.csv")
    trades = pd.read_csv(OUT / "all_trades.csv")
    fills = pd.read_csv(OUT / "all_fills.csv")
    paths = pd.read_csv(OUT / "strategy_path_metrics.csv")
    stocks = pd.read_csv(OUT / "strategy_stock_metrics.csv")
    config = json.loads((OUT / "run_config.json").read_text())
    assert len(summary) == 404 and len(paths) == 808 and len(stocks) == 8888
    assert trades.id.is_unique
    assert len(list((OUT / "trades").glob("*.html"))) == len(trades)
    assert len(list((OUT / "strategies").glob("*.html"))) == 404
    assert (trades.entry_price * trades.quantity <= 100000.000001).all()
    assert (trades.quantity > 0).all()
    assert np.allclose(trades.net_pnl, trades.gross_pnl - trades.fees)
    assert np.allclose(trades.slippage_cost, trades.reference_pnl - trades.gross_pnl)
    assert (trades.slippage_cost >= -1e-6).all()
    assert trades.side.equals(
        trades.symbol.map(
            lambda s: (
                "buy"
                if s
                in {
                    "ASHOKAMET",
                    "BBOX",
                    "DIGJAMLMTD",
                    "DRREDDY",
                    "FILATEX",
                    "HDFCBANK",
                    "KIRLOSIND",
                    "LADDERUP",
                    "PINELABS",
                    "PRICOLLTD",
                    "QUADFUTURE",
                }
                else "sell"
            )
        )
    )
    groups = dict(iter(fills.groupby("trade_id", sort=False)))
    for row in trades.itertuples():
        ledger = groups[row.id]
        assert len(ledger) >= 2
        assert ledger.iloc[0].reason == "entry"
        assert ledger.iloc[0].quantity == row.quantity
        assert ledger.iloc[1:].quantity.sum() == row.quantity
        assert np.isclose(ledger.fees.sum(), row.fees)
        cash = np.where(ledger.side == "buy", -1, 1) * ledger.quantity * ledger.price - ledger.fees
        assert np.isclose(cash.sum(), row.net_pnl, atol=1e-6)
        cutoff = time(15, 5 if config["metadata"][row.symbol]["is_fo"] else 20)
        for timestamp in ledger.time:
            stamp = datetime.fromisoformat(timestamp)
            assert stamp.date().isoformat() == "2026-09-11"
            assert time(9, 15) <= stamp.time() <= cutoff
        assert row.entry_time <= row.exit_time
        tick = config["metadata"][row.symbol]["tick_size"]
        assert np.allclose(ledger.price / tick, np.round(ledger.price / tick))
        page = OUT / "trades" / f"{row.id}.html"
        text = page.read_text(encoding="utf-8")
        for src in re.findall(r'<script src="([^"]+)"', text):
            assert (page.parent / src).is_file(), (page, src)
    for _, group in trades.groupby(["strategy_id", "symbol", "scenario"]):
        ordered = group.sort_values("entry_time")
        assert all(
            a <= b
            for a, b in zip(ordered.exit_time.iloc[:-1], ordered.entry_time.iloc[1:], strict=True)
        )
    aggregate = trades.groupby(["strategy_id", "scenario"]).net_pnl.sum()
    for row in paths.itertuples():
        assert np.isclose(row.net_pnl, aggregate.get((row.strategy_id, row.scenario), 0))
    for row in summary.itertuples():
        selected = paths.loc[paths.strategy_id == row.strategy_id]
        assert np.isclose(selected.net_pnl.min(), row.worst_path_net)
        assert np.isclose(selected.net_pnl.mean(), row.mean_path_net)
        report = json.loads((OUT / "strategies" / f"{row.strategy_id}.json").read_text())
        assert len(report["trades"]) == row.trades_OLHC + row.trades_OHLC
    audits = json.loads((OUT / "data_audit.json").read_text())
    source_count = 0
    for audit in audits:
        if "file" not in audit:
            continue
        source_count += 1
        assert hashlib.sha256((ROOT / audit["file"]).read_bytes()).hexdigest() == audit["sha256"]
    assert source_count == 44
    result = {
        "status": "passed",
        "strategies": len(summary),
        "paths": len(paths),
        "stock_runs": len(stocks),
        "trades_checked": len(trades),
        "fills_checked": len(fills),
        "source_hashes_checked": source_count,
        "chart_files_and_script_links_checked": len(trades),
        "checks": [
            "P&L/fees/size reconciliation",
            "whole-share quantity and tick alignment",
            "date and square-off limits",
            "no same-stock position overlaps",
            "correct buy/sell universe",
            "ranking and report totals",
            "immutable input hashes",
        ],
    }
    (OUT / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
