#!/usr/bin/env python3
"""Crypto backtest: HA/BB/VWAP strategy on BTC, ETH, XAUT futures trade data.

Adapts the Indian-market HA/BB/VWAP strategy for 24/7 crypto markets.
Sessions = UTC calendar days; VWAP resets daily; no entry time restrictions.
Volume filter disabled per user request.

Usage:
    python backtesting/crypto_backtest.py
    python backtesting/crypto_backtest.py --symbols btcfut --timeframes 1m 5m
"""
from __future__ import annotations

import argparse
import os
import json
import math
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter


DATA_DIR = Path(r"D:\Personal\openalgo_Crypto\historical_data")
OUT_DIR = Path(r"D:\Personal\openalgo\backtesting\crypto_results")
FIVE = pd.Timedelta(minutes=5)


@dataclass
class CryptoConfig:
    allocation: float = 10000.0
    tick_size: float = 0.5
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    reward_r: float = 2.0
    bb_period: int = 20
    bb_std: float = 2.0
    stop_source: str = "ha"
    image_filters: bool = True
    risk_fraction: float = 0.005
    max_trades: int = 3
    volume_filter: bool = False
    min_qty: float = 0.0001

    def validate(self):
        assert self.allocation > 0
        assert 0 < self.risk_fraction <= 1
        assert self.tick_size > 0
        assert 0 <= self.fee_bps < 10000
        assert 0 <= self.slippage_bps < 10000
        assert self.bb_period >= 2
        assert self.min_qty > 0


# ─── Data Loading ──────────────────────────────────────────────────────────

def read_tick_file(zip_path: Path) -> pd.DataFrame:
    """Read one monthly file (real zip, or .csv that is actually a zip)."""
    def use_buffer(buf):
        return pd.read_csv(buf)
    try:
        with zipfile.ZipFile(zip_path) as z:
            frames = [use_buffer(z.open(n)) for n in z.namelist() if n.endswith('.csv')]
        df = pd.concat(frames, ignore_index=True) if frames else None
    except (zipfile.BadZipFile, NotImplementedError):
        df = None
    if df is None:
        df = pd.read_csv(zip_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
    df['price'] = pd.to_numeric(df['price'])
    df['size'] = pd.to_numeric(df['size']).abs()
    return df


def candle_files(symbol_dir: Path):
    patterns = list(symbol_dir.rglob("*.csv.zip")) + list(symbol_dir.rglob("*.csv"))
    return sorted(patterns)


def build_candles(ticks: pd.DataFrame, timeframe_minutes: int) -> pd.DataFrame:
    """Aggregate trade ticks into OHLCV candles."""
    ticks = ticks.copy()
    ticks['candle'] = ticks['timestamp'].dt.floor(f'{timeframe_minutes}min')
    candles = ticks.groupby('candle', sort=True).agg(
        open=('price', 'first'),
        high=('price', 'max'),
        low=('price', 'min'),
        close=('price', 'last'),
        volume=('size', 'sum')
    ).reset_index()
    candles.rename(columns={'candle': 'timestamp'}, inplace=True)
    assert (candles.high >= candles[['open', 'close', 'low']].max(axis=1)).all()
    assert (candles.low <= candles[['open', 'close', 'high']].min(axis=1)).all()
    assert (candles.volume > 0).all()
    return candles


def load_candles(symbol_dir: Path, timeframe_minutes: int):
    """Stream each monthly file, aggregate candles per file, keep only candles."""
    parts, files = [], candle_files(symbol_dir)
    for zip_path in files:
        ticks = read_tick_file(zip_path)
        parts.append(build_candles(ticks, timeframe_minutes))
    if not parts:
        raise ValueError(f"No data found in {symbol_dir}")
    candles = pd.concat(parts, ignore_index=True)
    candles = candles.sort_values('timestamp').drop_duplicates('timestamp', keep='last')
    return candles.reset_index(drop=True), files


def detect_tick_size(ticks_first_file: pd.DataFrame) -> float:
    """Auto-detect minimum tick size from the first ~200k price changes."""
    prices = ticks_first_file['price'].to_numpy()[:200001]
    if len(prices) < 2:
        return 0.01
    diffs = np.abs(np.diff(prices))
    diffs = diffs[diffs > 0]
    if not len(diffs):
        return 0.01
    candidate = float(diffs.min())
    for tick in [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0]:
        if candidate <= tick * 1.5:
            return tick
    return round(candidate, 4)


# ─── Indicators ────────────────────────────────────────────────────────────

def compute_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ['open', 'high', 'low', 'close'])
    hc = (o + h + l + c) / 4.0
    ho = lfilter(np.array([0.0, 0.5]), np.array([1.0, -0.5]), hc,
                 zi=np.array([(o[0] + c[0]) / 2]))[0]
    df['ha_open'] = ho
    df['ha_close'] = hc
    df['ha_high'] = np.maximum.reduce([h, ho, hc])
    df['ha_low'] = np.minimum.reduce([l, ho, hc])
    return df


def compute_indicators(df: pd.DataFrame, cfg: CryptoConfig) -> pd.DataFrame:
    df = compute_heikin_ashi(df)
    df['bb_middle'] = df['ha_close'].rolling(cfg.bb_period).mean()
    dev = df['ha_close'].rolling(cfg.bb_period).std(ddof=0)
    df['bb_upper'] = df['bb_middle'] + cfg.bb_std * dev
    df['bb_lower'] = df['bb_middle'] - cfg.bb_std * dev
    days = pd.Series(df['timestamp'].dt.date, index=df.index)
    tp = df[['high', 'low', 'close']].mean(axis=1)
    cv = df['volume'].groupby(days).cumsum()
    df['vwap'] = (tp * df['volume']).groupby(days).cumsum() / cv.replace(0, np.nan)
    return df


# ─── Signal Generation ────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, cfg: CryptoConfig, tf_minutes: int) -> pd.DataFrame:
    df = df.copy()
    td = pd.Timedelta(minutes=tf_minutes)
    same_next = df['timestamp'].diff().eq(td)
    same_next &= pd.Series(df['timestamp'].dt.date, index=df.index).eq(
        pd.Series(df['timestamp'].dt.date, index=df.index).shift())
    bullish = df['ha_close'] > df['ha_open']
    tolerance = np.maximum(1e-8, np.abs(df['ha_open']) * 1e-10)
    wickless = (df['ha_low'] - df['ha_open']).abs() <= tolerance
    signal = (bullish & wickless
              & (df['ha_close'] > df['bb_upper'])
              & (df['ha_close'].shift() <= df['bb_upper'].shift()))
    if cfg.volume_filter:
        pass
    if cfg.image_filters:
        signal &= df['ha_close'] > df['vwap']
    confirmation = (signal.shift(fill_value=False) & same_next & bullish & wickless
                    & (df['ha_close'] > df['ha_high'].shift())
                    & (df['close'] > df['vwap']))
    if cfg.image_filters:
        confirmation &= (df['ha_close'] > df['vwap']) & (df['ha_close'] > df['bb_upper'])
    df['signal'] = signal
    df['confirmation'] = confirmation
    source = df['ha_low'] if cfg.stop_source == 'ha' else df['low']
    df['signal_stop'] = source.shift(1)
    return df


# ─── Backtest Engine ──────────────────────────────────────────────────────

def tick_round(value, tick, up=False):
    units = value / tick
    return round((math.ceil(units - 1e-9) if up else math.floor(units + 1e-9)) * tick, 10)


def run_backtest(df: pd.DataFrame, cfg: CryptoConfig, tf_minutes: int):
    cfg.validate()
    td = pd.Timedelta(minutes=tf_minutes)
    n = len(df)
    ts = df['timestamp'].to_numpy()
    day = df['timestamp'].dt.date.to_numpy()
    dti = df['timestamp'].dt
    sq_off_mask = ((dti.hour == 23) & (dti.minute >= (60 - tf_minutes))).to_numpy()
    o = df['open'].to_numpy(dtype=float)
    h = df['high'].to_numpy(dtype=float)
    l = df['low'].to_numpy(dtype=float)
    c = df['close'].to_numpy(dtype=float)
    conf = df['confirmation'].to_numpy()
    signal_stop = df['signal_stop'].to_numpy()

    candidates = {}
    conf_idx = np.flatnonzero(conf)
    for i in conf_idx:
        if i + 1 >= n:
            continue
        if day[i] != day[i + 1]:
            continue
        if (ts[i + 1] - ts[i]) != td:
            continue
        candidates.setdefault(i + 1, []).append(i)

    cash = cfg.allocation
    peak = cfg.allocation
    max_dd = 0.0
    trades = []
    position = None
    daily_entries = {}
    slip = cfg.slippage_bps / 10000
    fee = cfg.fee_bps / 10000

    def close(pos, idx, price, reason):
        nonlocal cash, position
        gross = pos['quantity'] * (price - pos['entry'])
        costs = pos['quantity'] * (price + pos['entry']) * fee
        cash += gross - costs
        trades.append({**pos, 'exit_time': ts[idx], 'exit': price, 'reason': reason,
                       'gross_pnl': gross, 'costs': costs, 'net_pnl': gross - costs,
                       'equity_after': cash})
        position = None

    for idx in range(n):
        stamp = ts[idx]
        o_i, h_i, l_i = o[idx], h[idx], l[idx]

        if position is not None:
            if sq_off_mask[idx]:
                price = max(cfg.tick_size, tick_round(o_i * (1 - slip), cfg.tick_size))
                close(position, idx, price, 'square_off')
            else:
                stop, target = position['stop'], position['target']
                result = None
                if o_i <= stop:
                    result = (max(cfg.tick_size, tick_round(o_i * (1 - slip), cfg.tick_size)), 'gap_stop')
                elif o_i >= target:
                    result = (target, 'target')
                elif l_i <= stop:
                    reason = 'both_hit_stop_first' if h_i >= target else 'stop'
                    result = (max(cfg.tick_size, tick_round(stop * (1 - slip), cfg.tick_size)), reason)
                elif h_i >= target:
                    result = (target, 'target')
                if result:
                    close(position, idx, *result)

        if position is None:
            for i in candidates.get(idx, []):
                count = daily_entries.get(day[idx], 0)
                if count >= cfg.max_trades or cash <= 0:
                    break
                entry = tick_round(o_i * (1 + slip), cfg.tick_size, up=True)
                stop = tick_round(float(signal_stop[i]), cfg.tick_size)
                if not (entry > stop > 0) or o_i <= stop:
                    continue
                target = tick_round(entry + cfg.reward_r * (entry - stop), cfg.tick_size, up=True)
                exp_stop = max(cfg.tick_size, tick_round(stop * (1 - slip), cfg.tick_size))
                loss = entry - exp_stop + (entry + exp_stop) * fee
                qty_raw = min(cash * cfg.risk_fraction / loss, cash / (entry * (1 + fee)))
                qty = math.floor(qty_raw / cfg.min_qty) * cfg.min_qty
                if qty <= 0:
                    continue
                position = {'signal_time': ts[i], 'entry_time': stamp,
                            'entry': entry, 'stop': stop, 'target': target, 'quantity': qty}
                daily_entries[day[idx]] = count + 1
                result = None
                if o_i <= stop:
                    result = (max(cfg.tick_size, tick_round(o_i * (1 - slip), cfg.tick_size)), 'gap_stop')
                elif o_i >= target:
                    result = (target, 'target')
                elif l_i <= stop:
                    result = (max(cfg.tick_size, tick_round(stop * (1 - slip), cfg.tick_size)), 'stop')
                elif h_i >= target:
                    result = (target, 'target')
                if result:
                    close(position, idx, *result)
                break

        equity = cash
        if position:
            equity += position['quantity'] * (c[idx] - position['entry'])
            equity -= position['quantity'] * (c[idx] + position['entry']) * fee
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    if position:
        price = max(cfg.tick_size, tick_round(c[-1] * (1 - slip), cfg.tick_size))
        close(position, n - 1, price, 'end_of_data')

    return pd.DataFrame(trades), max_dd


# ─── Reporting ─────────────────────────────────────────────────────────────

def compute_metrics(trades: pd.DataFrame, capital: float, max_dd: float, cfg: CryptoConfig) -> dict:
    if trades.empty:
        return {'trades': 0, 'status': 'no_trades', 'gross_pnl': 0.0, 'costs': 0.0,
                'net_pnl': 0.0, 'return_pct': 0.0, 'capital': capital,
                'max_drawdown_pct': float(max_dd * 100), 'win_rate_pct': None,
                'avg_win': None, 'avg_loss': None, 'profit_factor': None,
                'expectancy': None, 'avg_holding_minutes': None, 'config': asdict(cfg)}
    net = trades['net_pnl'].sum()
    wins = trades[trades['net_pnl'] > 0]
    losses = trades[trades['net_pnl'] <= 0]
    return {
        'trades': len(trades),
        'gross_pnl': float(trades['gross_pnl'].sum()),
        'costs': float(trades['costs'].sum()),
        'net_pnl': float(net),
        'return_pct': float(net / capital * 100),
        'capital': capital,
        'max_drawdown_pct': float(max_dd * 100),
        'win_rate_pct': float(len(wins) / len(trades) * 100),
        'avg_win': float(wins['net_pnl'].mean()) if len(wins) else None,
        'avg_loss': float(losses['net_pnl'].mean()) if len(losses) else None,
        'profit_factor': float(wins['net_pnl'].sum() / -losses['net_pnl'].sum())
            if len(losses) and losses['net_pnl'].sum() != 0 else None,
        'expectancy': float(trades['net_pnl'].mean()),
        'avg_holding_minutes': float(
            (pd.to_datetime(trades['exit_time']) - pd.to_datetime(trades['entry_time']))
            .dt.total_seconds().mean() / 60),
        'config': asdict(cfg),
    }


STYLE = 'body{background:#101620;color:#dde5ee;font:15px system-ui;margin:24px}a{color:#60caff}table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #334155;padding:7px;text-align:right}th{background:#1e293b;position:sticky;top:0}'


def write_html(path, body):
    Path(path).write_text(
        f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{STYLE}</style></head><body>{body}</body></html>',
        encoding='utf-8')


def generate_reports(symbol, timeframe, trades, metrics, out_dir, candles):
    out_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out_dir / 'trades.csv', index=False)
    (out_dir / 'summary.json').write_text(json.dumps(metrics, indent=2, allow_nan=False, default=str))

    days = candles['timestamp'].dt.date
    day_keys = sorted(days.unique())
    equity_curve = []
    eq = metrics['capital']
    trade_by_exit = {}
    if len(trades):
        for _, t in trades.iterrows():
            trade_by_exit[pd.Timestamp(t['exit_time']).date()] = trade_by_exit.get(
                pd.Timestamp(t['exit_time']).date(), 0) + t['net_pnl']
    peak = eq
    for d in day_keys:
        eq += trade_by_exit.get(d, 0)
        peak = max(peak, eq)
        equity_curve.append({'date': str(d), 'equity': eq, 'drawdown_pct': (peak - eq) / peak * 100})
    eq_df = pd.DataFrame(equity_curve)
    eq_df.to_csv(out_dir / 'equity.csv', index=False)

    m_df = pd.DataFrame([{k: v for k, v in metrics.items() if k != 'config'}])
    body = f'<h1>{symbol} — {timeframe}</h1>'
    body += '<p>HA/BB/VWAP crypto backtest. Sessions = UTC days. Volume filter disabled. 2R target.</p>'
    body += f'<p><a href="trades.csv">Trade ledger</a> | <a href="equity.csv">Equity curve</a> | <a href="summary.json">Full metrics</a></p>'
    body += '<h2>Summary</h2>' + m_df.T.to_html(header=False, escape=True)
    if len(trades):
        body += '<h2>Trades (last 50)</h2><div style="overflow:auto">' + trades.tail(50).to_html(index=False, escape=True) + '</div>'
    body += '<h2>Monthly P&L</h2>'
    if len(trades):
        tcopy = trades.copy()
        tcopy['month'] = pd.to_datetime(tcopy['exit_time']).dt.to_period('M').astype(str)
        monthly = tcopy.groupby('month').agg(trades=('net_pnl', 'size'), net_pnl=('net_pnl', 'sum'), win_rate=('net_pnl', lambda x: (x > 0).mean() * 100)).reset_index()
        body += monthly.to_html(index=False, escape=True)
    write_html(out_dir / 'report.html', body)


def index_report(out, summaries):
    body = '<h1>Crypto HA / BB / VWAP Backtest</h1>'
    body += '<p>USD 10,000 fixed notional per trade. Sessions = UTC calendar days. Volume filter disabled. 2R target.</p>'
    if summaries:
        df = pd.DataFrame(summaries)
        cols = [c for c in ['symbol', 'timeframe', 'trades', 'net_pnl', 'return_pct',
                            'win_rate_pct', 'max_drawdown_pct', 'profit_factor'] if c in df]
        shown = df[cols].copy()
        links = []
        for _, r in df.iterrows():
            links.append(f'<a href="{r["symbol"]}/{r["timeframe"]}/report.html">Open</a>')
        shown['report'] = links
        body += '<div style="overflow:auto">' + shown.to_html(index=False, escape=False, table_id='results') + '</div>'
    body += '<h2>Coverage</h2><ul>'
    for sym_dir in sorted(out.iterdir()):
        if sym_dir.is_dir():
            for tf_dir in sorted(sym_dir.iterdir()):
                if tf_dir.is_dir() and (tf_dir / 'summary.json').exists():
                    body += f'<li><a href="{sym_dir.name}/{tf_dir.name}/report.html">{sym_dir.name} {tf_dir.name}</a></li>'
    body += '</ul>'
    write_html(out / 'index.html', body)


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', nargs='+', default=['btcfut', 'ethfut', 'xautusdfut'])
    parser.add_argument('--timeframes', nargs='+', default=['1m', '5m'])
    parser.add_argument('--out', type=Path, default=OUT_DIR)
    parser.add_argument('--allocation', type=float, default=10000.0)
    parser.add_argument('--reward-r', type=float, default=2.0)
    parser.add_argument('--tick-size', type=float, default=None, help='Auto-detected if not set')
    parser.add_argument('--min-qty', type=float, default=0.0001)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    summaries = []
    for sym_name in args.symbols:
        sym_dir = DATA_DIR / sym_name
        if not sym_dir.exists():
            print(f"SKIP {sym_name}: not found at {sym_dir}")
            continue
        print(f"=== {sym_name} ===")
        t0 = time.perf_counter()
        files = candle_files(sym_dir)
        if not files:
            print(f"  SKIP: no data files found")
            continue
        probe = read_tick_file(files[0])
        auto_tick = detect_tick_size(probe)
        tick = args.tick_size if args.tick_size is not None else auto_tick
        print(f"  {len(files)} files, tick size: {tick} (probed {os.path.basename(files[0])})")

        for tf in args.timeframes:
            tf_min = int(tf.replace('m', ''))
            print(f"\n--- {sym_name} {tf} ---")
            cache = args.out / sym_name / f'{tf}_candles.pkl'
            if cache.exists():
                candles = pd.read_pickle(cache)
                print(f"  Cached: {len(candles):,} candles")
            else:
                t1 = time.perf_counter()
                candles, _ = load_candles(sym_dir, tf_min)
                cache.parent.mkdir(parents=True, exist_ok=True)
                candles.to_pickle(cache)
                print(f"  Built {len(candles):,} candles in {time.perf_counter()-t1:.1f}s")

            cfg = CryptoConfig(allocation=args.allocation, tick_size=tick, reward_r=args.reward_r,
                           min_qty=args.min_qty)
            cfg.validate()

            df = compute_indicators(candles, cfg)
            df = generate_signals(df, cfg, tf_min)

            sig_count = int(df['signal'].sum())
            conf_count = int(df['confirmation'].sum())
            print(f"  Signals: {sig_count}, Confirmations: {conf_count}")

            t2 = time.perf_counter()
            trades, max_dd = run_backtest(df, cfg, tf_min)
            print(f"  Backtest: {time.perf_counter()-t2:.1f}s")

            m = compute_metrics(trades, cfg.allocation, max_dd, cfg)
            m['symbol'] = sym_name
            m['timeframe'] = tf
            m['candles'] = len(candles)
            m['data_start'] = str(candles['timestamp'].iloc[0])
            m['data_end'] = str(candles['timestamp'].iloc[-1])

            summaries.append(m)
            report_dir = args.out / sym_name / tf
            generate_reports(sym_name, tf, trades, m, report_dir, candles)

            print(f"  Trades: {m['trades']}, Net P&L: {m['net_pnl']:.2f}, "
                  f"Win rate: {m.get('win_rate_pct', 0):.1f}%, Max DD: {m.get('max_drawdown_pct', 0):.1f}%")

    if summaries:
        pd.DataFrame(summaries).to_csv(args.out / 'summary.csv', index=False)
        index_report(args.out, summaries)
        print(f"\nAll done: {args.out / 'index.html'}")
        print(f"\n=== SUMMARY ===")
        df = pd.DataFrame(summaries)
        cols = [c for c in ['symbol', 'timeframe', 'trades', 'net_pnl', 'return_pct',
                            'win_rate_pct', 'max_drawdown_pct'] if c in df]
        print(df[cols].to_string(index=False))
    else:
        print("No results generated.")


if __name__ == '__main__':
    main()
