"""Read-only main-app timing: no order endpoints; credentials never leave localhost."""
import json, os, sqlite3, sys, time
from contextlib import closing
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
OUT=ROOT/'log/test/oct8-mock';private=OUT/'private';private.mkdir(exist_ok=True);private.chmod(0o700)
import dotenv
dotenv.load_dotenv(ROOT/'.env');dotenv.load_dotenv=lambda *a,**k:False;dotenv.main.load_dotenv=dotenv.load_dotenv
with closing(sqlite3.connect((ROOT/'db/openalgo.db').as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(private/'auth.db')) as target:source.backup(target)
(private/'auth.db').chmod(0o600)
os.environ['DATABASE_URL']='sqlite:///'+str(private/'auth.db');os.environ['LOG_DIR']=str(OUT/'read-client')
from database.auth_db import get_first_available_api_key, db_session
key=get_first_available_api_key();db_session.remove();assert key, 'No active local API key'
rows=[]
try:
 for round_no in range(int(os.getenv('PROBE_ROUNDS','5'))):
  for endpoint in ('orderbook','tradebook','positionbook','quotes'):
   body={'apikey':key}
   if endpoint=='quotes':body.update(symbol='SBIN',exchange='NSE')
   req=Request('http://127.0.0.1:5000/api/v1/'+endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
   start=time.perf_counter()
   try:
    with urlopen(req,timeout=40) as response: status=response.status;data=json.load(response)
   except HTTPError as exc:status=exc.code;data=json.loads(exc.read())
   row={'endpoint':endpoint,'round':round_no+1,'client_ms':round((time.perf_counter()-start)*1000,3),'http_status':status,'status':data.get('status'),'mode':data.get('mode'),'retry_after':data.get('retry_after')}
   rows.append(row);print(json.dumps(row),flush=True)
   (OUT/os.getenv('PROBE_OUTPUT','live-read-results.json')).write_text(json.dumps(rows,indent=2))
   time.sleep(float(os.getenv('PROBE_PAUSE','.2')))
finally:db_session.remove()
