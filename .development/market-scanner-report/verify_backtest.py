"""Validate generated trade reports against snapshots, constraints and ledgers."""
import argparse
import ast
import hashlib
import gzip
from html.parser import HTMLParser
import json
from pathlib import Path

import numpy as np
import pandas as pd

from reconstruct import read_candles


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'a' and 'href' in values:
            self.links.append(values['href'])
        if tag == 'script' and 'src' in values:
            self.links.append(values['src'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    out, run = args.report, args.report.parent
    manifest = json.loads((out / 'manifest.json').read_text())
    totals = json.loads((out / 'summary.json').read_text())
    trades = pd.read_csv(out / 'trades.csv')
    membership = pd.read_csv(run / 'scanner_memberships.csv').set_index(['symbol', 'available_at'])
    specs = {r['symbol']: r for r in json.loads((run / 'inputs/metadata.json').read_text())['universe']}
    assert trades.trade_id.is_unique and trades['plot'].is_unique
    assert len(list((out / 'trades').glob('*.html'))) == len(trades)
    for row in trades.itertuples(index=False):
        assert row.signal_timestamp + row.timeframe * 60 == row.signal_available_at
        assert row.signal_available_at <= row.entry_timestamp < row.signal_available_at + row.timeframe * 60
        for at, recorded in [(row.signal_available_at, row.signal_ranks), (row.entry_timestamp, row.entry_ranks)]:
            found = membership.loc[(row.symbol, at)]
            expected = found[['volume_rank', 'gainer_rank', 'loser_rank']].to_numpy(dtype=int).tolist()
            assert ast.literal_eval(recorded) == expected and any(expected)
        assert row.signal_rvol_20 >= 2
        assert row.quantity > 0 and row.quantity == int(row.quantity)
        lot = max(1, specs[row.symbol].get('lot') or 1)
        assert row.quantity % lot == 0
        assert row.entry * row.quantity <= 100000 + 1e-7
        assert row.entry_timestamp + 60 <= manifest['cutoff']
        if row.status == 'CLOSED':
            assert row.entry_timestamp <= row.exit_timestamp and row.exit_timestamp + 60 <= manifest['cutoff']
        else:
            assert pd.isna(row.exit_timestamp) and pd.isna(row.exit)
            assert row.mark_timestamp + 60 == manifest['cutoff']
        assert np.isclose(row.net_pnl, row.gross_pnl - row.entry_cost - row.exit_cost, atol=1e-6)
    for tf in [1, 5]:
        t = trades[trades.timeframe == tf]
        timeline = pd.read_csv(out / f'portfolio_{tf}m.csv')
        summary = totals[f'{tf}m']
        assert len(t) == summary['trades']
        assert int((t.status == 'CLOSED').sum()) == summary['closed']
        assert int((t.status == 'OPEN').sum()) == summary['open']
        assert np.isclose(t.net_pnl.sum(), timeline.pnl.iloc[-1], atol=1e-6)
        assert np.isclose(t.net_pnl.sum(), summary['net_pnl'], atol=1e-6)
        assert np.isclose((t.entry_cost + t.exit_cost).sum(), timeline.fees.iloc[-1], atol=1e-6)
    pages = [out / 'index.html'] + list((out / 'trades').glob('*.html'))
    for page in pages:
        parser = Links()
        parser.feed(page.read_text(encoding='utf-8'))
        for link in parser.links:
            assert (page.parent / link).resolve().exists(), (page, link)
    for relative, sha in manifest['input_hashes'].items():
        assert hashlib.sha256((run / relative).read_bytes()).hexdigest() == sha, relative
    overlaps, revisions = 0, []
    for path in (run / 'inputs/today').glob('*.json.gz'):
        warm = run / 'inputs/warmup' / path.name
        if not warm.exists():
            continue
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            original = json.load(f)
        with gzip.open(warm, 'rt', encoding='utf-8') as f:
            later = json.load(f)
        midnight = int(pd.Timestamp(manifest['session_date'], tz='Asia/Kolkata').timestamp())
        later = [r for r in later if r[0] >= midnight]
        if original != later:
            revisions.append(path.name.removesuffix('.json.gz'))
        effective = read_candles(run, path.name.removesuffix('.json.gz'))
        effective = effective[effective.timestamp >= midnight]
        np.testing.assert_array_equal(effective.to_numpy(), np.array(original))
        overlaps += 1
    result = {'trades_checked': len(trades), 'unique_trade_charts': len(pages) - 1,
              'overlapping_downloads_checked': overlaps, 'later_revisions_ignored': revisions,
              'checks': ['signal/entry scanner membership', 'causal signal time and next-bar expiry',
                         '20-session RVOL gate', 'quantity/lot/notional constraints', 'cutoff/open-mark integrity',
                         'cost/P&L reconciliation', 'all local HTML/Plotly links', 'all input content hashes'],
              'status': 'passed'}
    (out / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
