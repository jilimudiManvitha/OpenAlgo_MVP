"""Run a frozen intraday scanner replay and plot every simulated trade."""
import argparse
from dataclasses import asdict
import hashlib
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

from intraday_core import ReplayConfig, continuous_today, execute, prepare
from reconstruct import read_candles

CSS = '''body{margin:0;background:#0c111b;color:#e4ebf6;font:15px system-ui}main{max-width:1450px;margin:auto;padding:28px}h1{font-size:32px}p{color:#aab8ce;line-height:1.6}a{color:#7cc8ff}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:10px;border-bottom:1px solid #2b394d;text-align:right}th{background:#172335}td:first-child,th:first-child{text-align:left}.scroll{overflow:auto}input{padding:12px;background:#172335;color:#e4ebf6;border:1px solid #56708e;border-radius:6px;width:320px;max-width:100%}.notice{border-left:3px solid #e8b85e;padding-left:16px}.cards{display:flex;gap:15px;flex-wrap:wrap}.card{background:#172335;padding:18px;border-radius:10px;min-width:230px}.card strong{display:block;font-size:26px;margin:10px 0}.up{color:#6bdfab}.down{color:#ff939c}small{color:#aab8ce}@media(max-width:600px){main{padding:15px}}'''


def write_html(path, title, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>', encoding='utf-8')


def stamp(t):
    return pd.Timestamp(t, unit='s', tz='UTC').tz_convert('Asia/Kolkata').strftime('%H:%M')


def sources(ranks):
    return ', '.join(f'{name} #{rank}' for name, rank in zip(['Volume', 'Gainer', 'Loser'], ranks) if rank)


def trade_plot(path, record, raw, bars, tf):
    end = record['exit_timestamp'] if record['exit_timestamp'] is not None else record['mark_timestamp']
    left = max(int(raw.timestamp.iloc[0]), record['signal_timestamp'] - max(30, 10 * tf) * 60)
    right = min(int(raw.timestamp.iloc[-1]), end + 10 * 60)
    normal = raw[(raw.timestamp >= left) & (raw.timestamp <= right)]
    ha = bars[(bars.timestamp >= left) & (bars.timestamp <= right)]
    fig = make_subplots(rows=2, cols=1, vertical_spacing=.15,
                        subplot_titles=['Real one-minute prices and simulated fills', f'{tf}m Heikin-Ashi signal candles, Bollinger bands and session VWAP'])
    x = [stamp(t) for t in normal.timestamp]
    fig.add_trace(go.Candlestick(x=x, open=normal.open, high=normal.high, low=normal.low, close=normal.close, name='Real 1m'), row=1, col=1)
    hx = [stamp(t) for t in ha.timestamp]
    fig.add_trace(go.Candlestick(x=hx, open=ha.ha_open, high=ha.ha_high, low=ha.ha_low, close=ha.ha_close, name=f'HA {tf}m'), row=2, col=1)
    for column, label, color in [('bb_upper', 'BB upper', '#70a6ff'), ('bb_middle', 'BB middle', '#73849c'), ('bb_lower', 'BB lower', '#70a6ff'), ('vwap', 'Real HLC3 VWAP', '#eabd6b')]:
        fig.add_trace(go.Scatter(x=hx, y=ha[column], name=label, mode='lines', line={'color': color, 'width': 1.3}), row=2, col=1)
    fig.add_trace(go.Scatter(x=[stamp(record['entry_timestamp'])], y=[record['entry']], mode='markers+text', text=['ENTRY'], textposition='top center', name='Entry', marker={'symbol': 'triangle-up' if record['side'] == 'LONG' else 'triangle-down', 'color': '#6bdfab', 'size': 14}), row=1, col=1)
    price = record['exit'] if record['exit'] is not None else record['mark_price']
    label = 'EXIT' if record['status'] == 'CLOSED' else 'OPEN · MARK'
    fig.add_trace(go.Scatter(x=[stamp(end)], y=[price], mode='markers+text', text=[label], textposition='bottom center', name=label, marker={'symbol': 'x', 'color': '#ff939c', 'size': 12}), row=1, col=1)
    for value, label, color in [(record['entry'], 'Entry', '#6bdfab'), (record['stop'], 'Stop loss', '#ff939c'), (record['target'], 'Target 2R', '#82c6ff')]:
        fig.add_trace(go.Scatter(x=[stamp(record['entry_timestamp']), stamp(end)], y=[value, value], mode='lines', name=f'{label} {value:.2f}', line={'color': color, 'dash': 'dash'}), row=1, col=1)
    fig.add_trace(go.Scatter(x=[stamp(record['signal_timestamp'])], y=[float(bars.loc[bars.timestamp == record['signal_timestamp'], 'ha_close'].iloc[0])], mode='markers', name='Completed signal', marker={'symbol': 'diamond', 'color': '#eabd6b', 'size': 12}), row=2, col=1)
    fig.update_layout(template='plotly_dark', height=1000, title=f"{record['symbol']} · {tf}m · {record['trade_id']} · {record['side']} · {record['status']}", legend={'orientation': 'h'}, margin={'l': 55, 'r': 35, 't': 120, 'b': 55})
    fig.update_xaxes(type='category', rangeslider_visible=False, nticks=12, tickangle=0, title_text='IST · candle-open time')
    fig.update_xaxes(title_text='', row=1, col=1)
    title = f"{record['symbol']} {tf}m trade {record['trade_id']}"
    labels = {'side': 'Side', 'status': 'Status', 'entry': 'Entry ₹', 'stop': 'Stop ₹', 'target': 'Target ₹',
              'quantity': 'Quantity', 'entry_notional': 'Notional ₹', 'entry_cost': 'Entry cost ₹',
              'exit': 'Exit ₹', 'exit_cost': 'Exit cost ₹', 'gross_pnl': 'Gross / marked ₹',
              'net_pnl': 'Net / marked ₹', 'reason': 'Exit / mark reason', 'ambiguous': 'Ambiguous fill'}
    facts = {label: round(record[k], 2) if isinstance(record[k], float) else record[k] for k, label in labels.items()}
    body = f'<a href="../index.html">Back to all trades</a><h1>{html.escape(title)}</h1><p>Entry {stamp(record["entry_timestamp"])} IST · Signal available {stamp(record["signal_available_at"])} IST · {html.escape(sources(record["entry_ranks"]))}</p>'
    body += '<p class="notice">Candle-based simulated fills. Entry/exit labels identify one-minute bars, not exact tick times. Same-bar order is uncertain where ambiguity is flagged; stop-first convention is used. An OPEN marker is a valuation, not a simulated exit.</p>'
    body += '<div class="scroll">' + pd.DataFrame([facts]).to_html(index=False, escape=True) + '</div>'
    body += fig.to_html(full_html=False, include_plotlyjs='../plotly.min.js')
    write_html(path, title, body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--report-name', default='backtest')
    args = parser.parse_args()
    run = args.run
    meta = json.loads((run / 'inputs/metadata.json').read_text())
    reconstruction = json.loads((run / 'reconstruction.json').read_text())
    with np.load(run / 'rankings.npz') as a:
        symbols, ranks, starts, candidate = a['symbols'].copy(), a['ranks'].copy(), a['starts'].copy(), a['candidate'].copy()
    items = {x['symbol']: x for x in meta['universe']}
    start, cutoff = int(starts[0]), reconstruction['cutoff']
    if Path(args.report_name).name != args.report_name:
        raise ValueError('Report name must be a single directory name')
    output = run / args.report_name
    if (output / 'manifest.json').exists():
        raise RuntimeError('Preserve existing report: choose a new run/output location before rerunning')
    output.mkdir(exist_ok=True)
    (output / 'plotly.min.js').write_text(get_plotlyjs(), encoding='utf-8')
    sums = {tf: {k: np.zeros(len(starts)) for k in ['pnl', 'occupied', 'fees', 'positions']} for tf in [1, 5]}
    all_trades, summaries, rejected = [], [], []
    eligible_count = int(np.any(ranks > 0, axis=(1, 2)).sum())
    for i, symbol in enumerate(symbols):
        item = items[symbol]
        ever = bool(np.any(ranks[i]))
        if not ever and not item['current_selected']:
            continue
        status = 'not_selected_in_reconstructed_lists' if not ever else 'never_passed_scanner_and_20_session_volume_gate'
        reason = None
        if candidate[i]:
            try:
                d = read_candles(run, symbol)
                raw = continuous_today(d, start, cutoff)
                warm = d[d.timestamp < start]
                dates = np.unique((warm.timestamp.to_numpy() + 19800) // 86400)
                if len(dates) < 20 or len(warm) < 1000:
                    raise ValueError('insufficient_warmup_history')
                if len(raw) != len(starts):
                    raise ValueError('incomplete_today_price_history')
                daily = sorted((x for x in item['daily_baselines'] if x['date'] < meta['session_date']), key=lambda x: x['date'])
                if len(daily) < 20:
                    raise ValueError('insufficient_daily_volume_baseline')
                tick = float(item.get('tick') or 0)
                if not np.isfinite(tick) or tick <= 0:
                    raise ValueError('missing_verified_tick_size')
                lot = max(1, int(item.get('lot') or 1))
                cfg = ReplayConfig(tick=tick, lot=lot)
                membership = {int(t + 60): ranks[i, j] for j, t in enumerate(starts)}
                for tf in [1, 5]:
                    bars = prepare(d, tf, start, daily)
                    records, exclusions, curve, occupied, fees = execute(raw, bars, tf, membership, cfg)
                    for number, r in enumerate(records, len(all_trades) + 1):
                        r.update(symbol=str(symbol), timeframe=tf, trade_id=f'{symbol}-{tf}m-{number:04}', current_selected=item['current_selected'])
                        r['plot'] = 'trades/' + r['trade_id'] + '.html'
                        trade_plot(output / r['plot'], r, raw, bars, tf)
                    all_trades.extend(records)
                    rejected.extend(dict(r, symbol=str(symbol), timeframe=tf) for r in exclusions)
                    assert np.isclose(curve[-1], sum(r['net_pnl'] for r in records), atol=1e-6)
                    assert np.isclose(fees[-1], sum(r['entry_cost'] + r['exit_cost'] for r in records), atol=1e-6)
                    for k, value in [('pnl', curve), ('occupied', occupied), ('fees', fees)]:
                        sums[tf][k] += value
                    for r in records:
                        left = (r['entry_timestamp'] - start) // 60
                        right = (r['exit_timestamp'] - start) // 60 + 1 if r['exit_timestamp'] is not None else len(starts)
                        sums[tf]['positions'][left:right] += 1
                    summaries.append({'symbol': symbol, 'timeframe': tf, 'current_selected': item['current_selected'],
                                      'status': 'evaluated' if records else 'no_qualifying_entry', 'trades': len(records),
                                      'closed': sum(r['status'] == 'CLOSED' for r in records), 'open': sum(r['status'] == 'OPEN' for r in records),
                                      'net_pnl': float(curve[-1]), 'peak_notional': float(occupied.max()), 'tick_size': tick,
                                      'warmup_rows': len(warm), 'warmup_sessions': len(dates)})
                print(f'{symbol}: completed both timeframes; trade plots so far={len(all_trades)}', flush=True)
                continue
            except (ValueError, TypeError, OSError) as exc:
                status, reason = 'excluded', str(exc)
        for tf in [1, 5]:
            summaries.append({'symbol': symbol, 'timeframe': tf, 'current_selected': item['current_selected'],
                              'status': status, 'reason': reason, 'trades': 0, 'closed': 0, 'open': 0,
                              'net_pnl': None if status == 'excluded' else 0.})
    trades = pd.DataFrame(all_trades)
    assert len({r['trade_id'] for r in all_trades}) == len(all_trades)
    assert len(list((output / 'trades').glob('*.html'))) == len(all_trades)
    summaries = pd.DataFrame(summaries)
    trades.to_csv(output / 'trades.csv', index=False)
    summaries.to_csv(output / 'symbols.csv', index=False)
    pd.DataFrame(rejected).to_csv(output / 'rejected_signals.csv', index=False)
    benchmark = json.loads((run / 'inputs/benchmark.json').read_text())
    benchmark = [r for r in benchmark if start <= r[0] and r[0] + 60 <= cutoff]
    benchmark_return = (benchmark[-1][4] / benchmark[0][1] - 1) * 100 if benchmark and benchmark[0][0] == start and benchmark[-1][0] + 60 == cutoff else None
    totals, cards = {}, []
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=['Cumulative net P&L including open-position marks', 'Occupied notional; each timeframe is a separate simulation'])
    for tf in [1, 5]:
        values = sums[tf]
        recs = [r for r in all_trades if r['timeframe'] == tf]
        closed = [r for r in recs if r['status'] == 'CLOSED']
        open_trades = [r for r in recs if r['status'] == 'OPEN']
        capital = eligible_count * 100000
        peak = np.maximum.accumulate(np.r_[0., values['pnl']])[1:]
        assert np.isclose(values['pnl'][-1], sum(r['net_pnl'] for r in recs), atol=1e-6)
        total = {'trades': len(recs), 'closed': len(closed), 'open': len(open_trades),
                 'closed_net_pnl': sum(r['net_pnl'] for r in closed), 'open_marked_pnl_after_entry_cost': sum(r['net_pnl'] for r in open_trades),
                 'net_pnl': float(values['pnl'][-1]), 'costs_paid': float(values['fees'][-1]),
                 'win_rate_closed_percent': 100 * sum(r['net_pnl'] > 0 for r in closed) / len(closed) if closed else None,
                 'max_close_marked_drawdown_inr': float((peak - values['pnl']).max()),
                 'peak_notional_bound': float(values['occupied'].max()),
                 'peak_concurrent_positions_bound': int(values['positions'].max()),
                 'funding_bound': float(np.maximum(0, values['occupied'] - values['pnl']).max()),
                 'reference_capital': capital, 'return_on_reference_percent': float(values['pnl'][-1] / capital * 100),
                 'nifty_price_return_percent': benchmark_return, 'sharpe': None,
                 'ambiguous_trades': sum(r['ambiguous'] for r in recs)}
        totals[f'{tf}m'] = total
        pd.DataFrame({'timestamp': starts, **values}).to_csv(output / f'portfolio_{tf}m.csv', index=False)
        fig.add_trace(go.Scatter(x=[stamp(t + 60) for t in starts], y=values['pnl'], name=f'{tf}m net P&L'), row=1, col=1)
        fig.add_trace(go.Scatter(x=[stamp(t + 60) for t in starts], y=values['occupied'], name=f'{tf}m notional'), row=2, col=1)
        cards.append(f'<div class="card">{tf}m strategy<strong>₹{total["net_pnl"]:,.2f}</strong><small>{len(closed)} closed · {len(open_trades)} open · {total["ambiguous_trades"]} ambiguous</small></div>')
    fig.update_layout(template='plotly_dark', height=650, legend={'orientation': 'h'})
    (output / 'summary.json').write_text(json.dumps(totals, indent=2, allow_nan=False), encoding='utf-8')
    hashes = json.loads((run / 'input_hashes.json').read_text())
    manifest = {'session_date': meta['session_date'], 'cutoff': cutoff, 'scanner_id': meta['scanner_id'],
                'input_hashes': hashes, 'reconstruction': reconstruction, 'defaults': asdict(ReplayConfig()),
                'implementation_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), Path(__file__).with_name('intraday_core.py'), Path(__file__).with_name('reconstruct.py'), Path(__file__).resolve().parents[1] / 'six-task-research/backtesting/all_stock_ha/engine.py']},
                'assumptions': ['Dynamic top-50 union reconstructed at each minute close; entry and signal membership required.',
                  'All intraday members considered, including those absent from the final current scanner list.',
                  'Current master and previous-close reference; missing minute data causes exclusion. This is not full exchange coverage.',
                  'Original today-download candles take precedence over later warmup duplicates; warmup adds prior days only. A BSOFT revision was detected and excluded from execution.',
                  'Warmup HA seeded at first observed candle of a 50-calendar-day window; seed convergence is not original full-history identity.',
                  'HA/BB signal and 20-session RVOL >=2 preserved; daily full-day Fyers volumes used for the baseline.',
                  '5 bps per-side costs and 5 bps adverse slippage are illustrative, not itemized broker tariffs.',
                  'Tick and lot constraints read from current Fyers master; historical adjustment and corporate-action handling unverified.',
                  'Candle ordering ambiguous: stop-first; open trades marked at cutoff with entry cost, no invented closing fill.',
                  'Each timeframe is a separate all-opportunity simulation, 100000 per entry; cash is not constrained.',
                  'Reference capital is 100000 per ever-selected instrument, fixed within the day. Sharpe is unavailable for a single partial day.',
                  'NIFTY benchmark is price-only with no costs; strategy return uses the disclosed reference capital.']}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    body = f'<p><a href="../scanner/index.html">Current top-50 scanner lists</a> · <a href="../scanner_memberships.csv">Historical list membership</a></p><h1>Scanner strategy · {meta["session_date"]}</h1><p>Completed candles from 09:15 through {stamp(cutoff)} IST. Both 1m and 5m HA/BB/VWAP strategies; ₹100,000 notional per entry.</p>'
    body += '<p class="notice">Partial-day research simulation. Rankings are reconstructed using data available at each minute close. Coverage is incomplete and fills/costs are modeled. Stocks that entered a list earlier may no longer appear in the current top-50 snapshot. No live orders were submitted.</p>'
    body += '<div class="cards">' + ''.join(cards) + '</div>'
    body += f'<p>Universe: {len(symbols):,} configured; {reconstruction["full_prefix_symbols"]:,} continuous histories; {eligible_count} selected at some point; {int(candidate.sum())} could pass the mandatory volume filter. <a href="../reconstructed_coverage.csv">Coverage and exclusions</a>.</p>'
    body += fig.to_html(full_html=False, include_plotlyjs='plotly.min.js')
    body += '<h2>Results and benchmark</h2><p>Closed P&L and open-position marks are separate. Funding is a conservative one-minute bound; each simulation has its own capital. A single partial day has no meaningful daily Sharpe.</p><div class="scroll">' + pd.DataFrame(totals).T.to_html(escape=True) + '</div>'
    body += '<h2>Every simulated trade</h2><p><a href="trades.csv">Trade ledger CSV</a> · <a href="symbols.csv">All stock outcomes</a> · <a href="rejected_signals.csv">Rejected signals</a> · <a href="manifest.json">Data hashes and assumptions</a></p><input id="search" type="search" aria-label="Search trade symbol" placeholder="Search symbol…"><div class="scroll">'
    if all_trades:
        visible = []
        for r in all_trades:
            visible.append({'Stock': html.escape(r['symbol']), 'Timeframe': f'{r["timeframe"]}m', 'Side': r['side'], 'Status': r['status'],
                            'Entry IST': stamp(r['entry_timestamp']), 'Exit IST': stamp(r['exit_timestamp']) if r['exit_timestamp'] is not None else 'Open',
                            'Quantity': r['quantity'], 'Net / marked ₹': round(r['net_pnl'], 2),
                            'Entry lists': html.escape(sources(r['entry_ranks'])), 'In current list': r['current_selected'],
                            'Chart': f'<a href="{r["plot"]}">Plot trade</a>'})
        body += pd.DataFrame(visible).to_html(index=False, escape=False, table_id='trades')
    else:
        body += '<p>No valid strategy entries in this frozen data window. No synthetic trades or plots were created.</p>'
    body += '</div><h2>Stock coverage and no-trade reasons</h2><div class="scroll">' + summaries.to_html(index=False, escape=True) + '</div>'
    body += '<script>document.querySelector("#search").addEventListener("input",function(){const q=this.value.toLowerCase();document.querySelectorAll("#trades tbody tr").forEach(r=>r.hidden=!r.cells[0].textContent.toLowerCase().includes(q));});</script>'
    write_html(output / 'index.html', 'Intraday scanner backtest and trade plots', body)
    print(json.dumps(totals, indent=2))
    print(f'Report: {output / "index.html"}')


if __name__ == '__main__':
    main()
