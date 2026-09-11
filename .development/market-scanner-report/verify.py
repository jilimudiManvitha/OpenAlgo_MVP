"""Independently check snapshot arithmetic, ordering, dates, and cached baselines."""
import argparse
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--cache', type=Path, default=Path('db/market_scanner.db'))
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(encoding='utf-8'))
    assert data['state'] == 'completed' and not data['stale']
    assert data['session_date'] == datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
    summary = {key: data[key] for key in ['scan_id', 'session_date', 'started_at', 'completed_at',
               'total', 'valid_quotes', 'valid_baselines', 'partial', 'matching_counts', 'rate_limit_retries']}
    summary['issues'] = dict(Counter(row['reason'] for row in data['issues']))
    summary['top_five'] = {}
    checked = 0
    connection = sqlite3.connect(args.cache.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        for key in ['volume_shockers', 'top_gainers', 'top_losers']:
            rows = data[key]
            assert len(rows) == min(data['options']['limit'], data['matching_counts'][key])
            assert len({row['symbol'] for row in rows}) == len(rows)
            sort_key = (lambda r: (-r['rvol'], -r['change_percent'], r['symbol'])) if key == 'volume_shockers' else (lambda r: (-r['change_percent'], r['symbol'])) if key == 'top_gainers' else (lambda r: (r['change_percent'], r['symbol']))
            assert rows == sorted(rows, key=sort_key)
            for row in rows:
                assert row['last_trade_at'][:10] == data['session_date']
                assert row['quote_fetched_at'][:10] == data['session_date']
                expected = (row['ltp'] / row['previous_close'] - 1) * 100
                assert math.isclose(row['change_percent'], expected, abs_tol=1e-9)
                if key == 'top_gainers':
                    assert row['change_percent'] > 0
                if key == 'top_losers':
                    assert row['change_percent'] < 0
                if key == 'volume_shockers':
                    assert row['rvol'] > data['options']['min_rvol']
                if row['rvol'] is not None:
                    record = connection.execute('SELECT candles FROM fyers_volume_baselines WHERE symbol=? AND session_date=?',
                              (f"NSE:{row['symbol']}-EQ", data['session_date'])).fetchone()
                    assert record is not None
                    candles = sorted(json.loads(record[0]), key=lambda r: r['date'])[-data['options']['lookback_days']:]
                    assert len(candles) == data['options']['lookback_days']
                    assert all(r['date'] < data['session_date'] for r in candles)
                    assert row['baseline_dates'] == [r['date'] for r in candles]
                    average = math.fsum(r['volume'] for r in candles) / len(candles)
                    assert math.isclose(row['average_volume'], average, abs_tol=1e-9)
                    assert math.isclose(row['rvol'], row['volume'] / average, abs_tol=1e-9)
                checked += 1
            summary['top_five'][key] = [{field: row[field] for field in ['symbol', 'ltp', 'change_percent', 'volume', 'rvol']} for row in rows[:5]]
    finally:
        connection.close()
    summary['ranked_rows_checked'] = checked
    summary['verification'] = 'Dates, ranking, price change, and cached five-session volume arithmetic passed for every exported row.'
    target = args.snapshot.with_name(args.snapshot.stem + '-verified.json')
    target.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
