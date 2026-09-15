"""Artificial report data only. Does not open Historify or run a strategy."""

import json
import math
from dataclasses import asdict

from backtesting.ha_bb_vwap_v1_20260911.replay import Maker
from strategies.ha_bb_vwap_v1.models import Candle

from .configuration import Costs, load_config
from .runner import chart_rows
from .source import aggregate, bounds
from .statistics import DayAccumulator
from .storage import Store, encode


def demo_trade(day, sid, symbol, side, minutes, bars, costs, offset):
    direction = 1 if side == "buy" else -1
    entry_index, exit_index = 40 + offset * 10, 110 + offset * 20
    quantity = 100 + offset * 50
    sequence = [
        (entry_index, quantity, "entry"),
        (80, quantity // 2, "partial"),
        (exit_index, quantity - quantity // 2, "square_off"),
    ]
    fills = []
    for index, qty, reason in sequence:
        action = side if reason == "entry" else ("sell" if side == "buy" else "buy")
        price = round(bars[index].open, 2)
        parts = costs.breakdown(day, action, qty, price)
        fills.append(
            {
                "time": bars[index].start.isoformat(),
                "side": action,
                "quantity": qty,
                "price": price,
                "reference": price,
                "fees": sum(parts.values()),
                "costs": parts,
                "reason": reason,
            }
        )
    gross = sum(direction * (f["price"] - fills[0]["price"]) * f["quantity"] for f in fills[1:])
    fees = sum(f["fees"] for f in fills)
    return {
        "id": f"DEMO_{day}_{sid}_{symbol}",
        "day": day,
        "strategy_id": sid,
        "scenario": "OLHC",
        "symbol": symbol,
        "side": side,
        "minutes": minutes,
        "entry_time": fills[0]["time"],
        "exit_time": fills[-1]["time"],
        "entry_price": fills[0]["price"],
        "quantity": quantity,
        "initial_stop": fills[0]["price"] - direction * 3,
        "target": fills[0]["price"] + direction * 6,
        "gross_pnl": gross,
        "reference_pnl": gross,
        "fees": fees,
        "net_pnl": gross - fees,
        "slippage_cost": 0,
        "exit_reason": "square_off",
        "fills": fills,
        "stop_path": [],
    }


def marks_for(trades, bars):
    result = []
    for bar in bars:
        net = 0
        for t in trades:
            if t["entry_time"] > bar.observed_at.isoformat():
                continue
            quantity = 0
            direction = 1 if t["side"] == "buy" else -1
            for f in t["fills"]:
                if f["time"] > bar.observed_at.isoformat():
                    continue
                net -= f["fees"]
                if f["reason"] == "entry":
                    quantity += f["quantity"]
                else:
                    quantity -= f["quantity"]
                    net += direction * (f["price"] - t["entry_price"]) * f["quantity"]
            net += direction * (bar.close - t["entry_price"]) * quantity
        result.append([bar.observed_at.isoformat(), net])
    return result


def create_demo(output):
    from datetime import timedelta

    config = load_config()
    config.update(
        output=str(output),
        source="SYNTHETIC_DEMO_ONLY",
        symbols=["DEMO_A", "DEMO_B"],
        paths=["OLHC"],
        slippage=0,
    )
    days = [
        "2017-07-03",
        "2017-12-29",
        "2018-01-02",
        "2021-12-31",
        "2022-01-03",
        "2022-07-01",
        "2026-06-30",
        "2026-09-10",
    ]
    defs = [
        ("D001", {"name": "SYNTHETIC DEMO — buy 1m", "side": "buy", "timeframe_minutes": 1}),
        ("D002", {"name": "SYNTHETIC DEMO — sell 5m", "side": "sell", "timeframe_minutes": 5}),
    ]
    manifest = {
        "schema_version": 1,
        "demo": True,
        "config": config,
        "planned_days": days,
        "capital_reference": 200000,
        "source_sha256": "SYNTHETIC",
        "notes": [
            "SYNTHETIC DEMO — invented prices/trades for dashboard testing only.",
            "No source DuckDB was opened and no historical strategy was backtested.",
            "Real backtest defaults remain July 3, 2017 through September 10, 2026.",
        ],
    }
    costs = Costs(config)
    with Store(output / "results.sqlite", manifest, defs) as store:
        for day_index, day in enumerate(days):
            with store.db:
                a, _ = bounds(day)
                accumulators = {sid: DayAccumulator(day) for sid, _ in defs}
                for offset, symbol in enumerate(config["symbols"]):
                    bars = []
                    for i in range(375):
                        value = 100 + offset * 20 + 4 * math.sin(i / 32 + day_index * 0.7)
                        start = a + timedelta(minutes=i)
                        bars.append(
                            Candle(
                                start,
                                start + timedelta(minutes=1),
                                value,
                                value + 0.4,
                                value - 0.4,
                                value + 0.08,
                                10000,
                                True,
                            )
                        )
                    for sid, cfg in defs:
                        minutes = cfg["timeframe_minutes"]
                        trade = demo_trade(
                            day, sid, symbol, cfg["side"], minutes, bars, costs, offset
                        )
                        source_bars = bars if minutes == 1 else aggregate(bars)
                        accumulators[sid].add([trade], marks_for([trade], source_bars))
                        store.add_trades([trade])
                        maker, charts = Maker([]), []
                        for bar in source_bars:
                            charts.append(maker.preview(bar))
                            maker.commit(bar)
                        store.db.execute(
                            "INSERT INTO candles VALUES(?,?,?,?)",
                            (day, symbol, minutes, encode(chart_rows(charts))),
                        )
                    store.db.execute(
                        "INSERT INTO coverage VALUES(?,?,?,?)",
                        (
                            day,
                            symbol,
                            "synthetic",
                            json.dumps({"rows": 375, "warning": "Invented fixture candles"}),
                        ),
                    )
                for sid, _ in defs:
                    stats, series = accumulators[sid].finish()
                    store.daily(sid, "OLHC", day, stats, series)
                store.db.execute(
                    "INSERT INTO days VALUES(?,?,?,?,?,?)",
                    (day, 2, 2, 0, 0.001 * math.sin(day_index), "SYNTHETIC"),
                )
    return output
