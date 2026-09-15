"""Independently check saved report ledgers against the supplied raw trade tape."""

import csv
import hashlib
import importlib.metadata
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from backtesting.ethfut_404.data import OUT, read_ticks, write_json


def main():
    times, prices, _, audit = read_ticks()
    assert audit == json.loads((OUT / "source_audit.json").read_text())
    source = dict(zip(times, prices, strict=True))
    summaries = json.loads((OUT / "summary.json").read_text())["strategies"]
    assert len(summaries) == 404
    totals = {"fills": 0, "trades": 0, "overnight_trades": 0, "entries_outside_nse_hours": 0}
    for summary in summaries:
        sid = summary["id"]
        fills = list(csv.DictReader((OUT / f"{sid}_fills.csv").open(encoding="utf-8")))
        trades = list(csv.DictReader((OUT / f"{sid}_trades.csv").open(encoding="utf-8")))
        units = 0
        last = 0
        cash = fees = 0.0
        for row in fills:
            stamp = datetime.fromisoformat(row["time"])
            us = round(stamp.timestamp() * 1e6)
            assert us in source and us >= last
            last = us
            sign = 1 if row["side"] == "buy" else -1
            price, quantity, fee = (float(row[k]) for k in ("price", "eth", "fees"))
            np.testing.assert_allclose(price, source[us] * (1 + sign * 0.0005), atol=1e-8)
            np.testing.assert_allclose(fee, price * quantity * 0.0005, atol=1e-8)
            np.testing.assert_allclose(quantity * 100, round(quantity * 100), atol=1e-8)
            q = round(quantity * 100)
            if row["reason"] == "entry":
                assert units == 0 and quantity * price <= 100000 + 1e-8
                from zoneinfo import ZoneInfo

                local = stamp.astimezone(ZoneInfo("Asia/Kolkata"))
                minutes = local.hour * 60 + local.minute
                totals["entries_outside_nse_hours"] += not 555 <= minutes < 920
            units += sign * q
            cash += -sign * quantity * price - fee
            fees += fee
        assert units == 0
        assert len(trades) == summary["trades"]
        np.testing.assert_allclose(
            sum(float(t["net_pnl"]) for t in trades), summary["net_pnl"], atol=1e-6
        )
        np.testing.assert_allclose(cash, summary["net_pnl"], atol=1e-6)
        np.testing.assert_allclose(fees, summary["fees"], atol=1e-6)
        daily = list(csv.DictReader((OUT / f"{sid}_daily.csv").open(encoding="utf-8")))
        np.testing.assert_allclose(
            sum(float(d["daily_pnl"]) for d in daily), summary["net_pnl"], atol=1e-6
        )
        totals["fills"] += len(fills)
        totals["trades"] += len(trades)
        totals["overnight_trades"] += summary["overnight_trades"]
    dependencies = [
        Path("strategies/ha_bb_vwap_v1") / f for f in ("engine.py", "models.py", "indicators.py")
    ]
    dependencies.append(Path("backtesting/ha_bb_vwap_v1_20260911/replay.py"))
    evidence = dict(
        passed=True,
        versions=404,
        **totals,
        source_hashes_preserved=True,
        every_fill_matches_actual_source_trade_plus_slippage=True,
        every_csv_total_reconciled=True,
        dependency_hashes={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies
        },
        packages={
            p: importlib.metadata.version(p)
            for p in ("openalgo", "numba", "numpy", "polars", "vectorbt", "pandas")
        },
    )
    write_json(OUT / "verification.json", evidence)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
