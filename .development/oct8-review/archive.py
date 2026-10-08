"""Build the requested archive from existing FYERS observations and missing ranges."""
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
START, END = date(2026, 7, 8), date(2026, 10, 7)
OUT = ROOT / 'backtesting/nifty_options/2026-07-08_2026-10-07'


def setup():
    import dotenv
    dotenv.load_dotenv(ROOT / '.env')
    dotenv.load_dotenv = lambda *a, **kw: False
    dotenv.main.load_dotenv = dotenv.load_dotenv
    private = ROOT / 'log/test/oct8-project/data-access'
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    target = private / 'openalgo.db'
    if not target.exists():
        with closing(sqlite3.connect((ROOT/'db/openalgo.db').as_uri()+'?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        target.chmod(0o600)
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(target)
    os.environ['LOG_DIR'] = str(private / 'logs')
    OUT.mkdir(parents=True, exist_ok=True)


def collect():
    from strategies.nifty_options import history as h
    from strategies.nifty_options.data_probe import active_login, expired_call
    _, token = active_login()
    manifest = h.discover(token, START, END, OUT)
    archives = [ROOT/'backtest/nifty_options/2026-07-03_2026-10-01/manifest.json', ROOT/'backtesting/all_scheduled_20261006/inputs/manifest.json', ROOT/'log/test/day-review-20261007/inputs/manifest.json']
    sources = defaultdict(list)
    for mf in archives:
        m = json.loads(mf.read_text())
        for c in m['contracts']:
            name = h.cache_file(c['symbol'], c['start'], c['end']).name
            candidates = [h.existing_cache_file(c['symbol'], c['start'], c['end']), mf.parent/'options/candles'/name]
            p = next((p for p in candidates if p.exists()), None)
            if p:
                sources[c['symbol']].append((c['start'], c['end'], p))
        for name in m['spot_files']:
            p = ROOT/name
            data=h.read_candles(p)
            sources['NSE:NIFTY50-INDEX'].append((m['start'],m['end'],p))
    work = [{'symbol':'NSE:NIFTY50-INDEX','start':str(START),'end':str(END),'expired':False}, *manifest['contracts']]
    progress = {'status':'downloading','contracts':len(manifest['contracts']),'completed':0,'new_requests':0,'reused_files':0}
    provenance = {}
    for i,c in enumerate(work):
        symbol, first, last = c['symbol'], c['start'], c['end']
        target=h.cache_file(symbol, first, last)
        if not target.exists():
            available = [(a,b,p) for a,b,p in sources[symbol] if a<=last and b>=first]
            rows={}; covered=set(); used=[]
            for a,b,p in available:
                data=h.read_candles(p)
                h.validate_rows(data['candles'], check_ohlc=symbol!='NSE:NIFTY50-INDEX')
                d=max(date.fromisoformat(a),date.fromisoformat(first)); end=min(date.fromisoformat(b),date.fromisoformat(last))
                while d<=end:
                    covered.add(str(d));d+=timedelta(days=1)
                for r in data['candles']:
                    # Identical prices with revised index volume are harmless: index is close-only.
                    if r['timestamp'] in rows and any(rows[r['timestamp']][k]!=r[k] for k in ('open','high','low','close')):
                        raise RuntimeError('Conflicting cached prices: '+symbol)
                    rows[r['timestamp']]=r
                used.append({'file':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
            d=date.fromisoformat(first); end=date.fromisoformat(last)
            while d<=end:
                if str(d) in covered:
                    d+=timedelta(days=1);continue
                begin=d
                while d<=end and str(d) not in covered: d+=timedelta(days=1)
                finish=d-timedelta(days=1)
                # Missing interval is retrieved, never treated as a zero-return session.
                if c['expired']:
                    data=expired_call(token,'history',{'broker_symbol':symbol,'interval':'1m','start_date':str(begin),'end_date':str(finish),'include_oi':True})
                else:
                    data=h.regular_history(token,symbol,str(begin),str(finish))
                h.validate_rows(data['candles'], check_ohlc=symbol!='NSE:NIFTY50-INDEX')
                for r in data['candles']:
                    if r['timestamp'] in rows and rows[r['timestamp']]['close']!=r['close']:raise RuntimeError('Conflicting downloaded prices: '+symbol)
                    rows[r['timestamp']]=r
                progress['new_requests']+=1
                time.sleep(.4)
            from strategies.nifty_options.engine import IST
            from datetime import datetime
            selected=[r for t,r in sorted(rows.items()) if first<=datetime.fromtimestamp(t,IST).date().isoformat()<=last]
            h.write_candles(target,{'broker_symbol':symbol,'candles':selected,'start_date':first,'end_date':last,'data_status':'ok' if selected else 'no_data','interval':'1m','index_close_only':symbol=='NSE:NIFTY50-INDEX','provenance':used})
            progress['reused_files']+=len(used)
            provenance[str(target.relative_to(ROOT))]=used
        progress['completed']=i+1
        if i%10==0:
            h.atomic_json(OUT/'download_status.json',progress);print(json.dumps(progress),flush=True)
    manifest['spot_files']=[str(h.cache_file('NSE:NIFTY50-INDEX',START,END).relative_to(ROOT))]
    h.atomic_json(OUT/'manifest.json',manifest)
    progress['status']='download_complete';h.atomic_json(OUT/'download_status.json',progress)
    print(json.dumps(progress),flush=True)

if __name__=='__main__':
    setup()
    collect()
