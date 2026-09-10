"""API-only Nifty 50 baseline and bounded, chronological strategy research.

No OHLCV cache, downloads, database reads, or trading endpoints. Market data is
held in RAM. Only research results, trade ledgers and coverage metadata persist.
Run with backtesting/.venv/Scripts/python.exe and --help for options.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

ROOT = Path(__file__).resolve().parents[2]
NAME = "NIFTY50_BB_VWAP_HEIKIN_ASHI"
OUTPUT = ROOT / "backtesting" / "stratagies_Backtest_output" / NAME
SOURCE = Path(__file__).with_name("nifty500_bb_vwap_heikin_ashi_openalgo.py")
UNIVERSE_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
INITIAL_CAPITAL = 10_000.0
NSE_CHARGES = "https://fyers.in/charges-list"


@dataclass(frozen=True)
class Parameters:
    name: str = "baseline"
    bb_length: int = 20
    bb_multiplier: float = 2.0
    top_gainer_pct: float = 1.0
    volume_multiplier: float = 2.0
    stop_mode: str = "ha_close_fixed"
    fixed_risk: float = 10.0
    atr_multiple: float = 1.5
    risk_fraction: float = 0.0
    reward_r: float = 2.0
    trail_after_target: bool = True
    entry_end: int = 15 * 60
    max_trades: int = 3
    daily_loss_fraction: float = 0.0
    min_rvol: float = 0.0
    max_extension_atr: float = 0.0


def experiments():
    """Fixed before looking at returns. A modest search limits multiple testing."""
    baseline = Parameters()
    enhanced = replace(baseline, name="atr_risk", stop_mode="atr_hard",
                       risk_fraction=0.01, daily_loss_fraction=0.025)
    candidates = [baseline, replace(baseline, name="fixed_hard_stop", stop_mode="fixed_hard"),
                  enhanced]
    for length in (15, 20, 25):
        for multiple in (1.8, 2.0, 2.2):
            for atr in (1.0, 1.5, 2.0):
                candidates.append(replace(enhanced, name=f"bb{length}_{multiple}_atr{atr}",
                                          bb_length=length, bb_multiplier=multiple,
                                          atr_multiple=atr))
    candidates += [replace(enhanced, name="early_entries", entry_end=13 * 60 + 30),
                   replace(enhanced, name="relative_volume", min_rvol=1.5),
                   replace(enhanced, name="extension_filter", max_extension_atr=2.0),
                   replace(enhanced, name="fixed_2R", trail_after_target=False),
                   replace(enhanced, name="risk_half_percent", risk_fraction=0.005)]
    return candidates


def normalize(frame):
    if not isinstance(frame, pd.DataFrame):
        # Do not print arbitrary API error payloads: they may contain credentials.
        code = frame.get("error_type", frame.get("status", "unknown")) if isinstance(frame, dict) else "type"
        raise RuntimeError(f"History API did not return candles ({code})")
    frame = frame.copy()
    if "timestamp" in frame:
        stamp = frame.pop("timestamp")
        frame.index = (pd.to_datetime(stamp, unit="s", utc=True)
                       if pd.api.types.is_numeric_dtype(stamp) else pd.to_datetime(stamp))
    else:
        frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("Asia/Kolkata").tz_localize(None)
    if frame.index.has_duplicates:
        raise RuntimeError("Duplicate API candle timestamps")
    frame = frame.sort_index()[["open", "high", "low", "close", "volume"]].astype(float)
    if frame.empty:
        return frame
    invalid = (~np.isfinite(frame).all(axis=1) | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
               | (frame.volume < 0) | (frame.high < frame[["open", "close", "low"]].max(axis=1))
               | (frame.low > frame[["open", "close", "high"]].min(axis=1)))
    if invalid.any():
        raise RuntimeError(f"Invalid OHLCV rows: {int(invalid.sum())}")
    return frame


class History:
    def __init__(self):
        load_dotenv(find_dotenv(str(ROOT / ".env")), override=False)
        key = os.getenv("OPENALGO_API_KEY", "")
        if not key:
            raise RuntimeError("OPENALGO_API_KEY is missing from the root .env or process environment")
        host = os.getenv("OPENALGO_HOST") or os.getenv("HOST_SERVER") or "http://127.0.0.1:5000"
        self.client = api(api_key=key, host=host)
        self.calls = 0
        self.coverage = []

    def fetch(self, symbol, start, end, interval="5m", exchange="NSE"):
        parts = []
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        chunk_days = 90 if interval == "5m" else 300
        while start <= end:
            stop = min(end, start + pd.Timedelta(days=chunk_days - 1))
            for attempt in range(3):
                try:
                    self.calls += 1
                    response = self.client.history(symbol=symbol, exchange=exchange,
                        interval=interval, start_date=str(start.date()), end_date=str(stop.date()), source="api")
                    if isinstance(response, dict) and response.get("error_type") == "no_data":
                        # Coverage checks distinguish leading absence from holes inside history.
                        data = pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                                            index=pd.DatetimeIndex([]), dtype=float)
                    else:
                        data = normalize(response)
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise RuntimeError(f"API history failed: {symbol} {interval} {start.date()}..{stop.date()}; "
                                           f"{type(exc).__name__}") from None
                    time.sleep(2 ** attempt)
            parts.append(data)
            time.sleep(0.25)
            start = stop + pd.Timedelta(days=1)
        result = pd.concat(parts).sort_index()
        if result.index.has_duplicates:
            raise RuntimeError(f"Overlapping API chunks: {symbol}")
        return result


def fetch_universe():
    """Read public NSE JSON API in memory; require exactly 50 stock symbols."""
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                                "Referer": "https://www.nseindia.com/market-data/live-equity-market"})
        session.get("https://www.nseindia.com", timeout=30).raise_for_status()
        response = session.get(UNIVERSE_URL, timeout=30)
        response.raise_for_status()
        payload = response.json()
    symbols = sorted({row["symbol"] for row in payload.get("data", [])
                      if row.get("symbol") and row["symbol"] != "NIFTY 50"})
    if len(symbols) != 50:
        raise RuntimeError(f"NSE API returned {len(symbols)} stocks, expected exactly 50")
    return symbols, payload.get("timestamp", "not supplied")


def features(frame, daily, bb_length, bb_multiplier):
    """Keep source's session resets; daily volume denominator is strictly lagged."""
    previous = daily.close.shift(1)
    daily_mean = pd.Series(ta.sma(daily.volume.to_numpy(), 20), index=daily.index).shift(1)
    # Provider daily timestamps may include a time component.
    previous.index = previous.index.normalize()
    daily_mean.index = daily_mean.index.normalize()
    blocks = []
    for day, f in frame.groupby(frame.index.normalize(), sort=True):
        f = f.copy()
        o, h, l, c, v = (f[col].to_numpy() for col in ["open", "high", "low", "close", "volume"])
        hc = (o + h + l + c) / 4
        ho = np.empty(len(f))
        ho[0] = (o[0] + c[0]) / 2
        for i in range(1, len(f)):
            ho[i] = (ho[i - 1] + hc[i - 1]) / 2
        hh = np.maximum.reduce([h, ho, hc])
        hl = np.minimum.reduce([l, ho, hc])
        upper, middle, _ = ta.bbands(hc, period=bb_length, std_dev=bb_multiplier)
        f["hc"], f["hh"], f["upper"], f["middle"] = hc, hh, upper, middle
        f["vwap"] = ta.vwap(h, l, c, v, source="hlc3", anchor="Session")
        f["atr"] = ta.atr(h, l, c, period=14)
        f["wickless"] = (hc > ho) & (np.abs(hl - ho) <= np.maximum(1e-8, np.abs(ho) * 1e-10))
        f["gain"] = (c / previous.get(day, np.nan) - 1) * 100
        f["volume_ratio"] = np.cumsum(v) / daily_mean.get(day, np.nan)
        f["slot"] = (f.index.hour * 60 + f.index.minute - 555) // 5
        f["signal"] = ((f.hc > f.upper) & (f.hc.shift(1) <= f.upper.shift(1))
                       & (f.hc > f.vwap) & f.wickless & (f.slot >= bb_length + 1))
        f["confirmation"] = (f.hc > f.hh.shift(1)) & (f.hc > f.upper) & (f.hc > f.vwap) & f.wickless
        # Only completed bars enter feature values; the simulator fills after confirmation.
        blocks.append(f)
    result = pd.concat(blocks)
    # Time-of-day relative volume uses the same slot in 20 PREVIOUS sessions.
    cumulative = result.groupby(result.index.normalize()).volume.cumsum()
    means = cumulative.groupby(result.slot).transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    result["rvol"] = cumulative / means
    return result


def candidate_ranks(prepared, p):
    scores = pd.DataFrame(index=pd.DatetimeIndex(sorted(set().union(*(f.index for f in prepared.values())))))
    # NaN daily baseline must not suppress an otherwise valid top-gainer.
    for s, f in prepared.items():
        scores[s] = pd.concat([f.gain / p.top_gainer_pct,
                               f.volume_ratio / p.volume_multiplier], axis=1).max(axis=1)
    return scores.where(scores >= 1).rank(axis=1, ascending=False, method="first")


def opportunities(prepared, p, slippage_bps=5.0):
    ranks = candidate_ranks(prepared, p)
    opportunities_out = []
    slip = slippage_bps / 10_000
    for symbol, all_f in prepared.items():
        for _, f in all_f.groupby(all_f.index.normalize(), sort=True):
            rank = ranks[symbol].reindex(f.index).to_numpy()
            signal = (f.signal & (rank <= 30)).fillna(False).to_numpy()
            if p.min_rvol:
                signal &= (f.rvol >= p.min_rvol).fillna(False).to_numpy()
            if p.max_extension_atr:
                signal &= ((f.close - f.vwap) / f.atr <= p.max_extension_atr).fillna(False).to_numpy()
            # Reset entry cleaning on the following candle, so rejected global
            # portfolio entries don't suppress future independent setups.
            reset = np.roll(signal, 1)
            reset[0] = False
            signal = np.asarray(ta.exrem(signal, reset), dtype=bool)
            confirms = f.confirmation.to_numpy()
            stamps = f.index
            a = {col: f[col].to_numpy() for col in ["open", "high", "low", "close", "hc", "middle", "atr"]}
            for si in np.flatnonzero(signal):
                ci, ei = si + 1, si + 2
                if ei >= len(f) or not confirms[ci]:
                    continue
                if stamps[ei] - stamps[si] != pd.Timedelta(minutes=10):
                    continue
                entry_time = stamps[ei]
                if entry_time.hour * 60 + entry_time.minute > p.entry_end:
                    continue
                entry = a["open"][ei] * (1 + slip)
                risk = p.fixed_risk if p.stop_mode != "atr_hard" else float(a["atr"][ci]) * p.atr_multiple
                if not np.isfinite(risk) or risk <= 0 or risk >= entry:
                    continue
                stop, target = entry - risk, entry + p.reward_r * risk
                target_reached = False
                exit_price, exit_time, reason, worst = None, None, None, entry
                for j in range(ei, len(f)):
                    stamp = stamps[j]
                    if stamp.hour * 60 + stamp.minute >= 920:
                        exit_price, exit_time, reason = a["open"][j], stamp, "square_off"
                        worst = min(worst, exit_price)
                        break
                    if p.stop_mode != "ha_close_fixed" and a["low"][j] <= stop:
                        # Persistent actual-price stop, pessimistic stop-first if target also touched.
                        exit_price = min(a["open"][j], stop)
                        exit_time, reason = stamp + pd.Timedelta(minutes=5), "hard_stop"
                        worst = min(worst, exit_price)
                        break
                    worst = min(worst, a["low"][j])
                    if a["hc"][j] >= target:
                        target_reached = True
                        if not p.trail_after_target:
                            reason = "target_close"
                    if p.stop_mode == "ha_close_fixed" and not target_reached and a["hc"][j] <= stop:
                        reason = "ha_close_stop"
                    if a["hc"][j] < a["middle"][j] and reason is None:
                        reason = "bb_middle"
                    if reason:
                        if j + 1 >= len(f) or stamps[j + 1] - stamp != pd.Timedelta(minutes=5):
                            raise RuntimeError(f"Missing execution candle: {symbol} {stamp}")
                        exit_price, exit_time = a["open"][j + 1], stamps[j + 1]
                        worst = min(worst, exit_price)
                        break
                if exit_price is None:
                    raise RuntimeError(f"No square-off candle: {symbol} {entry_time.date()}")
                current_rank = rank[ci] if np.isfinite(rank[ci]) and rank[ci] <= 30 else 100 + rank[si]
                opportunities_out.append(dict(symbol=symbol, signal_time=stamps[si] + pd.Timedelta(minutes=5),
                    entry_time=entry_time, exit_time=exit_time, entry_price=entry,
                    exit_price=exit_price * (1 - slip), risk_per_share=risk,
                    rank=current_rank, reason=reason, worst_price=worst))
    return sorted(opportunities_out, key=lambda row: (row["entry_time"], row["rank"], row["symbol"]))


def fees(turnover, sell=False):
    """Present-day Fyers rate approximation, held constant across historical years."""
    brokerage = min(20.0, turnover * 0.0003)
    exchange = turnover * 0.0000307
    sebi = turnover * 0.000001
    ipft = turnover * 0.000001
    gst = 0.18 * (brokerage + exchange + sebi + ipft)
    tax = turnover * (0.00025 if sell else 0.00003)
    return brokerage + exchange + sebi + ipft + gst + tax


def simulate(opps, p, days, initial=INITIAL_CAPITAL):
    equity, last_exit = initial, pd.Timestamp.min
    trades, daily_pnl = [], pd.Series(0.0, index=days)
    current_day, count, day_start, day_pnl = None, 0, initial, 0.0
    for opportunity in opps:
        day = opportunity["entry_time"].normalize()
        if day not in daily_pnl.index:
            continue
        if day != current_day:
            current_day, count, day_start, day_pnl = day, 0, equity, 0.0
        # Source only scans when flat, and skips scanning on its exit cycle.
        if opportunity["signal_time"] <= last_exit or count >= p.max_trades or equity <= 0:
            continue
        if p.daily_loss_fraction and day_pnl <= -day_start * p.daily_loss_fraction:
            continue
        entry, exit_price = opportunity["entry_price"], opportunity["exit_price"]
        # Fixed source notional, capped by remaining account margin; no automatic recapitalization.
        quantity = math.floor(min(50_000.0, equity * 5) / entry)
        if p.risk_fraction:
            quantity = min(quantity, math.floor(equity * p.risk_fraction / opportunity["risk_per_share"]))
        while quantity > 0 and quantity * entry / 5 + fees(quantity * entry) > equity:
            quantity -= 1
        if quantity < 1:
            continue
        buy_fee, sell_fee = fees(quantity * entry), fees(quantity * exit_price, True)
        gross = quantity * (exit_price - entry)
        net = gross - buy_fee - sell_fee
        row = dict(opportunity, quantity=quantity, gross_pnl=gross, buy_fee=buy_fee,
                   sell_fee=sell_fee, net_pnl=net, equity_before=equity, equity_after=equity + net,
                   adverse_equity=equity + quantity * (opportunity["worst_price"] - entry) - buy_fee)
        trades.append(row)
        equity += net
        daily_pnl.loc[day] += net
        day_pnl += net
        count += 1
        last_exit = opportunity["exit_time"]
    return pd.DataFrame(trades), initial + daily_pnl.cumsum()


def metrics(equity, trades=None, initial=INITIAL_CAPITAL):
    returns = equity.pct_change()
    if len(equity):
        returns.iloc[0] = equity.iloc[0] / initial - 1
    returns = returns.fillna(0)
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    ending = float(equity.iloc[-1])
    total = ending / initial - 1
    peak = equity.cummax().clip(lower=initial)
    dd = equity / peak - 1
    stdev = returns.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2))
    result = dict(total_return_pct=total * 100, cagr_pct=((ending / initial) ** (1 / years) - 1) * 100 if ending > 0 else -100,
                  sharpe=float(returns.mean() / stdev * np.sqrt(252)) if stdev > 0 else 0.0,
                  sortino=float(returns.mean() / downside * np.sqrt(252)) if downside > 0 else None,
                  max_daily_drawdown_pct=float(dd.min() * 100), ending_equity=ending,
                  trading_days=len(equity))
    if trades is not None:
        pnl = trades.net_pnl if len(trades) else pd.Series(dtype=float)
        losses, wins = -pnl[pnl < 0].sum(), pnl[pnl > 0].sum()
        result.update(trades=len(trades), win_rate_pct=float((pnl > 0).mean() * 100) if len(pnl) else 0,
                      profit_factor=float(wins / losses) if losses else None,
                      net_pnl=float(pnl.sum()), gross_pnl=float(trades.gross_pnl.sum()) if len(trades) else 0,
                      total_fees=float((trades.buy_fee + trades.sell_fee).sum()) if len(trades) else 0,
                      average_trade=float(pnl.mean()) if len(pnl) else 0)
    return result


def selection_score(opps, p, development_days):
    """Three chronological yearly development folds, each funded identically."""
    folds, counts, returns = [], [], []
    for days in np.array_split(development_days, 3):
        trades, equity = simulate(opps, p, pd.DatetimeIndex(days))
        m = metrics(equity, trades)
        folds.append(m["sharpe"] - abs(m["max_daily_drawdown_pct"]) / 20)
        counts.append(m["trades"])
        returns.append(m["total_return_pct"])
    score = float(np.mean(folds) - 0.5 * np.std(folds))
    if min(counts) < 30 or sum(r > 0 for r in returns) < 2:
        score = -1e9
    return score, folds


def vectorbt_audit(trades):
    """Replay explicit fills, costs and whole shares, with shared cash across symbols."""
    import vectorbt as vbt
    if trades.empty:
        return {"status": "no trades"}
    symbols = sorted(trades.symbol.unique())
    index = pd.DatetimeIndex(sorted(set(trades.entry_time) | set(trades.exit_time)))
    prices = pd.DataFrame(np.nan, index=index, columns=symbols)
    sizes, costs = prices.copy(), prices.copy()
    for row in trades.itertuples():
        for stamp, price, quantity, cost in [(row.entry_time, row.entry_price, row.quantity, row.buy_fee),
                                             (row.exit_time, row.exit_price, -row.quantity, row.sell_fee)]:
            prices.loc[stamp, row.symbol] = price
            sizes.loc[stamp, row.symbol] = quantity
            costs.loc[stamp, row.symbol] = cost
    # The additional 40k is a fixed borrowing facility, not strategy equity.
    pf = vbt.Portfolio.from_orders(prices.ffill(), size=sizes, price=prices,
        fixed_fees=costs.fillna(0), fees=0, init_cash=50_000, cash_sharing=True,
        group_by=True, direction="longonly", min_size=1, size_granularity=1, freq="5min")
    net = float(pf.value().iloc[-1]) - 50_000
    expected = float(trades.net_pnl.sum())
    if not np.isclose(net, expected, atol=0.01):
        raise AssertionError(f"VectorBT replay discrepancy: {net} versus {expected}")
    return {"status": "passed", "net_pnl": net, "orders": len(pf.orders.records),
            "note": "Independent fill/fee audit; risk metrics use the actual 10k account."}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8")


def export_report(out, comparisons, curves, baseline_trades, best_trades, trials, winner, manifest, status):
    comparisons.to_csv(out / "strategy_vs_benchmark.csv")
    baseline_trades.to_csv(out / "baseline_trades.csv", index=False)
    best_trades.to_csv(out / "selected_candidate_trades.csv", index=False)
    curves.to_csv(out / "daily_equity.csv")
    trials.to_csv(out / "experiments.tsv", sep="\t", index=False)
    write_json(out / "selected_candidate.json", {"parameters": asdict(winner), "status": status})
    write_json(out / "manifest.json", manifest)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=["Account value", "Daily drawdown (%)"])
    for name in curves:
        values = curves[name]
        fig.add_trace(go.Scatter(x=values.index, y=values, name=name), row=1, col=1)
        fig.add_trace(go.Scatter(x=values.index, y=(values / values.cummax().clip(lower=INITIAL_CAPITAL) - 1) * 100,
                                name=name, showlegend=False), row=2, col=1)
    fig.update_layout(template="plotly_dark", title=NAME, height=800)
    fig.write_html(out / "equity_drawdown.html", include_plotlyjs=True)
    for metric in ["development_return_pct", "development_sharpe"]:
        grid = trials.pivot_table(index="bb_length", columns="bb_multiplier", values=metric, aggfunc="median")
        heat = go.Figure(go.Heatmap(z=grid.values, x=grid.columns, y=grid.index, colorbar_title=metric))
        heat.update_layout(template="plotly_dark", title=f"Development only: median {metric} across risk variants",
                           xaxis_title="BB multiplier", yaxis_title="BB period")
        heat.write_html(out / f"{metric}_heatmap.html", include_plotlyjs=True)
    groups = []
    for name, trades in [("baseline", baseline_trades), ("selected", best_trades)]:
        if not trades.empty:
            grouped = trades.groupby("symbol").agg(trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum"),
                win_rate=("net_pnl", lambda s: float((s > 0).mean())), fees=("buy_fee", "sum"))
            grouped["fees"] += trades.groupby("symbol").sell_fee.sum()
            grouped = grouped.reindex(manifest["universe"])
            grouped.index.name = "symbol"
            grouped[["trades", "net_pnl", "fees"]] = grouped[["trades", "net_pnl", "fees"]].fillna(0)
            grouped["variant"] = name
            groups.append(grouped.reset_index())
    if groups:
        pd.concat(groups).to_csv(out / "per_stock_results.csv", index=False)
    monthly = curves.diff()
    monthly.iloc[0] = curves.iloc[0] - INITIAL_CAPITAL
    monthly.resample("ME").sum().to_csv(out / "monthly_pnl.csv")
    monthly.resample("YE").sum().to_csv(out / "yearly_pnl.csv")
    body = f"""# {NAME}: detailed report

Research status: **{status}**. Selected configuration: `{winner.name}`.

Requested window: {manifest['start']} through {manifest['end']}. Actual data end: {manifest['actual_end']}.
Universe: 50 stocks returned by the NSE JSON API at run time. **Current-constituent survivorship bias applies**;
this is not a reconstruction of historical Nifty 50 membership. New listings and renamed securities are not backfilled.

## Results

{comparisons.to_markdown()}

Returns measure the Rs 10,000 shared account after fees and assumed slippage, not 50 independently funded accounts.
Sharpe and Sortino use daily returns, 252 trading days and zero risk-free rate. Drawdown is daily closing drawdown;
it understates intraday risk. Trade ledgers include each trade's adverse account value. NIFTY is a price-index
benchmark, without dividends or execution fees, normalized from the close preceding the evaluation window.

## Baseline fidelity and execution

The original source uses BB(20,2) on session-reset Heikin Ashi close, session VWAP, a wickless bullish
upper-band crossover and immediate-next-bar confirmation above the signal HA high. The scanner uses the
completed real close versus previous daily close, and cumulative volume versus the prior 20 daily sessions.
It ranks up to 30 candidates. Pending setups can confirm after falling out of the scanner. Quote snapshots
are unavailable historically, so completed closes replace live quotes. Scanner activity stops while positioned.
The first source-eligible signal requires 22 completed candles (11:05 IST with a full session).

The source's synthetic HA paper fills are replaced with actual next-bar opens plus slippage. Its baseline
stop remains a HA-close condition and deactivates after 2R, while the BB-middle exit stays active throughout.
All positions close at 15:20. This is a bar-based reconstruction, not exact tick-by-tick live execution.
One position, at most three trades daily, integer quantities, fixed Rs 50,000 notional ceiling, and a 5x cap
on remaining equity apply. Entry fees must fit available margin. No external capital is injected after losses.

## Enhancements and experiment design

Search space: {len(trials)} predeclared configurations. Variants test BB sensitivity, persistent actual-price
fixed/ATR stops, 0.5%-1% account risk sizing, a daily loss cutoff, earlier entry cutoff, time-of-day relative
volume and VWAP-extension filtering. Hard stops use gap-aware fills; if stop and target coincide, stop wins.
Risk sizing excludes gap loss and trading fees, so actual loss can exceed its target.

The first three years form development data, split into three chronological folds. The fixed selection
score is mean(Sharpe - |drawdown%|/20) minus half its fold standard deviation. Each fold needs 30 trades,
and at least two folds need positive returns. The top five development candidates enter the fourth-year
validation comparison. A single candidate is then locked before evaluating the fifth-year holdout.
No holdout return enters parameter selection. The full-window selected curve is retrospective, not wholly
out of sample. Holdout failure is reported and does not trigger another search on that holdout.

`autoresearch/README.md`, `program.md`, `prepare.py` and `train.py` describe GPU language-model research.
This adaptation uses its fixed evaluator, baseline-first discipline, experiment ledger and keep/discard
decisions. It does not train a language model or run its data downloader.

## Costs, data and reproducibility

Assumed slippage: 5 basis points each side; selected strategy is also evaluated at 10 bps each side.
Intraday brokerage: min(Rs 20, 0.03% turnover) per side, STT 0.025% sell, stamp 0.003% buy,
exchange 0.00307%, SEBI 0.0001%, assumed IPFT 0.0001%, GST 18% on brokerage plus exchange/SEBI/IPFT.
The current cost approximation is applied uniformly; historical fee changes and charge rounding are not reconstructed.
Rate source: [Fyers charges]({NSE_CHARGES}). Intraday leverage availability per stock/day is assumed.

History is requested through OpenAlgo `history(source='api')` in 90-day intraday and 300-day daily chunks.
No raw candles, quote data, market-data files or price caches are saved. Coverage metadata and the source-code
hash appear in `manifest.json` and `coverage.csv`. No local history databases are read. Data-quality validation
requires complete regular sessions. NIFTY intraday coverage identifies nonstandard sessions, which remain
cash days for the strategy. Leading unavailable stock history is disclosed without inventing prices;
holes after a stock's first available daily bar stop the run instead of generating misleading performance.
Provider corporate-action adjustment methodology remains unverified. Past index membership, dividends,
symbol changes and spin-offs can limit comparisons. These results establish the best candidate within the
declared search and assumptions; they do not establish an absolute best strategy or future profitability.

## Files

`experiments.tsv`: all trials and decisions. `baseline_trades.csv` and `selected_candidate_trades.csv`: fills,
costs and P&L. `per_stock_results.csv`, `monthly_pnl.csv`, `yearly_pnl.csv`: attribution.
`equity_drawdown.html`: offline interactive chart. Development heatmaps show parameter sensitivity.
`selected_candidate.json`: locked parameters and promotion status. `validation.csv`: shortlist evaluation.
"""
    (out / f"{NAME}_detailed_report.md").write_text(body, encoding="utf-8")
    (out / "README.md").write_text(
        f"# {NAME}\n\nRun completed. Research conclusion: {status}.\n\n"
        f"Read [{NAME}_detailed_report.md]({NAME}_detailed_report.md) for results and limitations.\n"
        "Selected parameters are in selected_candidate.json. A completed run does not necessarily validate an enhancement.\n",
        encoding="utf-8")


def run(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if end > pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize():
        raise RuntimeError("Cannot request future dates")
    write_json(out / "run_status.json", {"status": "preflight", "start": start, "end": end,
               "raw_data_persistence": False})
    history = History()
    # Probe authentication and earliest intraday availability before the expensive run.
    probe = history.fetch("SBIN", start, start + pd.Timedelta(days=7))
    if probe.empty:
        raise RuntimeError("SBIN API preflight returned no candles at the requested five-year start")
    if args.preflight:
        print("History API preflight passed.", flush=True)
        return
    symbols, universe_timestamp = fetch_universe()
    bench = history.fetch("NIFTY", start - pd.Timedelta(days=10), end, "D", "NSE_INDEX")
    bench.index = bench.index.normalize()
    today = pd.Timestamp.now(tz="Asia/Kolkata")
    if today.hour * 60 + today.minute < 930:
        bench = bench[bench.index < today.tz_localize(None).normalize()]
    days = bench.loc[start:end].index
    if len(days) < 1100 or days[-1] < end - pd.Timedelta(days=7):
        raise RuntimeError("Benchmark API does not cover the requested five years through the latest session")
    benchmark_bars = history.fetch("NIFTY", start, end, "5m", "NSE_INDEX")
    benchmark_counts = benchmark_bars.between_time("09:15", "15:25").groupby(
        benchmark_bars.between_time("09:15", "15:25").index.normalize()).size()
    regular_days = days.intersection(benchmark_counts[benchmark_counts == 75].index)
    excluded_days = days.difference(regular_days)
    if len(excluded_days) > 20:
        raise RuntimeError("More than 20 benchmark sessions lack regular 5-minute coverage; investigate API data")
    raw, daily = {}, {}
    for i, symbol in enumerate(symbols, 1):
        print(f"API history {i}/50: {symbol}", flush=True)
        daily[symbol] = history.fetch(symbol, start - pd.Timedelta(days=65), end, "D")
        if daily[symbol].empty:
            raise RuntimeError(f"No daily history for {symbol}; cannot verify symbol mapping")
        raw[symbol] = history.fetch(symbol, start - pd.Timedelta(days=45), end)
        if raw[symbol].empty:
            raise RuntimeError(f"No intraday history for {symbol}; cannot verify symbol mapping")
        raw[symbol] = raw[symbol].between_time("09:15", "15:25")
        raw[symbol] = raw[symbol][raw[symbol].index.normalize().isin(regular_days.union(
            raw[symbol].index.normalize().unique()[raw[symbol].index.normalize().unique() < start]))]
        counts = raw[symbol].groupby(raw[symbol].index.normalize()).size()
        first_daily = daily[symbol].index.min().normalize()
        expected = regular_days[regular_days >= first_daily]
        missing = expected.difference(counts.index)
        incomplete = counts[(counts.index >= start) & (counts.index <= days[-1]) & (counts != 75)]
        info = dict(symbol=symbol, rows=len(raw[symbol]), first=str(raw[symbol].index.min()),
                    last=str(raw[symbol].index.max()), missing_sessions=len(missing), incomplete_sessions=len(incomplete),
                    leading_unavailable_sessions=int((regular_days < first_daily).sum()),
                    note="Leading absence may reflect listing, rename or provider limits; not backfilled")
        history.coverage.append(info)
        pd.DataFrame(history.coverage).to_csv(out / "coverage.csv", index=False)
        if len(missing) or len(incomplete):
            raise RuntimeError(f"Incomplete five-year history for {symbol}: {len(missing)} missing and "
                               f"{len(incomplete)} incomplete sessions. See coverage.csv; no performance claimed.")
    dev_end, valid_end = start + pd.DateOffset(years=3), start + pd.DateOffset(years=4)
    development = days[days < dev_end]
    validation = days[(days >= dev_end) & (days < valid_end)]
    holdout = days[days >= valid_end]
    candidates = experiments()
    cached_features, all_opps, results = {}, {}, []
    for i, p in enumerate(candidates):
        print(f"Experiment {i + 1}/{len(candidates)}: {p.name}", flush=True)
        key = (p.bb_length, p.bb_multiplier)
        if key not in cached_features:
            cached_features.clear()  # Bounded RAM; each group is processed consecutively where possible.
            cached_features[key] = {s: features(raw[s], daily[s], *key) for s in symbols}
        opps = opportunities(cached_features[key], p)
        all_opps[p.name] = opps
        trades, equity = simulate(opps, p, development)
        m = metrics(equity, trades)
        score, folds = selection_score(opps, p, development)
        results.append(dict(**asdict(p), selection_score=score, development_return_pct=m["total_return_pct"],
                            development_sharpe=m["sharpe"], development_drawdown_pct=m["max_daily_drawdown_pct"],
                            development_trades=m["trades"], fold_scores=json.dumps(folds), status="discard"))
        pd.DataFrame(results).to_csv(out / "experiments.tsv", sep="\t", index=False)
    trials = pd.DataFrame(results)
    trials.nlargest(10, "development_return_pct").to_csv(out / "top10_development_return.csv", index=False)
    trials.nlargest(10, "development_sharpe").to_csv(out / "top10_development_sharpe.csv", index=False)
    eligible = trials[trials.selection_score > -1e9].nlargest(5, "selection_score")
    shortlist = set(eligible.name) | {"baseline"}
    validations = []
    for p in candidates:
        if p.name not in shortlist:
            continue
        t, e = simulate(all_opps[p.name], p, validation)
        m = metrics(e, t)
        score = m["sharpe"] - abs(m["max_daily_drawdown_pct"]) / 20
        if m["trades"] < 30 or m["net_pnl"] <= 0:
            score = -1e9
        validations.append(dict(name=p.name, score=score, **m))
    val = pd.DataFrame(validations).sort_values("score", ascending=False)
    val.to_csv(out / "validation.csv", index=False)
    chosen = val.iloc[0]["name"] if val.iloc[0].score > -1e9 else "baseline"
    winner = next(p for p in candidates if p.name == chosen)
    # Persist the selection BEFORE holdout is simulated.
    write_json(out / "selection_lock.json", {"parameters": asdict(winner), "dev_end_exclusive": dev_end,
               "validation_end_exclusive": valid_end, "holdout_used_for_selection": False})
    base_t, base_e = simulate(all_opps["baseline"], candidates[0], days)
    best_t, best_e = simulate(all_opps[chosen], winner, days)
    comparisons = {"baseline_full": metrics(base_e, base_t), "selected_full": metrics(best_e, best_t)}
    for name, p in [("baseline", candidates[0]), ("selected", winner)]:
        t, e = simulate(all_opps[p.name], p, holdout)
        comparisons[f"{name}_holdout"] = metrics(e, t)
    reference = bench.loc[bench.index < start, "close"].iloc[-1]
    bench_e = bench.close.reindex(days) / reference * INITIAL_CAPITAL
    comparisons["NIFTY_full"] = metrics(bench_e)
    hold_reference = bench.loc[bench.index < holdout[0], "close"].iloc[-1]
    comparisons["NIFTY_holdout"] = metrics(bench.close.reindex(holdout) / hold_reference * INITIAL_CAPITAL)
    key = (winner.bb_length, winner.bb_multiplier)
    prepared = cached_features.get(key) or {s: features(raw[s], daily[s], *key) for s in symbols}
    stress_opps = opportunities(prepared, winner, slippage_bps=10)
    stress_t, stress_e = simulate(stress_opps, winner, holdout)
    comparisons["selected_holdout_10bps"] = metrics(stress_e, stress_t)
    good = (chosen != "baseline" and comparisons["selected_holdout"]["net_pnl"] > 0
            and comparisons["selected_holdout"]["sharpe"] > comparisons["baseline_holdout"]["sharpe"]
            and comparisons["selected_holdout"]["trades"] >= 30
            and comparisons["selected_holdout_10bps"]["net_pnl"] > 0)
    status = "enhancement passed holdout and cost stress" if good else "no validated enhancement; do not promote"
    trials.loc[trials.name == chosen, "status"] = "selected_before_holdout"
    manifest = dict(start=str(start.date()), end=str(end.date()), actual_end=str(days[-1].date()),
        universe=symbols, universe_api=UNIVERSE_URL, universe_timestamp=universe_timestamp,
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(), api_calls=history.calls,
        packages={p: importlib.metadata.version(p) for p in ["openalgo", "vectorbt", "numpy", "pandas"]},
        baseline_audit=vectorbt_audit(base_t), selected_audit=vectorbt_audit(best_t),
        development_end_exclusive=str(dev_end.date()), validation_end_exclusive=str(valid_end.date()),
        raw_data_saved=False, excluded_nonstandard_sessions=[str(d.date()) for d in excluded_days], status=status)
    curves = pd.DataFrame({"Baseline": base_e, "Selected": best_e, "NIFTY": bench_e})
    export_report(out, pd.DataFrame(comparisons).T, curves, base_t, best_t, trials, winner, manifest, status)
    write_json(out / "run_status.json", {"status": "completed", "research_conclusion": status})
    print(pd.DataFrame(comparisons).T.to_string(), flush=True)
    print(f"Report saved: {out}", flush=True)


def main():
    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=str((pd.Timestamp(today) - pd.DateOffset(years=5)).date()))
    parser.add_argument("--end", default=str(today))
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        # Known internal RuntimeErrors are sanitized; avoid raw third-party network payloads.
        detail = str(exc) if isinstance(exc, (RuntimeError, AssertionError)) else type(exc).__name__
        write_json(out / "run_status.json", {"status": "blocked", "reason": detail,
                   "start": args.start, "end": args.end, "performance_results_available": False})
        print(f"Research stopped: {detail}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
