"""Explicit OHLC-path approximation for the existing V1 event-driven strategies."""

import csv
import hashlib
import importlib.util
import json
import math
import sqlite3
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from openalgo import ta

from strategies.ha_bb_vwap_v1.models import IST, Candle, Indicators, Snapshot

ROOT = Path(__file__).resolve().parents[2]
DAY = "2026-09-11"
START = datetime(2026, 9, 11, 9, 15, tzinfo=IST)
END = START.replace(hour=15, minute=30)
SLIPPAGE = 0.0005
STEPS_PER_LEG = 3
WARMUP = 600


def definitions():
    result = []
    base = ROOT / "strategies/ha_bb_vwap_v1/versions"
    for path in sorted(base.glob("*/*/*.py")):
        spec = importlib.util.spec_from_file_location("v1_definition", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result.append((module.CONFIG, module.create_strategy, str(path.relative_to(ROOT))))
    if len(result) != 404 or len({x[0].name for x in result}) != 404:
        raise ValueError("Expected 404 unique materialized versions")
    return result


def source_files():
    result = []
    for side, group in (("buy", "GainersOn11092026"), ("sell", "LoosersOn11092026")):
        for one in sorted((ROOT / "CSVs" / group).glob("historify*/*_1m.csv")):
            five = one.with_name(one.name.replace("_1m.csv", "_5m.csv"))
            if not five.exists():
                raise ValueError(f"Missing matching 5m file: {one}")
            result.append((side, one.name.split("_NSE_")[0], one, five))
    if len(result) != 22:
        raise ValueError(f"Expected 22 stock/side inputs, found {len(result)}")
    return result


def metadata(symbols):
    result = {}
    uri = (ROOT / "db/openalgo.db").as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        for symbol in symbols:
            eq = db.execute(
                "SELECT tick_size FROM symtoken WHERE symbol=? AND exchange='NSE'", (symbol,)
            ).fetchone()
            fo = db.execute(
                "SELECT symbol FROM symtoken WHERE exchange='NFO' AND (name=? OR symbol GLOB ?) LIMIT 1",
                (symbol, symbol + "[0-9]*"),
            ).fetchone()
            if not eq or not eq[0]:
                raise ValueError(f"Missing equity instrument metadata: {symbol}")
            result[symbol] = {
                "tick_size": eq[0],
                "is_fo": bool(fo),
                "derivative_example": fo[0] if fo else None,
                "source": "read-only local symtoken master, September 13 snapshot",
            }
    return result


def read_input(path, minutes):
    frame = pl.read_csv(path, schema_overrides={"date": pl.String, "time": pl.String})
    total = frame.height
    invalid = frame.filter(
        (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") <= 0)
        | (pl.col("volume") < 0)
    )
    day = frame.filter(pl.col("date") == DAY)
    prior = frame.filter(pl.col("date") < DAY).tail(WARMUP)
    selected = pl.concat([prior, day]).sort(["date", "time"])
    if selected.unique(subset=["date", "time"]).height != selected.height:
        raise ValueError(f"Duplicate candles: {path}")
    bars = []
    for row in selected.iter_rows(named=True):
        start = datetime.fromisoformat(row["date"] + "T" + row["time"]).replace(tzinfo=IST)
        bar = Candle(
            start,
            start + timedelta(minutes=minutes),
            *[float(row[k]) for k in ("open", "high", "low", "close", "volume")],
            True,
        )
        bar.validate(minutes)
        bars.append(bar)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    audit = {
        "file": str(path.relative_to(ROOT)),
        "sha256": digest,
        "source_rows": total,
        "target_rows": day.height,
        "warmup_rows": prior.height,
        "historical_invalid_ranges": invalid.height,
        "first_time": day["time"][0],
        "last_time": day["time"][-1],
        "zero_volume_target_bars": day.filter(pl.col("volume") == 0).height,
    }
    return (
        [b for b in bars if b.start.date().isoformat() < DAY],
        [b for b in bars if b.start.date().isoformat() == DAY],
        audit,
    )


class Maker:
    """Cache committed HA bars; preview indicators exclude all later information."""

    def __init__(self, history):
        self.raw, self.ha = [], []
        self.session_numerator = self.session_volume = 0.0
        self.session_date = None
        for bar in history:
            self.commit(bar)

    def ha_bar(self, bar):
        hc = (bar.open + bar.high + bar.low + bar.close) / 4
        ho = (self.ha[-1][0] + self.ha[-1][3]) / 2 if self.ha else (bar.open + bar.close) / 2
        return (ho, max(bar.high, ho, hc), min(bar.low, ho, hc), hc)

    def commit(self, bar):
        value = self.ha_bar(bar)
        self.ha.append(value)
        self.raw.append(bar)
        day = bar.start.date()
        if day != self.session_date:
            self.session_date = day
            self.session_numerator = self.session_volume = 0.0
        self.session_numerator += (bar.high + bar.low + bar.close) / 3 * bar.volume
        self.session_volume += bar.volume
        self.array = np.asarray(self.ha, dtype=float)

    def preview(self, bar):
        current = self.ha_bar(bar)
        values = np.vstack((self.array, current)) if self.ha else np.asarray([current])
        h, low, c = values[:, 1], values[:, 2], values[:, 3]
        n = len(c)
        nan = float("nan")
        upper, mid, lower = (
            (float(x[-1]) for x in ta.bbands(c, 20, 2)) if n >= 20 else (nan, nan, nan)
        )
        macd, signal, _ = (
            (float(x[-1]) for x in ta.macd(c, 12, 26, 9)) if n >= 35 else (nan, nan, nan)
        )
        st, direction = (
            (float(x[-1]) for x in ta.supertrend(h, low, c, 14, 2)) if n >= 15 else (nan, nan)
        )
        numerator = self.session_numerator if bar.start.date() == self.session_date else 0
        volume = self.session_volume if bar.start.date() == self.session_date else 0
        numerator += (bar.high + bar.low + bar.close) / 3 * bar.volume
        volume += bar.volume
        indicators = Indicators(
            upper,
            mid,
            lower,
            numerator / volume if volume else nan,
            float(ta.sma(c, 9)[-1]) if n >= 9 else nan,
            float(ta.ema(c, 9)[-1]) if n >= 9 else nan,
            float(ta.ema(c, 21)[-1]) if n >= 21 else nan,
            float(ta.rsi(c, 14)[-1]) if n >= 15 else nan,
            macd,
            signal,
            st,
            direction,
        )
        return Snapshot(bar, *current, indicators)


def event_stream(history, minute_bars, native_bars, minutes, path):
    maker = Maker(history)
    events, charts, discrepancies = [], [], []
    native = {b.start: b for b in native_bars}
    active = None
    for minute in minute_bars:
        start = minute.start.replace(minute=(minute.start.minute // minutes) * minutes)
        if active is not None and active.start != start:
            final = replace(
                active, observed_at=active.start + timedelta(minutes=minutes), complete=True
            )
            events.append(maker.preview(final))
            maker.commit(final)
            charts.append(events[-1])
            active = None
        extrema = [minute.low, minute.high] if path == "OLHC" else [minute.high, minute.low]
        knots = [minute.open, *extrema, minute.close]
        prices = [minute.open]
        for left, right in zip(knots, knots[1:], strict=False):
            prices.extend(
                left + (right - left) * step / STEPS_PER_LEG for step in range(1, STEPS_PER_LEG + 1)
            )
        previous_volume = active.volume if active else 0
        for index, price in enumerate(prices):
            fraction = index / (len(prices) - 1)
            observed = minute.start + timedelta(seconds=fraction * 59.999)
            if active is None:
                active = Candle(start, observed, minute.open, price, price, price, 0, False)
            active = replace(
                active,
                observed_at=observed,
                high=max(active.high, price),
                low=min(active.low, price),
                close=price,
                volume=previous_volume + minute.volume * fraction,
            )
            # A zero-volume minute cannot support fills. Its close still updates indicators.
            events.append((maker.preview(active), minute.volume > 0))
        if minute.start + timedelta(minutes=1) == start + timedelta(minutes=minutes):
            final = replace(active, observed_at=start + timedelta(minutes=minutes), complete=True)
            actual = native.get(start)
            if actual and any(
                abs(getattr(actual, k) - getattr(final, k)) > 1e-6
                for k in ("open", "high", "low", "close", "volume")
            ):
                discrepancies.append(start.isoformat())
            events.append((maker.preview(final), False))
            maker.commit(final)
            charts.append(events[-1][0])
            active = None
    if active:
        final = replace(
            active, observed_at=active.start + timedelta(minutes=minutes), complete=True
        )
        events.append((maker.preview(final), False))
        charts.append(events[-1][0])
    # Missing-minute boundary finalizations above are also non-fill observations.
    events = [x if isinstance(x, tuple) else (x, False) for x in events]
    return events, charts, discrepancies


def charges(side, quantity, price):
    turnover = quantity * price
    brokerage = min(20, turnover * 0.0003)
    exchange = turnover * 0.0000307
    sebi = turnover * 0.000001
    stt = turnover * 0.00025 if side == "sell" else 0
    stamp = turnover * 0.00003 if side == "buy" else 0
    return brokerage + exchange + sebi + stt + stamp + 0.18 * (brokerage + exchange + sebi)


def execute(definition, symbol, meta, events, path, strategy_id):
    cfg, factory, _ = definition
    engine = factory(symbol, meta["is_fo"])
    trades, fills, marked = [], [], []
    trade = None
    cash_pnl = 0.0
    rejected = 0
    cutoff = START.replace(hour=15, minute=5 if meta["is_fo"] else 20)
    clock_done = False
    last_price = events[0][0].candle.open

    def fill(intent):
        nonlocal trade, cash_pnl, rejected
        sign = 1 if intent.side == "buy" else -1
        tick = meta["tick_size"]
        slipped = intent.reference_price * (1 + sign * SLIPPAGE)
        price = (
            math.ceil(slipped / tick - 1e-9) if sign == 1 else math.floor(slipped / tick + 1e-9)
        ) * tick
        quantity = intent.quantity
        if intent.reason == "entry":
            quantity = min(quantity, math.floor(cfg.capital / price))
            if quantity < 1:
                engine.reject_order(intent.order_id)
                rejected += 1
                return
            engine.pending.intent = replace(intent, quantity=quantity)
        fee = charges(intent.side, quantity, price)
        try:
            engine.acknowledge_fill(intent.order_id, price, quantity)
        except ValueError:
            engine.reject_order(intent.order_id)
            rejected += 1
            return
        record = {
            "time": intent.observed_at.isoformat(),
            "side": intent.side,
            "quantity": quantity,
            "price": price,
            "reference": intent.reference_price,
            "fees": fee,
            "reason": intent.reason,
        }
        fills.append(record)
        if intent.reason == "entry":
            p = engine.position
            trade = {
                "strategy_id": strategy_id,
                "name": cfg.name,
                "symbol": symbol,
                "side": cfg.side,
                "minutes": cfg.timeframe_minutes,
                "scenario": path,
                "entry_time": record["time"],
                "entry_price": price,
                "entry_reference": intent.reference_price,
                "quantity": quantity,
                "initial_stop": p.initial_stop,
                "target": p.target,
                "risk": p.risk,
                "gross_pnl": 0.0,
                "reference_pnl": 0.0,
                "fees": fee,
                "fills": [record],
                "stop_path": [],
            }
            cash_pnl -= fee
        else:
            gross = cfg.direction * (price - trade["entry_price"]) * quantity
            reference = (
                cfg.direction * (intent.reference_price - trade["entry_reference"]) * quantity
            )
            trade["gross_pnl"] += gross
            trade["reference_pnl"] += reference
            trade["fees"] += fee
            trade["fills"].append(record)
            cash_pnl += gross - fee
            if engine.position is None:
                trade.update(
                    exit_time=record["time"],
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
                rejected += 1
        last_price = snap.candle.close
        pnl = cash_pnl
        if engine.position:
            pnl += cfg.direction * (last_price - engine.position.entry) * engine.position.quantity
            if trade and (
                not trade["stop_path"] or trade["stop_path"][-1][1] != engine.position.stop
            ):
                trade["stop_path"].append(
                    [snap.candle.observed_at.isoformat(), engine.position.stop]
                )
        if snap.candle.complete:
            marked.append([snap.candle.observed_at.isoformat(), pnl])
    if engine.position:
        for intent in engine.on_clock(END, last_price):
            fill(intent)
    if engine.position or engine.pending:
        raise AssertionError("Unclosed position at end of replay")
    return trades, fills, marked, rejected


def write_csv(path, rows, fields=None):
    if not rows and fields is None:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def safe_json(value):
    if isinstance(value, dict):
        return {k: safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
