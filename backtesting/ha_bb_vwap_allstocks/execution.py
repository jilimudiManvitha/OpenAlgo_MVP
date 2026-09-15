"""Date-independent execution adapter for the unchanged materialized strategies."""

import math
from dataclasses import replace

import numpy as np

from backtesting.ha_bb_vwap_v1_20260911.replay import definitions, event_stream

from .source import bounds


def selected_definitions(config):
    result = [(f"S{i + 1:03d}", definition) for i, definition in enumerate(definitions())]
    wanted = set(config["strategy_ids"])
    if wanted - {r[0] for r in result}:
        raise ValueError("Unknown strategy_ids")
    return [r for r in result if not wanted or r[0] in wanted]


def replay(definition, sid, symbol, day, instrument, events, path, config, costs):
    cfg, factory, _ = definition
    engine = factory(symbol, instrument["is_fo"])
    start, end = bounds(day)
    cutoff = start.replace(hour=15, minute=5 if instrument["is_fo"] else 20)
    trades, marked, rejected = [], [], []
    trade, cash, clock_done = None, 0.0, False
    last_price = events[0][0].candle.open

    def fill(intent):
        nonlocal trade, cash
        direction = 1 if intent.side == "buy" else -1
        tick = instrument["tick_size"]
        slipped = intent.reference_price * (1 + direction * config["slippage"])
        price = (
            math.ceil(slipped / tick - 1e-9)
            if direction == 1
            else math.floor(slipped / tick + 1e-9)
        ) * tick
        quantity = intent.quantity
        if intent.reason == "entry":
            quantity = min(quantity, math.floor(cfg.capital / price))
            if quantity < 1:
                engine.reject_order(intent.order_id)
                rejected.append(
                    {"time": intent.observed_at.isoformat(), "reason": "capital_or_price"}
                )
                return
            engine.pending.intent = replace(intent, quantity=quantity)
        try:
            engine.acknowledge_fill(intent.order_id, price, quantity)
        except ValueError as error:
            engine.reject_order(intent.order_id)
            rejected.append({"time": intent.observed_at.isoformat(), "reason": str(error)})
            return
        parts = costs.breakdown(day, intent.side, quantity, price)
        fee = sum(parts.values())
        f = {
            "time": intent.observed_at.isoformat(),
            "side": intent.side,
            "quantity": quantity,
            "price": price,
            "reference": intent.reference_price,
            "fees": fee,
            "costs": parts,
            "reason": intent.reason,
        }
        cash -= fee
        if intent.reason == "entry":
            position = engine.position
            trade = {
                "id": f"{day}_{sid}_{path}_{symbol}_{len(trades) + 1}",
                "day": day,
                "strategy_id": sid,
                "scenario": path,
                "symbol": symbol,
                "side": cfg.side,
                "minutes": cfg.timeframe_minutes,
                "entry_time": f["time"],
                "entry_price": price,
                "quantity": quantity,
                "initial_stop": position.initial_stop,
                "target": position.target,
                "gross_pnl": 0.0,
                "reference_pnl": 0.0,
                "fees": fee,
                "fills": [f],
                "stop_path": [],
            }
        else:
            pnl = cfg.direction * (price - trade["entry_price"]) * quantity
            trade["gross_pnl"] += pnl
            trade["reference_pnl"] += (
                cfg.direction * (intent.reference_price - trade["fills"][0]["reference"]) * quantity
            )
            trade["fees"] += fee
            trade["fills"].append(f)
            cash += pnl
            if engine.position is None:
                trade.update(
                    exit_time=f["time"],
                    exit_reason=intent.reason,
                    net_pnl=trade["gross_pnl"] - trade["fees"],
                    slippage_cost=trade["reference_pnl"] - trade["gross_pnl"],
                )
                trades.append(trade)
                trade = None

    for snap, liquid in events:
        if not clock_done and snap.candle.observed_at >= cutoff:
            reference = snap.candle.open if snap.candle.start == cutoff else last_price
            for intent in engine.on_clock(cutoff, reference):
                fill(intent)
            clock_done = True
        for intent in engine.on_snapshot(snap):
            if liquid or intent.reason != "entry":
                fill(intent)
            else:
                engine.reject_order(intent.order_id)
                rejected.append({"time": intent.observed_at.isoformat(), "reason": "zero_volume"})
        last_price = snap.candle.close
        pnl = cash
        if engine.position:
            pnl += cfg.direction * (last_price - engine.position.entry) * engine.position.quantity
            if not trade["stop_path"] or trade["stop_path"][-1][1] != engine.position.stop:
                trade["stop_path"].append(
                    [snap.candle.observed_at.isoformat(), engine.position.stop]
                )
        if snap.candle.complete:
            marked.append([snap.candle.observed_at.isoformat(), pnl])
    if not clock_done:
        for intent in engine.on_clock(cutoff, last_price):
            fill(intent)
        marked.append([cutoff.isoformat(), cash])
    if engine.position or engine.pending:
        raise AssertionError("Unclosed position/order at session end")
    if not np.isclose(cash, sum(t["net_pnl"] for t in trades)):
        raise AssertionError("Session cash/trade ledger mismatch")
    return trades, marked, rejected


def reconcile(trades):
    if not trades:
        return
    import pandas as pd
    import vectorbt as vbt

    fills = [f for t in trades for f in t["fills"]]
    prices = pd.Series([f["price"] for f in fills], dtype=float)
    sizes = [f["quantity"] * (1 if f["side"] == "buy" else -1) for f in fills]
    portfolio = vbt.Portfolio.from_orders(
        prices,
        size=sizes,
        price=prices,
        direction="both",
        init_cash=1e6,
        fees=0,
        fixed_fees=[f["fees"] for f in fills],
        min_size=1,
        size_granularity=1,
        allow_partial=False,
        freq="1min",
    )
    if len(portfolio.orders.records) != len(fills) or not np.isclose(
        float(portfolio.total_profit()), sum(t["net_pnl"] for t in trades), atol=1e-6
    ):
        raise AssertionError("Independent VectorBT fill accounting differs")
