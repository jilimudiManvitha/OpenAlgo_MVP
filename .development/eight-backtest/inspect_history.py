import sys,json,sqlite3,time
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from services.market_scanner_provider import FyersScannerProvider,get_fyers_token
from utils.httpx_client import cleanup_httpx_client
with sqlite3.connect('file:db/market_scanner_live.db?mode=ro',uri=True) as c:
 owner=c.execute("select user from scanner_live_accounts where broker='fyers'").fetchone()[0]
p=FyersScannerProvider(get_fyers_token(owner)); IST=ZoneInfo('Asia/Kolkata')
a=int(datetime(2026,9,30,9,15,tzinfo=IST).timestamp())
queries=[('session',0,a,a+375*60-1,1)]
try:
 for label,fmt,first,last,cont in queries:
  params=dict(symbol='NSE:NIFTY50-INDEX',resolution='1',date_format=fmt,range_from=first,range_to=last,cont_flag=cont)
  response=p._request('/data/history?'+urlencode(params))
  rows=response.get('candles',[]);groups=defaultdict(list)
  for r in rows:groups[r[0]].append(r)
  conflicts=sum(any(x!=v[0] for x in v[1:]) for v in groups.values())
  print(label,'rows',len(rows),'unique',len(groups),'conflicts',conflicts,'first',rows[:1],'last',rows[-1:],flush=True)
  (ROOT/'.development/eight-backtest'/f'nifty-{label}.json').write_text(json.dumps(response))
  time.sleep(1)
finally:cleanup_httpx_client()
