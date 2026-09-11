"""Read-only Historify input and an idempotent, separate CSV research catalog."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TZ = 'Asia/Kolkata'
OHLCV = ['open', 'high', 'low', 'close', 'volume']


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def connect(path, readonly=False):
    c = duckdb.connect(str(path), read_only=readonly, config={'threads': 2})
    c.execute('SET enable_progress_bar=false')
    return c


def init_catalog(c):
    c.execute('''CREATE TABLE IF NOT EXISTS source_files(
        path VARCHAR PRIMARY KEY, sha256 VARCHAR, kind VARCHAR, rows BIGINT,
        columns_json VARCHAR, status VARCHAR, error VARCHAR)''')
    c.execute('''CREATE TABLE IF NOT EXISTS csv_rows(
        path VARCHAR, row_number BIGINT, payload VARCHAR,
        PRIMARY KEY(path,row_number))''')
    c.execute('''CREATE TABLE IF NOT EXISTS universe_snapshots(
        source_path VARCHAR, symbol VARCHAR, name VARCHAR, as_of DATE,
        PRIMARY KEY(source_path,symbol))''')
    c.execute('''CREATE TABLE IF NOT EXISTS csv_ohlcv(
        source_path VARCHAR, symbol VARCHAR, exchange VARCHAR, interval VARCHAR,
        timestamp BIGINT, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
        volume DOUBLE, PRIMARY KEY(source_path,symbol,interval,timestamp))''')
    c.execute('''CREATE TABLE IF NOT EXISTS backtest_runs(
        run_id VARCHAR PRIMARY KEY, manifest VARCHAR, status VARCHAR)''')


def csv_kind(path, columns):
    cols = set(columns)
    lower = str(path).lower()
    if any(x in lower for x in ['heikin', 'hekin', 'indicators', 'real_vs_']):
        return 'synthetic_or_diagnostic'
    if set(OHLCV) <= cols and ('timestamp' in cols or {'date', 'time'} <= cols):
        if any(x in lower for x in ['validated_ohlcv', 'normalized_real', 'backtest_output', 'stratagies_backtest_output']):
            return 'derived_ohlcv'
        return 'ohlcv'
    if 'symbol' in cols and ('company name' in cols or 'industry' in cols):
        return 'universe'
    if 'name' in cols and 'ltp' in cols:
        return 'screener_snapshot'
    if {'date', 'open', 'high', 'low', 'close'} <= cols:
        return 'daily_reference_without_volume'
    return 'reference_or_report'


def ingest_csvs(c, roots):
    """Archive every CSV row; only genuine OHLCV feeds the candle table."""
    paths = sorted({p.resolve() for root in roots if Path(root).exists()
                    for p in Path(root).rglob('*.csv')
                    if not any(x in p.parts for x in ['.venv', 'node_modules', 'all_stock_ha'])})
    for path in paths:
        sha = digest(path)
        old = c.execute('SELECT sha256,status FROM source_files WHERE path=?', [str(path)]).fetchone()
        if old == (sha, 'imported'):
            continue
        columns, kind, count = [], 'unknown', 0
        try:
            c.execute('BEGIN')
            for table in ['csv_rows', 'universe_snapshots', 'csv_ohlcv']:
                key = 'path' if table == 'csv_rows' else 'source_path'
                c.execute(f'DELETE FROM {table} WHERE {key}=?', [str(path)])
            with path.open(encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                columns = [str(x).strip().lower() for x in (reader.fieldnames or [])]
                if len(columns) != len(set(columns)):
                    raise ValueError('duplicate normalized column names')
                kind = csv_kind(path, columns)
                batch = []
                for count, row in enumerate(reader, 1):
                    if None in row:
                        raise ValueError(f'extra fields at row {count}')
                    values = {str(k).strip().lower(): v for k, v in row.items()}
                    batch.append((str(path), count, json.dumps(values, ensure_ascii=False)))
                    if len(batch) >= 10000:
                        archive_batch(c, batch)
                        batch = []
                archive_batch(c, batch)
            if kind == 'universe':
                c.execute('''INSERT INTO universe_snapshots
                    SELECT path, upper(trim(json_extract_string(payload,'$.symbol'))),
                        json_extract_string(payload,'$."company name"'), NULL
                    FROM csv_rows WHERE path=?
                    QUALIFY row_number() OVER(PARTITION BY path,
                        upper(trim(json_extract_string(payload,'$.symbol'))))=1''', [str(path)])
            if kind == 'ohlcv':
                import_candles(c, path)
            c.execute('INSERT OR REPLACE INTO source_files VALUES (?,?,?,?,?,?,?)',
                      [str(path), sha, kind, count, json.dumps(columns), 'imported', None])
            c.execute('COMMIT')
        except Exception as exc:
            c.execute('ROLLBACK')
            c.execute('INSERT OR REPLACE INTO source_files VALUES (?,?,?,?,?,?,?)',
                      [str(path), sha, kind, count, json.dumps(columns), 'quarantined', str(exc)])
        print(f'CSV {kind}: {path.name} ({count} rows)', flush=True)
    return c.execute('SELECT * FROM source_files ORDER BY path').fetchdf()


def archive_batch(c, rows):
    if rows:
        frame = pd.DataFrame(rows, columns=['path', 'row_number', 'payload'])
        c.register('_archive', frame)
        try:
            c.execute('INSERT INTO csv_rows SELECT * FROM _archive')
        finally:
            c.unregister('_archive')


def import_candles(c, path):
    frame = pd.read_csv(path)
    frame.columns = frame.columns.str.strip().str.lower()
    stamp = frame['timestamp'] if 'timestamp' in frame else frame['date'] + ' ' + frame['time']
    if pd.api.types.is_numeric_dtype(stamp):
        # Require a plausible epoch unit rather than treating an integer as nanoseconds.
        unit = 'ms' if stamp.abs().median() > 1e11 else 's'
        idx = pd.DatetimeIndex(pd.to_datetime(stamp, unit=unit, utc=True))
    else:
        idx = pd.DatetimeIndex(pd.to_datetime(stamp, format='mixed'))
        idx = idx.tz_localize(TZ) if idx.tz is None else idx
    frame['timestamp'] = idx.tz_convert('UTC').as_unit('s').asi8
    if 'symbol' not in frame:
        # Historify export naming contract; unknown files are quarantined.
        parts = path.stem.split('_')
        if len(parts) < 3 or parts[-2] not in ['NSE', 'BSE']:
            raise ValueError('OHLCV missing symbol; expected SYMBOL_EXCHANGE_INTERVAL.csv')
        frame['symbol'], frame['exchange'], frame['interval'] = '_'.join(parts[:-2]), parts[-2], parts[-1]
    frame['exchange'] = frame.get('exchange', 'NSE')
    if 'interval' not in frame:
        intervals = np.diff(np.sort(frame.timestamp.unique()))
        intervals = intervals[(intervals > 0) & (intervals <= 300)]
        if not len(intervals):
            raise ValueError('cannot infer interval')
        minutes = int(np.min(intervals) // 60)
        if minutes not in (1, 5):
            raise ValueError('unsupported inferred interval')
        frame['interval'] = f'{minutes}m'
    frame['source_path'] = str(path)
    if frame.duplicated(['symbol', 'interval', 'timestamp']).any():
        raise ValueError('duplicate candles; resolve conflicting source before ingestion')
    frame[OHLCV] = frame[OHLCV].apply(pd.to_numeric, errors='raise')
    if not valid_rows(frame).all():
        raise ValueError('invalid OHLCV values')
    columns = ['source_path', 'symbol', 'exchange', 'interval', 'timestamp'] + OHLCV
    c.register('_candles', frame[columns])
    try:
        c.execute('INSERT INTO csv_ohlcv SELECT * FROM _candles')
    finally:
        c.unregister('_candles')


def valid_rows(d):
    return (np.isfinite(d[OHLCV]).all(axis=1) & (d[OHLCV[:4]] > 0).all(axis=1)
            & (d.volume >= 0) & (d.high >= d[['open', 'close', 'low']].max(axis=1))
            & (d.low <= d[['open', 'close', 'high']].min(axis=1)))


def complete_sessions(frame, minutes=1):
    """No invented candles. Invalid/incomplete regular sessions are excluded."""
    d = frame.sort_values('timestamp').reset_index(drop=True)
    stamps = d.timestamp.to_numpy(dtype=np.int64)
    local = stamps + 19800
    days = local // 86400
    slots = (local % 86400) // 60
    regular = (slots >= 555) & (slots < 930)
    now = pd.Timestamp.now(tz='UTC').timestamp()
    valid = valid_rows(d).to_numpy() & (stamps % 60 == 0) & (stamps + minutes*60 <= now)
    expected = np.arange(555, 930, minutes)
    keep = np.zeros(len(d), dtype=bool)
    records = []
    unique_days, starts, counts = np.unique(days, return_index=True, return_counts=True)
    for day, start, count in zip(unique_days, starts, counts):
        inds = np.arange(start, start+count)
        inds = inds[regular[inds]]
        ok = len(inds) == len(expected) and np.array_equal(slots[inds], expected) and valid[inds].all()
        if ok:
            keep[inds] = True
        records.append({'date': str(pd.Timestamp(int(day)*86400, unit='s').date()),
                        'source_rows': int(count), 'regular_rows': len(inds),
                        'expected_rows': len(expected), 'valid_session': bool(ok),
                        'reason': '' if ok else 'incomplete_duplicate_invalid_or_unfinished_session'})
    return d.loc[keep].reset_index(drop=True), pd.DataFrame(records)


def aggregate_five(d):
    if d.empty:
        return d.copy()
    a = d[OHLCV].to_numpy().reshape(-1, 5, 5)
    return pd.DataFrame({'timestamp': d.timestamp.to_numpy()[::5],
                         'open': a[:, 0, 0], 'high': a[:, :, 1].max(axis=1),
                         'low': a[:, :, 2].min(axis=1), 'close': a[:, -1, 3],
                         'volume': a[:, :, 4].sum(axis=1)})
