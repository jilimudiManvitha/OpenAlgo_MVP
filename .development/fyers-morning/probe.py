"""Read-only FYERS quotes/margins using a private DB snapshot; NEVER orders."""
import json
import os
import runpy
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values
config=dotenv_values(ROOT/'.env')
runpy.run_path(str(ROOT/'test/conftest.py'))
for key in ('APP_KEY','API_KEY_PEPPER','FERNET_SALT','BROKER_API_KEY'):
    if config.get(key): os.environ[key]=config[key]
os.environ['LOG_DIR']=str(ROOT/'log/test/fyers-morning')
result={'orders_sent':0,'quotes':None,'margins':[]}
with tempfile.TemporaryDirectory(dir=ROOT/'log/test/fyers-morning') as folder:
    folder=Path(folder)
    snapshot=folder/'auth-symbols.db'
    with closing(sqlite3.connect((ROOT/'db/openalgo.db').as_uri()+'?mode=ro',uri=True)) as src:
        with closing(sqlite3.connect(snapshot)) as dest: src.backup(dest)
    snapshot.chmod(0o600)
    os.environ['DATABASE_URL']='sqlite:///'+str(snapshot)
    os.environ['NIFTY_OPTIONS_STATE_DB']=str(ROOT/'db/nifty_options/state.sqlite3')
    from services.options_capital import overview, current_quote
    from services.market_scanner_provider import credentials
    from strategies.nifty_options import runtime
    from broker.fyers.api.data import BrokerData
    from utils.httpx_client import get_httpx_client, cleanup_httpx_client
    real=get_httpx_client()
    class ReadOnlyClient:
        def get(self,url,**kw):
            assert url.startswith('https://api-t1.fyers.in/data/quotes?')
            return real.get(url,**kw)
        def post(self,url,**kw):
            assert url=='https://api-t1.fyers.in/api/v3/multiorder/margin'
            return real.post(url,**kw)
    import utils.httpx_client as http
    import broker.fyers.api.data as data
    http.get_httpx_client=lambda:ReadOnlyClient()
    data.get_httpx_client=http.get_httpx_client
    runtime.ROOT=folder  # margin sidecar belongs to the test, not production db/.
    with closing(sqlite3.connect(snapshot)) as conn:
        owners=[r[0] for r in conn.execute("SELECT name FROM auth WHERE broker='fyers' AND is_revoked=0")]
    try:
        assert len(owners)==1,'Expected one active FYERS session'
        owner=owners[0]
        token,_=credentials(owner,'fyers')
        view=overview(owner)
        symbols=sorted({leg['symbol'] for row in view['strategies'] for leg in row['legs']})
        quotes=BrokerData(token).get_multiquotes([{'symbol':s,'exchange':'NFO'} for s in symbols],include_oi=False)
        result['quotes']={'requested':len(symbols),'received':sum(bool(q.get('data',{}).get('ltp',0)>0) for q in quotes)}
        for sid in ['combined']+[r['strategy_id'] for r in view['strategies'] if r['legs']]:
            q=current_quote(owner,sid,view['fingerprint'])
            result['margins'].append({k:q[k] for k in ('strategy_id','quoted_at','margin_total','margin_new_order','sizing_requirement')})
        result['passed']=result['quotes']['requested']==result['quotes']['received'] and len(result['margins'])==7
    except Exception as exc:
        result.update(passed=False,error_type=type(exc).__name__)
        # Known controlled errors only; never stringify arbitrary HTTP/auth errors.
        from services.market_scanner_provider import ScannerError
        from strategies.nifty_options.selection import DataUnavailable
        if isinstance(exc,(ScannerError,DataUnavailable)):result['error']=str(exc)
    finally:
        runtime.cleanup_sessions()
        cleanup_httpx_client()
    from database.auth_db import engine as auth_engine
    from database.symbol import engine as symbol_engine
    auth_engine.dispose();symbol_engine.dispose()
(ROOT/'log/test/fyers-morning/live-probe.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
