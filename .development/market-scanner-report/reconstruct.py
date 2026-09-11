"""Reconstruct per-minute top-50 lists from the frozen full-universe inputs."""
import argparse
from datetime import datetime
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from intraday_core import continuous_today, rank_snapshot, valid_frame


def read_candles(run, symbol):
    warmup = run / 'inputs/warmup' / (symbol + '.json.gz')
    today = run / 'inputs/today' / (symbol + '.json.gz')
    if warmup.exists():
        with gzip.open(warmup, 'rt', encoding='utf-8') as handle:
            rows = json.load(handle)
        if today.exists():
            # The warmup request can arrive hours later and contain broker revisions.
            # Rank and execute the same original today bars; warmup supplies only prior days.
            meta = json.loads((run / 'inputs/metadata.json').read_text())
            midnight = int(datetime.fromisoformat(meta['session_date'] + 'T00:00:00+05:30').timestamp())
            with gzip.open(today, 'rt', encoding='utf-8') as handle:
                original_today = json.load(handle)
            rows = [r for r in rows if r[0] < midnight] + original_today
        return valid_frame(rows)
    if today.exists():
        with gzip.open(today, 'rt', encoding='utf-8') as handle:
            return valid_frame(json.load(handle))
    raise ValueError('missing_history_file')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    meta = json.loads((args.run / 'inputs/metadata.json').read_text())
    start = int(datetime.fromisoformat(meta['session_date'] + 'T09:15:00+05:30').timestamp())
    cutoff = min(meta['cutoff'], start + 375 * 60)
    count = (cutoff - start) // 60
    universe = sorted(meta['universe'], key=lambda r: r['symbol'])
    symbols = [r['symbol'] for r in universe]
    closes, volumes = np.full((len(symbols), count), np.nan), np.zeros((len(symbols), count))
    previous, average, strategy_average = np.full(len(symbols), np.nan), np.full(len(symbols), np.nan), np.full(len(symbols), np.nan)
    coverage = []
    for i, item in enumerate(universe):
        try:
            d = read_candles(args.run, item['symbol'])
            today = d[(d.timestamp >= start) & (d.timestamp + 60 <= cutoff)]
            continuous = continuous_today(d, start, cutoff)
            n = len(continuous)
            closes[i, :n] = continuous.close
            volumes[i, :n] = continuous.volume.cumsum()
            if item.get('previous_close'):
                previous[i] = float(item['previous_close'])
            daily = sorted((x for x in item['daily_baselines'] if x['date'] < meta['session_date']), key=lambda r: r['date'])
            if len(daily) >= 5:
                average[i] = math.fsum(r['volume'] for r in daily[-5:]) / 5
            if len(daily) >= 20:
                strategy_average[i] = math.fsum(r['volume'] for r in daily[-20:]) / 20
            reason = 'complete_to_cutoff' if n == count else 'missing_minutes_prefix_only'
            coverage.append({'symbol': item['symbol'], 'current_selected': item['current_selected'],
                             'received_today_rows': len(today), 'usable_prefix_rows': n, 'expected_rows': count,
                             'daily_baselines': len(daily), 'previous_close': previous[i], 'average_5': average[i],
                             'average_20': strategy_average[i], 'status': reason})
        except (ValueError, TypeError, OSError) as exc:
            coverage.append({'symbol': item['symbol'], 'current_selected': item['current_selected'],
                             'usable_prefix_rows': 0, 'expected_rows': count, 'status': str(exc)})
    ranks = np.zeros((len(symbols), count, 3), dtype=np.uint16)
    snapshots, memberships = [], []
    for j in range(count):
        ranked, changes, rv, valid = rank_snapshot(symbols, closes[:, j], volumes[:, j], previous, average)
        ranks[:, j] = ranked
        available = start + (j + 1) * 60
        snapshots.append({'available_at': available, 'cutoff_bar_open': available - 60,
                          'valid_instruments': valid, 'configured_universe': len(symbols),
                          'selected_unique': int(np.any(ranked > 0, axis=1).sum())})
        for i in np.flatnonzero(np.any(ranked > 0, axis=1)):
            memberships.append({'available_at': available, 'symbol': symbols[i],
                                'volume_rank': int(ranked[i, 0]), 'gainer_rank': int(ranked[i, 1]),
                                'loser_rank': int(ranked[i, 2]), 'price_change_percent': changes[i],
                                'scanner_rvol_5': rv[i], 'cumulative_volume': volumes[i, j]})
    # A stock below the mandatory 20-session volume threshold at every snapshot
    # cannot enter, regardless of its indicator values. Avoid needless warmup calls.
    enough_volume = np.isfinite(strategy_average) & (strategy_average > 0)
    candidate = np.any((np.any(ranks > 0, axis=2)) & (volumes >= 2 * strategy_average[:, None]), axis=1) & enough_volume
    needed = [s for i, s in enumerate(symbols) if candidate[i] and not (args.run / 'inputs/warmup' / (s + '.json.gz')).exists()]
    (args.run / 'warmup_needed.json').write_text(json.dumps(needed), encoding='utf-8')
    np.savez_compressed(args.run / 'rankings.npz', ranks=ranks, symbols=np.array(symbols),
                        starts=start + np.arange(count) * 60, candidate=candidate)
    pd.DataFrame(coverage).to_csv(args.run / 'reconstructed_coverage.csv', index=False)
    pd.DataFrame(snapshots).to_csv(args.run / 'scanner_snapshots.csv', index=False)
    pd.DataFrame(memberships).to_csv(args.run / 'scanner_memberships.csv', index=False)
    report = {'snapshots': count, 'cutoff': cutoff, 'universe': len(symbols),
              'ever_selected': int(np.any(ranks > 0, axis=(1, 2)).sum()),
              'can_pass_strategy_volume': int(candidate.sum()), 'additional_warmup_needed': len(needed),
              'full_prefix_symbols': sum(x['usable_prefix_rows'] == count for x in coverage),
              'first_snapshot_valid': snapshots[0]['valid_instruments'], 'last_snapshot_valid': snapshots[-1]['valid_instruments'],
              'selection_note': 'Rankings are reconstructed within available continuous-price coverage. Stocks are excluded after the first missing minute; zero-volume bars are not invented. Current Fyers EQ universe includes possible ETFs.',
              'latency_note': 'Completed bars become available at close with zero modeled processing latency; one-minute bar execution is approximate.'}
    (args.run / 'reconstruction.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
