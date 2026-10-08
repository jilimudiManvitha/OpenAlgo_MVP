"""Loopback HTTP order benchmark; synthetic identity, mocked network, disposable DBs."""
import gc,json,os,runpy,socket,sys,tempfile,threading,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));runpy.run_path(str(ROOT/'test/conftest.py'))
OUT=ROOT/'log/test/oct8-mock';fixture=tempfile.TemporaryDirectory(prefix='benchmark-',dir=OUT)
for key,name in [('DATABASE_URL','auth'),('SANDBOX_DATABASE_URL','sandbox'),('LATENCY_DATABASE_URL','latency'),('LOGS_DATABASE_URL','logs')]:os.environ[key]='sqlite:///'+str(Path(fixture.name)/f'{name}.db')
os.environ['LOG_DIR']=str(OUT/'mock-runtime');os.environ['ORDER_RATE_LIMIT']='10 per second'
import httpx,numpy as np,psutil
from flask import Flask
from flask_restx import Api
from werkzeug.serving import make_server
from database import auth_db,settings_db,sandbox_db,symbol
from utils.db_sessions import remove_all_scoped_sessions
for mod in (auth_db,settings_db,sandbox_db,symbol):mod.init_db()
key='mock-only-oct8-benchmark';owner='mock-benchmark'
auth_db.db_session.add(auth_db.Auth(name=owner,auth=auth_db.encrypt_token('fake-token'),broker='fyers',is_revoked=False));auth_db.db_session.add(auth_db.ApiKeys(user_id=owner,api_key_hash=auth_db.ph.hash(key+auth_db.PEPPER),api_key_encrypted=auth_db.encrypt_token(key)));auth_db.db_session.commit()
symbol.db_session.add(symbol.SymToken(symbol='SBIN',brsymbol='SBIN-EQ',name='Mock SBI',exchange='NSE',brexchange='NSE',token='3045',lotsize=1,instrumenttype='EQ',tick_size=.05,contract_value=1.0));symbol.db_session.commit()
import restx_api
from services import place_order_service as service
from utils import httpx_client,latency_monitor
from database.latency_db import init_latency_db,OrderLatency,latency_session
from sandbox.execution_engine import ExecutionEngine
from limiter import limiter
from restx_api.place_order import api as ns,PlaceOrder
from utils.event_bus import bus
init_latency_db();mode={'delay':0,'reject':False};counter=0
# Hard guard: fixture code may only connect back to its own benchmark listener.
original_connect=socket.socket.connect
def local_only(sock,address):
    if isinstance(address,tuple) and address[:2]!=('127.0.0.1',5012):raise RuntimeError('External network forbidden in mock benchmark')
    return original_connect(sock,address)
socket.socket.connect=local_only
def transport(request):
    assert request.url.host=='mock-broker.invalid'
    time.sleep(mode['delay'])
    return httpx.Response(400 if mode['reject'] else 200,json={'status':'error' if mode['reject'] else 'success','message':'deliberate mock rejection'})
mockclient=httpx_client.TimedClient(transport=httpx.MockTransport(transport));httpx_client._httpx_client=mockclient
def place(data,token):
    global counter
    assert token=='fake-token';counter+=1
    res=mockclient.post('https://mock-broker.invalid/orders',json=data,timeout=2)
    return SimpleNamespace(status=res.status_code),res.json(),'MOCK-'+str(counter)
service.import_broker_module=lambda broker:SimpleNamespace(place_order_api=place)
ExecutionEngine._fetch_quote=lambda *a,**k:{'ltp':100,'bid':100,'ask':100,'open':100,'high':101,'low':99,'prev_close':100,'volume':10000}
app=Flask(__name__);app.secret_key='fixture';limiter.init_app(app);api=Api(app,doc=False);latency_monitor.wrap_resource_methods(PlaceOrder,'PLACE');api.add_namespace(ns,path='/api/v1/placeorder')
@app.teardown_appcontext
def cleanup(_=None):remove_all_scoped_sessions()
server=make_server('127.0.0.1',5012,app,threaded=True);thread=threading.Thread(target=server.serve_forever);thread.start()
process=psutil.Process();results=[];payload={'apikey':key,'strategy':'MOCK_LATENCY','symbol':'SBIN','exchange':'NSE','action':'BUY','quantity':1,'pricetype':'MARKET','product':'CNC'}
def stats(values):return {k:round(float(v),3) for k,v in {'avg_ms':np.mean(values),'p50_ms':np.percentile(values,50),'p95_ms':np.percentile(values,95),'p99_ms':np.percentile(values,99),'max_ms':max(values),'under_150_pct':100*sum(x<150 for x in values)/len(values)}.items()}
try:
 with httpx.Client(timeout=10,trust_env=False) as client:
  for label,paper,delay,n in [('mock_ack_0ms',False,0,100),('mock_ack_50ms',False,.05,100),('sandbox_fixed_quote',True,0,100)]:
   settings_db.set_analyze_mode(paper);remove_all_scoped_sessions();mode.update(delay=delay,reject=False)
   previous=latency_session.query(OrderLatency.id).order_by(OrderLatency.id.desc()).first();last=previous[0] if previous else 0;latency_session.remove()
   times=[];ids=[];fd_before=process.num_fds()
   for i in range(n):
    start=time.perf_counter();r=client.post('http://127.0.0.1:5012/api/v1/placeorder',json=payload);elapsed=(time.perf_counter()-start)*1000
    assert r.status_code==200,(r.status_code,r.text);assert r.json()['status']=='success';ids.append(r.json()['orderid']);times.append(elapsed)
    time.sleep(max(0,.115-(time.perf_counter()-start)))
   latency_monitor._latency_log_executor.submit(lambda:None).result(timeout=15)
   rows=latency_session.query(OrderLatency).filter(OrderLatency.id>last).all();assert len(rows)==n
   result={'test':label,'orders':n,'success':len(ids),'client_http':stats(times),'server_handler':stats([r.total_latency_ms for r in rows]),'mock_http_avg_ms':round(float(np.mean([r.rtt_ms for r in rows])),3),'overhead_avg_ms':round(float(np.mean([r.overhead_ms for r in rows])),3)}
   latency_session.remove()
   if paper:
    filled=sandbox_db.SandboxOrders.query.filter(sandbox_db.SandboxOrders.orderid.in_(ids),sandbox_db.SandboxOrders.order_status=='complete').count();assert filled==n;result['confirmed_paper_fills']=filled;sandbox_db.db_session.remove()
   gc.collect();result['fd_before']=fd_before;result['fd_after']=process.num_fds();results.append(result);print(json.dumps(result),flush=True)
  settings_db.set_analyze_mode(False);remove_all_scoped_sessions();mode.update(delay=0,reject=True)
  for _ in range(5):
   r=client.post('http://127.0.0.1:5012/api/v1/placeorder',json=payload);assert r.status_code==400;time.sleep(.115)
  latency_monitor._latency_log_executor.submit(lambda:None).result(timeout=15)
  assert latency_session.query(OrderLatency).filter_by(status='FAILED').count()==5
  (OUT/'mock-results.json').write_text(json.dumps({'market_closed':True,'results':results,'expected_rejections':5,'unexpected_failures':0,'real_broker_orders':0,'limitations':'Loopback REST/schema/auth/service/latency persistence; no production middleware/event subscribers, real broker network or exchange matching. Sandbox uses fixed synthetic quotes.'},indent=2))
finally:
 server.shutdown();thread.join(5);server.server_close();latency_monitor._latency_log_executor.shutdown(wait=True);mockclient.close();remove_all_scoped_sessions();fixture.cleanup()
