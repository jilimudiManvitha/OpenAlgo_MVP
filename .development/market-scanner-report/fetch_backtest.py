"""Fetch immutable, data-only inputs for a scanner-selected intraday replay."""
import argparse
from datetime import date, datetime, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--warmup-list', type=Path)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from database.auth_db import Auth, db_session
    from database.symbol import SymToken, db_session as symbols_session
    from services.market_scanner_provider import FyersScannerProvider, get_fyers_token, load_universe, ScannerError
    try:
        users = db_session.query(Auth.name).filter(Auth.broker == 'fyers', Auth.is_revoked.is_(False)).all()
    finally:
        db_session.remove()
    if len(users) != 1:
        raise RuntimeError('A single active Fyers login is required')
    provider = FyersScannerProvider(get_fyers_token(users[0][0]))
    snapshot = json.loads((args.run / 'scanner.json').read_text())
    day = date.fromisoformat(snapshot['session_date'])
    cutoff = int(datetime.fromisoformat(snapshot['completed_at']).timestamp()) // 60 * 60
    selected = {r['symbol'] for key in ['volume_shockers', 'top_gainers', 'top_losers'] for r in snapshot[key]}
    meta_path = args.run / 'inputs/metadata.json'

    def call(function, *values):
        for attempt in range(3):
            try:
                return function(*values)
            except ScannerError as exc:
                if exc.status_code != 429 or attempt == 2:
                    raise
                print('Broker quota cooldown: 60 seconds', flush=True)
                time.sleep(60)

    if meta_path.exists():
        metadata = json.loads(meta_path.read_text())
    else:
        universe = load_universe()
        try:
            specs = {r.symbol: {'tick': r.tick_size, 'lot': r.lotsize} for r in symbols_session.query(SymToken).filter(SymToken.exchange == 'NSE', SymToken.instrumenttype == 'EQ').all()}
        finally:
            symbols_session.remove()
        connection = sqlite3.connect((ROOT / 'db/market_scanner.db').as_uri() + '?mode=ro', uri=True)
        try:
            daily = {s: json.loads(raw) for s, raw in connection.execute('SELECT symbol,candles FROM fyers_volume_baselines WHERE session_date=?', (day.isoformat(),))}
        finally:
            connection.close()
        for i in range(0, len(universe), 50):
            batch = universe[i:i + 50]
            quotes = call(provider.quotes, batch)
            for item in batch:
                item.update(specs.get(item['symbol'], {}))
                item['previous_close'] = quotes.get(item['broker_symbol'], {}).get('prev_close_price')
                item['daily_baselines'] = daily.get(item['broker_symbol'], [])
                item['current_selected'] = item['symbol'] in selected
        metadata = {'session_date': day.isoformat(), 'cutoff': cutoff, 'scanner_id': snapshot['scan_id'],
                    'universe': universe, 'notes': ['Current Fyers EQ master; may include ETFs.',
                    'Previous close from current-day Fyers quotes; daily volume baselines exclude today.',
                    'Historical bar snapshots assume zero processing latency at bar close.']}
        save(meta_path, metadata)
    wanted = set(json.loads(args.warmup_list.read_text())) if args.warmup_list else None
    universe = [x for x in metadata['universe'] if wanted is None or x['symbol'] in wanted]
    errors = []
    for i, item in enumerate(universe, 1):
        warmup = bool(wanted is not None or item['current_selected'])
        folder = args.run / 'inputs' / ('warmup' if warmup else 'today')
        path = folder / (item['symbol'] + '.json.gz')
        if path.exists():
            if i % 100 == 0:
                print(f'History {i}/{len(universe)}: reused cached input', flush=True)
            continue
        params = {'symbol': item['broker_symbol'], 'resolution': '1', 'date_format': '1',
                  'range_from': (day - timedelta(days=50) if warmup else day).isoformat(),
                  'range_to': day.isoformat(), 'cont_flag': '1'}
        try:
            result = call(provider._request, '/data/history?' + urlencode(params))
            rows = result.get('candles')
            if not isinstance(rows, list):
                raise ValueError('Missing candle list')
            rows = [r[:6] for r in rows if len(r) >= 6 and int(r[0]) + 60 <= cutoff]
            folder.mkdir(parents=True, exist_ok=True)
            with gzip.open(str(path) + '.tmp', 'wt', encoding='utf-8') as handle:
                json.dump(rows, handle, allow_nan=False)
            Path(str(path) + '.tmp').replace(path)
        except ScannerError as exc:
            if exc.status_code in (401, 403, 429):
                raise
            errors.append({'symbol': item['symbol'], 'reason': 'broker_history_unavailable'})
        except (ValueError, TypeError, OSError):
            errors.append({'symbol': item['symbol'], 'reason': 'invalid_history_response'})
        if i % 20 == 0 or i == len(universe):
            print(f'History {i}/{len(universe)}; errors={len(errors)}', flush=True)
    if wanted is None:
        params = {'symbol': 'NSE:NIFTY50-INDEX', 'resolution': '1', 'date_format': '1',
                  'range_from': day.isoformat(), 'range_to': day.isoformat(), 'cont_flag': '1'}
        try:
            result = call(provider._request, '/data/history?' + urlencode(params))
            save(args.run / 'inputs/benchmark.json', [r[:6] for r in result.get('candles', []) if int(r[0]) + 60 <= cutoff])
        except ScannerError:
            save(args.run / 'inputs/benchmark.json', [])
    save(args.run / ('warmup_errors.json' if wanted is not None else 'history_errors.json'), errors)
    manifest = {str(p.relative_to(args.run)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((args.run / 'inputs').rglob('*')) if p.is_file()}
    save(args.run / 'input_hashes.json', manifest)
    print(f'Input stage complete: {len(universe)} instruments; errors={len(errors)}', flush=True)


if __name__ == '__main__':
    main()
