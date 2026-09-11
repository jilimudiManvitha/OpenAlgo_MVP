#!/usr/bin/env python3
"""Narasimha's 5-minute HA + Bollinger Bands + VWAP long strategy.

INSTALL: python -m pip install pandas numpy
Optional OpenAlgo downloader: python -m pip install openalgo

EXAMPLES
  python ha_bb_vwap_strategy.py backtest --csv candles.csv
  python ha_bb_vwap_strategy.py backtest --csv candles.csv --volume-mode time
  python ha_bb_vwap_strategy.py backtest --csv candles.csv --skip-volume-filter
  python ha_bb_vwap_strategy.py download --symbols SBIN,INFY --start 2026-07-01 --end 2026-09-04 --out candles.csv
  python ha_bb_vwap_strategy.py selftest

CSV: timestamp,symbol,open,high,low,close,volume
Timestamps label BAR OPEN, e.g. 2026-09-04T09:15:00+05:30.
Naive timestamps are explicitly interpreted as Asia/Kolkata. Use actual,
unadjusted 5-minute OHLCV, NOT Heikin Ashi OHLCV. Supply at least 21 complete
regular sessions per symbol (75 bars, 09:15 through 15:25). Missing bars,
duplicate timestamps and partial sessions are rejected, never filled forward.
Special trading sessions must be excluded from this regular-session backtest.

BASELINE
  BB = SMA(HA close, 20) +/- 2 * population stddev(HA close, 20).
  HA recurses across sessions; initial HA open = (real open + real close)/2.
  VWAP = session cumulative (real HLC3 * volume) / cumulative volume.
  Volume filter default: cumulative volume / prior 20 full-session average.
  --volume-mode time selects prior 20 sessions' same-time cumulative average.
  --skip-volume-filter disables RVOL and its 20-session warmup; VWAP stays on.
  --breakout-source high uses HA high for fresh BB crosses and HA BB/VWAP
    filters. Confirmation still closes above the signal HA high.
  --exit-mode bb_middle replaces the 2R target with a real-price break below
    the prior completed candle's BB middle. Initial stop and square-off remain.
  Signal: fresh HA-close cross above upper BB, bullish, zero lower wick.
  Confirmation: immediate next same-session completed HA candle, bullish,
    zero lower wick, HA close above signal HA high, real close above VWAP.
  Extra image filters (default on): signal HA close > VWAP; confirmation
    HA close > VWAP and upper BB. --no-image-filters disables these extras.
  Entry: NEXT actual bar open plus adverse slippage, after confirmation.
  Stop: signal HA low (or --stop-source real). Target: fill + 2*(fill-stop).
  Stop rounds DOWN and target UP to --tick-size. Configure for your symbols.
  One portfolio position, max 3 entries/day, entry 09:20..15:00 inclusive;
    flatten at the 15:20 bar OPEN. No BB-middle trailing in this version.

EXECUTION MODEL / LIMITS
  Backtesting only. No broker order methods and no switch enabling live orders.
  Real OHLC drives exits. Stop wins if both levels occur in one bar. Downward
  stop gaps fill at open minus slippage; target limits fill at target (no gap
  improvement). A position held at bar open blocks new entries for that bar.
  Default costs are illustrative, NOT a verified broker/tax schedule. Supply
  realistic total costs. Five-minute bars cannot resolve intrabar ordering.
  RVOL eligibility is checked at SIGNAL close, not using end-of-day knowledge.
  The provided symbols define the universe; this does not assert Nifty 500
  membership. Use point-in-time constituents to avoid survivorship bias.
  Tests verify mechanics with synthetic data; no profitability claim is made.

OpenAlgo credentials: OPENALGO_API_KEY and optional OPENALGO_HOST
(default http://127.0.0.1:5000). Fyers must already be connected there.
Sources: https://docs.openalgo.in/trading-platform/python
https://www.tradingview.com/pine-script-docs/concepts/non-standard-charts-data/
https://www.tradingview.com/support/solutions/43000705489-relative-volume-at-time/
"""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "Asia/Kolkata"
FIVE = pd.Timedelta(minutes=5)


@dataclass(frozen=True)
class Config:
    bb_length: int = 20
    bb_std: float = 2.0
    volume_days: int = 20
    volume_multiple: float = 2.0
    volume_mode: str = "daily"
    volume_filter: bool = True
    breakout_source: str = "close"
    exit_mode: str = "target"
    stop_source: str = "ha"
    image_filters: bool = True
    capital: float = 10000.0
    risk_fraction: float = 0.005
    buying_power_multiple: float = 1.0
    tick_size: float = 0.01
    slippage_bps: float = 5.0
    fee_bps: float = 5.0
    max_trades: int = 3
    entry_start: time = time(9, 20)
    entry_end: time = time(15, 0)
    square_off: time = time(15, 20)

    def validate(self):
        numeric = (self.capital, self.risk_fraction, self.buying_power_multiple,
                   self.tick_size, self.slippage_bps, self.fee_bps,
                   self.bb_std, self.volume_multiple)
        if not all(math.isfinite(v) for v in numeric):
            raise ValueError("Configuration must contain finite numbers")
        if self.capital <= 0 or not 0 < self.risk_fraction <= 1:
            raise ValueError("Capital > 0 and risk fraction in (0, 1] required")
        if min(self.tick_size, self.buying_power_multiple, self.volume_multiple, self.bb_std) <= 0:
            raise ValueError("Tick, buying power, volume multiple and BB std must be positive")
        if self.slippage_bps < 0 or self.slippage_bps >= 10000 or self.fee_bps < 0:
            raise ValueError("Invalid slippage or fees")
        if self.bb_length < 2 or self.volume_days < 1 or self.max_trades < 1:
            raise ValueError("Invalid lookback or trade limit")
        if self.volume_mode not in ("daily", "time") or self.stop_source not in ("ha", "real"):
            raise ValueError("Invalid volume mode or stop source")
        if self.breakout_source not in ("close", "high"):
            raise ValueError("Breakout source must be close or high")
        if self.exit_mode not in ("target", "bb_middle"):
            raise ValueError("Exit mode must be target or bb_middle")
        if not self.entry_start <= self.entry_end < self.square_off:
            raise ValueError("Invalid trading windows")


def ist_timestamp(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("Missing timestamp")
    return stamp.tz_localize(TZ) if stamp.tzinfo is None else stamp.tz_convert(TZ)


def read_candles(path):
    data = pd.read_csv(path)
    required = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    if not set(required).issubset(data.columns):
        raise ValueError("CSV needs: " + ",".join(required))
    if data.empty or data[required].isna().any().any():
        raise ValueError("CSV is empty or contains missing fields")
    data = data[required].copy()
    data["timestamp"] = pd.DatetimeIndex([ist_timestamp(x) for x in data.timestamp])
    data["symbol"] = data.symbol.astype(str).str.strip().str.upper()
    if (data.symbol == "").any() or data.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("Empty symbol or duplicate symbol/timestamp")
    cols = ["open", "high", "low", "close", "volume"]
    data[cols] = data[cols].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(data[cols].to_numpy()).all():
        raise ValueError("Non-finite OHLCV")
    if (data[["open", "high", "low", "close"]] <= 0).any().any() or (data.volume < 0).any():
        raise ValueError("Prices must be positive; volume nonnegative")
    if ((data.high < data[["open", "close", "low"]].max(axis=1)) |
            (data.low > data[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC ranges")
    now = pd.Timestamp.now(tz=TZ)
    if (data.timestamp + FIVE > now).any():
        raise ValueError("Input contains future or unfinished bars")
    expected = list(range(9 * 60 + 15, 15 * 60 + 30, 5))
    for (symbol, day), group in data.groupby(["symbol", data.timestamp.dt.date]):
        group = group.sort_values("timestamp")
        stamps = group.timestamp.dt
        minutes = (stamps.hour * 60 + stamps.minute).tolist()
        if minutes != expected or (stamps.second != 0).any() or (stamps.microsecond != 0).any():
            raise ValueError(f"{symbol} {day}: require all 75 regular 5-minute bar-open timestamps")
    return data.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def pattern_flags(d, cfg):
    """All flags become knowable only at the row's CLOSE."""
    same_next = d.index.to_series().diff().eq(FIVE)
    same_next &= pd.Series(d.index.date, index=d.index).eq(
        pd.Series(d.index.date, index=d.index).shift())
    bullish = d.ha_close > d.ha_open
    tolerance = np.maximum(1e-8, np.abs(d.ha_open) * 1e-10)
    wickless = (d.ha_low - d.ha_open).abs() <= tolerance
    breakout = d.ha_high if cfg.breakout_source == "high" else d.ha_close
    signal = (bullish & wickless & (breakout > d.bb_upper)
              & (breakout.shift() <= d.bb_upper.shift()))
    if cfg.volume_filter:
        signal &= d.rvol >= cfg.volume_multiple
    if cfg.image_filters:
        signal &= breakout > d.vwap
    confirmation = (signal.shift(fill_value=False) & same_next & bullish & wickless
                    & (d.ha_close > d.ha_high.shift()) & (d.close > d.vwap))
    if cfg.image_filters:
        confirmation &= (breakout > d.vwap) & (breakout > d.bb_upper)
    return signal, confirmation


def indicators(raw, cfg):
    d = raw.set_index("timestamp").sort_index().copy()
    hc = d[["open", "high", "low", "close"]].mean(axis=1)
    ho = np.empty(len(d))
    ho[0] = (d.open.iloc[0] + d.close.iloc[0]) / 2
    for i in range(1, len(d)):
        ho[i] = (ho[i - 1] + hc.iloc[i - 1]) / 2
    d["ha_open"], d["ha_close"] = ho, hc
    d["ha_high"] = np.maximum.reduce([d.high.to_numpy(), ho, hc.to_numpy()])
    d["ha_low"] = np.minimum.reduce([d.low.to_numpy(), ho, hc.to_numpy()])
    d["bb_middle"] = hc.rolling(cfg.bb_length).mean()
    dev = hc.rolling(cfg.bb_length).std(ddof=0)
    d["bb_upper"] = d.bb_middle + cfg.bb_std * dev
    d["bb_lower"] = d.bb_middle - cfg.bb_std * dev
    days = pd.Series(d.index.date, index=d.index)
    cv = d.volume.groupby(days).cumsum()
    tp = d[["high", "low", "close"]].mean(axis=1)
    d["vwap"] = (tp * d.volume).groupby(days).cumsum() / cv.replace(0, np.nan)
    if cfg.volume_mode == "daily":
        totals = d.volume.groupby(days).sum()
        baseline = totals.shift(1).rolling(cfg.volume_days).mean()
        denom = days.map(baseline)
    else:
        # Validated input guarantees the same complete 75 time slots each day.
        slots = pd.Series(d.index.hour * 60 + d.index.minute, index=d.index)
        denom = cv.groupby(slots).transform(
            lambda x: x.shift(1).rolling(cfg.volume_days).mean())
    d["rvol"] = cv / denom.replace(0, np.nan)
    d["signal"], d["confirmation"] = pattern_flags(d, cfg)
    source = d.ha_low if cfg.stop_source == "ha" else d.low
    d["signal_stop"] = source.shift(1)  # available at confirmation close
    d["signal_rvol"] = d.rvol.shift(1)
    d["signal_time"] = pd.Series(d.index, index=d.index).shift(1)
    return d


def tick_round(value, tick, up=False):
    units = value / tick
    return round((math.ceil(units - 1e-9) if up else math.floor(units + 1e-9)) * tick, 10)


def stop_target_exit(bar, position, cfg):
    """Actual OHLC only. Return (price, reason) or None."""
    if cfg.exit_mode == "bb_middle":
        return bb_middle_exit(bar, position, cfg)
    o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
    slip = cfg.slippage_bps / 10000
    stop, target = position["stop"], position["target"]
    if o <= stop:
        return max(cfg.tick_size, tick_round(o * (1 - slip), cfg.tick_size)), "gap_stop"
    if o >= target:
        return target, "target"
    if l <= stop:
        reason = "both_hit_stop_first" if h >= target else "stop"
        return max(cfg.tick_size, tick_round(stop * (1 - slip), cfg.tick_size)), reason
    if h >= target:
        return target, "target"
    return None


def bb_middle_exit(bar, position, cfg):
    """Follow the last completed BB middle, retaining the initial protective stop.

    The band can move down; it is not a ratcheted highest-ever stop. Current-bar
    HA close and BB values must never be used to decide an intrabar exit.
    """
    o, low = float(bar["open"]), float(bar["low"])
    stop = position["stop"]
    middle = float(bar.get("bb_exit_level", np.nan))
    slip = cfg.slippage_bps / 10000

    def fill(price, reason):
        return max(cfg.tick_size, tick_round(price * (1 - slip), cfg.tick_size)), reason

    if o <= stop:
        return fill(o, "gap_stop")
    if math.isfinite(middle) and o < middle:
        return fill(o, "gap_bb_middle")
    if math.isfinite(middle) and middle > stop and low < middle:
        return fill(middle, "bb_middle")
    if low <= stop:
        return fill(stop, "stop")
    return None


def simulate(prepared, cfg):
    """Chronological portfolio engine; indicators are causal and fills delayed."""
    cfg.validate()
    events, candidates = {}, {}
    for symbol, d in prepared.items():
        if cfg.exit_mode == "bb_middle":
            d = d.copy()
            d["bb_exit_level"] = d.bb_middle.shift(1)
        for stamp, row in d.iterrows():
            events.setdefault(stamp, {})[symbol] = row
        for i in np.flatnonzero(d.confirmation.to_numpy()):
            stamp = d.index[i]
            if i + 1 >= len(d) or d.index[i + 1] != stamp + FIVE:
                continue
            next_stamp = d.index[i + 1]
            if stamp.date() != next_stamp.date():
                continue
            candidates.setdefault(next_stamp, []).append((symbol, d.iloc[i]))
    cash, peak, max_dd = cfg.capital, cfg.capital, 0.0
    trades, position = [], None
    daily_entries = {}

    def close_position(stamp, price, reason):
        nonlocal cash, position
        p = position
        if cfg.exit_mode == "bb_middle":
            p["exit_bb_middle"] = float(events[stamp][p["symbol"]].bb_exit_level)
        gross = p["quantity"] * (price - p["entry"])
        fees = p["quantity"] * (price + p["entry"]) * cfg.fee_bps / 10000
        cash += gross - fees
        trades.append({**p, "exit_time": stamp, "exit": price, "reason": reason,
                       "gross_pnl": gross, "costs": fees, "net_pnl": gross - fees,
                       "net_R": (gross - fees) / (p["quantity"] * (p["entry"] - p["stop"])),
                       "equity_after": cash})
        position = None

    for stamp in sorted(events):
        bars = events[stamp]
        active_at_open = position is not None
        if position is not None:
            symbol = position["symbol"]
            if symbol not in bars:
                raise ValueError(f"Missing bar for held symbol {symbol} at {stamp}")
            b = bars[symbol]
            if stamp.time() >= cfg.square_off:
                price = max(cfg.tick_size, tick_round(float(b.open) * (1 - cfg.slippage_bps / 10000), cfg.tick_size))
                close_position(stamp, price, "square_off")
            else:
                outcome = stop_target_exit(b, position, cfg)
                if outcome:
                    close_position(stamp, *outcome)
        if not active_at_open and cfg.entry_start <= stamp.time() <= cfg.entry_end:
            count = daily_entries.get(stamp.date(), 0)
            ranked = sorted(candidates.get(stamp, []), key=lambda x:
                            (-float(x[1].signal_rvol), x[0]) if cfg.volume_filter else (0, x[0]))
            for symbol, conf in ranked:
                if count >= cfg.max_trades or cash <= 0:
                    break
                b = bars[symbol]
                entry = tick_round(float(b.open) * (1 + cfg.slippage_bps / 10000), cfg.tick_size, up=True)
                stop = tick_round(float(conf.signal_stop), cfg.tick_size)
                if not (entry > stop > 0) or float(b.open) <= stop:
                    continue
                target = (tick_round(entry + 2 * (entry - stop), cfg.tick_size, up=True)
                          if cfg.exit_mode == "target" else np.nan)
                # Budget approximate stop slippage and round-trip costs too.
                expected_stop_fill = max(cfg.tick_size, tick_round(stop * (1 - cfg.slippage_bps / 10000), cfg.tick_size))
                loss_per_share = entry - expected_stop_fill + (entry + expected_stop_fill) * cfg.fee_bps / 10000
                quantity = math.floor(min(cash * cfg.risk_fraction / loss_per_share,
                                          cash * cfg.buying_power_multiple / (entry * (1 + cfg.fee_bps / 10000))))
                if quantity <= 0:
                    continue
                position = {"symbol": symbol, "signal_time": conf.signal_time,
                            "confirmation_time": conf.name, "entry_time": stamp,
                            "entry": entry, "stop": stop, "target": target,
                            "quantity": quantity, "signal_rvol": float(conf.signal_rvol)}
                daily_entries[stamp.date()] = count + 1
                # Slippage could put a modeled entry above that bar's observed high;
                # retained as an adverse execution-cost assumption, not an HA fill.
                outcome = stop_target_exit(b, position, cfg)
                if outcome:
                    close_position(stamp, *outcome)
                break
        equity = cash
        if position:
            close = float(bars[position["symbol"]].close)
            equity += position["quantity"] * (close - position["entry"])
            equity -= position["quantity"] * (close + position["entry"]) * cfg.fee_bps / 10000
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    if position:
        raise ValueError("Dataset ended with an open position; complete session required")
    result = pd.DataFrame(trades)
    wins = int((result.net_pnl > 0).sum()) if len(result) else 0
    print(f"Trades: {len(result)} | Net P&L: {cash - cfg.capital:.2f} | Final equity: {cash:.2f}")
    print(f"Win rate: {wins / len(result):.2%}" if len(result) else "No trades. Check warmup and filters.")
    print(f"Maximum drawdown at sampled bar closes: {max_dd:.2%} (not intrabar drawdown)")
    return result


def download(args):
    """Read-only OpenAlgo history; SDK dependency is optional."""
    from openalgo import api
    key = os.environ.get("OPENALGO_API_KEY")
    if not key:
        raise ValueError("Set OPENALGO_API_KEY in your environment; do not hardcode it")
    first, last = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if first > last or last >= pd.Timestamp.now(tz=TZ).date():
        raise ValueError("Use a valid date range ending before today (completed sessions)")
    client = api(api_key=key, host=os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5000"))
    frames = []
    for symbol in dict.fromkeys(s.strip().upper() for s in args.symbols.split(",") if s.strip()):
        start = first
        while start <= last:
            end = min(start + timedelta(days=29), last)
            response = client.history(symbol=symbol, exchange="NSE", interval="5m",
                                      start_date=start.isoformat(), end_date=end.isoformat())
            if not isinstance(response, pd.DataFrame) or response.empty:
                raise ValueError(f"No DataFrame for {symbol} {start}..{end}; check OpenAlgo history")
            d = response.copy()
            if not isinstance(d.index, pd.DatetimeIndex):
                raise ValueError("Expected OpenAlgo history DatetimeIndex; inspect installed SDK output")
            d.index = pd.DatetimeIndex([ist_timestamp(x) for x in d.index])
            # Vendor extended-session bars are excluded deliberately.
            d = d[(d.index.time >= time(9, 15)) & (d.index.time < time(15, 30))]
            d.index.name = "timestamp"
            d["symbol"] = symbol
            frames.append(d.reset_index()[["timestamp", "symbol", "open", "high", "low", "close", "volume"]])
            start = end + timedelta(days=1)
    if not frames:
        raise ValueError("Supply at least one symbol")
    pd.concat(frames).to_csv(args.out, index=False)
    read_candles(args.out)  # fail explicitly on incomplete/invalid returned sessions
    print(f"Saved validated history to {args.out}")


def selftest():
    """Small deterministic regression checks, never requests data or places orders."""
    import tempfile
    from dataclasses import replace
    cfg = Config(slippage_bps=0, fee_bps=0, image_filters=False, volume_days=1)
    idx = pd.date_range("2026-01-05 09:15", periods=6, freq="5min", tz=TZ)
    d = pd.DataFrame({"open": [99]*6, "high": [101]*6, "low": [98]*6,
                      "close": [99, 102, 104, 105, 105, 105],
                      "ha_open": [98, 100, 102, 103, 103, 103],
                      "ha_close": [99, 102, 104, 105, 105, 105],
                      "ha_low": [98, 100, 102, 103, 103, 103],
                      "ha_high": [100, 103, 105, 106, 106, 106],
                      "bb_upper": [100]*6, "vwap": [98]*6, "rvol": [3]*6}, index=idx, dtype=float)
    s, c = pattern_flags(d, cfg)
    assert s.tolist() == [False, True, False, False, False, False]
    assert c.tolist() == [False, False, True, False, False, False]
    # A bullish candle's high can cross BB/VWAP with its close below both.
    wick_break = d.copy()
    wick_break.loc[idx[1], ["ha_open", "ha_low", "ha_close", "vwap"]] = [99.0, 99.0, 99.5, 100.5]
    high_cfg = replace(cfg, image_filters=True, volume_filter=False, breakout_source="high")
    high_signals, high_confirms = pattern_flags(wick_break, high_cfg)
    assert high_signals.iloc[1] and high_confirms.iloc[2]
    assert not pattern_flags(wick_break, replace(high_cfg, breakout_source="close"))[0].iloc[1]
    wick_break.loc[idx[2], "ha_close"] = 102.9
    assert not pattern_flags(wick_break, high_cfg)[1].any(), "Confirmation must still close above signal high"
    w = d.copy(); w.loc[idx[2], "ha_low"] = 101
    assert not pattern_flags(w, cfg)[1].any(), "Lower wick must invalidate confirmation"
    w = d.drop(idx[2]); assert not pattern_flags(w, cfg)[1].any(), "Missing next bar must expire signal"
    w = d.copy(); w.loc[idx[2], "ha_close"] = 102.9
    assert not pattern_flags(w, cfg)[1].any(), "High-only breakout must not confirm"
    p = {"stop": 96, "target": 108}
    assert stop_target_exit({"open":100,"high":110,"low":95}, p, cfg) == (96, "both_hit_stop_first")
    assert stop_target_exit({"open":94,"high":100,"low":93}, p, cfg) == (94, "gap_stop")
    assert stop_target_exit({"open":110,"high":112,"low":109}, p, cfg) == (108, "target")
    trail_cfg = replace(cfg, exit_mode="bb_middle")
    assert stop_target_exit({"open":110,"high":120,"low":109,"bb_exit_level":100}, p, trail_cfg) is None, "2R must not exit a trailing trade"
    assert stop_target_exit({"open":110,"high":120,"low":99,"bb_exit_level":100}, p, trail_cfg) == (100, "bb_middle")
    assert stop_target_exit({"open":99,"high":120,"low":98,"bb_exit_level":100}, p, trail_cfg) == (99, "gap_bb_middle")
    assert stop_target_exit({"open":110,"high":120,"low":100,"bb_exit_level":100}, p, trail_cfg) is None, "Touching BB is not below BB"
    assert stop_target_exit({"open":100,"high":110,"low":95,"bb_exit_level":90}, p, trail_cfg) == (96, "stop")
    rows = []
    for day, volume in [("2026-01-05",100), ("2026-01-06",300)]:
        for t in pd.date_range(day + " 09:15", periods=75, freq="5min", tz=TZ):
            rows.append(dict(timestamp=t, symbol="TEST", open=100., high=101., low=99., close=100., volume=float(volume)))
    raw = pd.DataFrame(rows)
    featured = indicators(raw, replace(cfg, volume_mode="time"))
    assert np.isnan(featured.rvol.iloc[74]) and featured.rvol.iloc[75] == 3
    daily = indicators(raw, cfg)
    assert np.isclose(daily.rvol.iloc[75], 3 / 75)
    changed = raw.copy(); changed.loc[100:, "close"] = 100.5
    f2 = indicators(changed, replace(cfg, volume_mode="time"))
    pd.testing.assert_frame_equal(featured.iloc[:100], f2.iloc[:100])
    # Isolate execution mechanics: confirmation at 09:25 -> actual 09:30 open.
    featured["confirmation"] = False
    featured.loc[featured.index[2], ["confirmation", "signal_stop", "signal_rvol"]] = [True, 96.0, 3.0]
    featured.loc[featured.index[3], ["open", "high", "low", "close"]] = [101., 111., 100., 110.]
    trades = simulate({"TEST": featured}, cfg)
    assert len(trades) == 1 and trades.iloc[0].entry == 101 and trades.iloc[0].target == 111
    assert trades.iloc[0].entry_time == featured.index[3]
    assert trades.iloc[0].reason == "target"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "test.csv"
        raw.to_csv(path, index=False); read_candles(path)
        raw.iloc[1:].to_csv(path, index=False)
        try:
            read_candles(path)
        except ValueError:
            pass
        else:
            raise AssertionError("Incomplete session must fail")
    print("PASS: patterns, wick rejection, expiry, HA-close breakout, gap/ambiguous exits,")
    print("RVOL timing, causal indicators, next-bar execution, target formula, input validation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("backtest", help="Backtest actual OHLCV CSV; never places orders")
    b.add_argument("--csv", required=True)
    b.add_argument("--out", default="trades.csv")
    b.add_argument("--volume-mode", choices=["daily", "time"], default="daily")
    b.add_argument("--breakout-source", choices=["close", "high"], default="close")
    b.add_argument("--exit-mode", choices=["target", "bb_middle"], default="target")
    b.add_argument("--skip-volume-filter", action="store_true",
                   help="Disable RVOL eligibility and its session warmup; retain VWAP")
    b.add_argument("--volume-days", type=int, default=20)
    b.add_argument("--volume-multiple", type=float, default=2.)
    b.add_argument("--stop-source", choices=["ha", "real"], default="ha")
    b.add_argument("--no-image-filters", action="store_true")
    b.add_argument("--capital", type=float, default=10000.)
    b.add_argument("--risk-fraction", type=float, default=.005)
    b.add_argument("--buying-power-multiple", type=float, default=1.)
    b.add_argument("--tick-size", type=float, default=.01)
    b.add_argument("--slippage-bps", type=float, default=5.)
    b.add_argument("--fee-bps", type=float, default=5.)
    b.add_argument("--max-trades", type=int, default=3)
    dl = commands.add_parser("download", help="Read-only OpenAlgo history download")
    dl.add_argument("--symbols", required=True, help="Comma-separated broker NSE symbols")
    dl.add_argument("--start", required=True)
    dl.add_argument("--end", required=True)
    dl.add_argument("--out", default="candles.csv")
    commands.add_parser("selftest", help="Run deterministic mechanics checks")
    args = parser.parse_args()
    try:
        if args.command == "selftest":
            selftest()
        elif args.command == "download":
            download(args)
        else:
            cfg = Config(**{name: getattr(args, name) for name in (
                "volume_mode", "volume_days", "volume_multiple", "stop_source", "capital",
                "risk_fraction", "buying_power_multiple", "tick_size", "slippage_bps", "fee_bps", "max_trades")},
                image_filters=not args.no_image_filters, volume_filter=not args.skip_volume_filter,
                breakout_source=args.breakout_source, exit_mode=args.exit_mode)
            cfg.validate()
            raw = read_candles(args.csv)
            prepared = {}
            for symbol, group in raw.groupby("symbol"):
                if cfg.volume_filter and group.timestamp.dt.date.nunique() <= cfg.volume_days:
                    raise ValueError(f"{symbol}: need more than {cfg.volume_days} full sessions")
                prepared[symbol] = indicators(group, cfg)
            result = simulate(prepared, cfg)
            if result.empty:
                result = pd.DataFrame(columns=["symbol", "signal_time", "confirmation_time", "entry_time", "entry", "stop", "target", "quantity", "signal_rvol", "exit_time", "exit", "reason", "gross_pnl", "costs", "net_pnl", "net_R", "equity_after"])
            result.to_csv(args.out, index=False)
            print(f"Saved {args.out}. Simulation only; costs are configurable assumptions.")
    except (ValueError, ImportError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
