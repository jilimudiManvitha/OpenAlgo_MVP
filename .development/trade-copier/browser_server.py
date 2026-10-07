"""Isolated copier fixture: synthetic broker responses only, port 5011."""
import atexit
import os
import runpy
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
runpy.run_path(str(ROOT/'test/conftest.py'))
os.environ['DATABASE_URL']='sqlite:///log/test/copier-browser-auth.db'
from flask import Flask, jsonify, session, send_from_directory, request
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from cryptography.fernet import Fernet
from services.trade_copier.engine import Engine
from services.trade_copier import runtime
from blueprints.trade_copier import trade_copier_bp
from utils import session as auth_session
from test.test_trade_copier import Fake, event, settled

PREVIEW=ROOT/'.development/trade-copier/dist'
if '--production-bundle' in sys.argv:
    PREVIEW = ROOT / 'frontend/dist'
app=Flask(__name__,static_folder=str(PREVIEW/'assets'),static_url_path='/assets')
app.secret_key='synthetic-copier-preview-only'
csrf=CSRFProtect(app)
mode={'value':'live'}
auth_session.is_session_valid=lambda:session.get('user')=='fixture'
runtime.active_mode=lambda:mode['value']
fakes={}
def factory(a):
    return fakes.setdefault(a.id,Fake(a.client_id))
vault=Fernet(Fernet.generate_key())
# Unique database per preview. Never overwrite another lane's file.
import tempfile
fd,path=tempfile.mkstemp(prefix='copier-browser-',suffix='.db',dir=ROOT/'log/test')
os.close(fd)
e=Engine('sqlite:///'+path,lambda s:vault.encrypt(s.encode()).decode(),lambda s:vault.decrypt(s.encode()).decode(),
         lambda *_:([],['SYNTHETIC-MASTER']),lambda owner,m,*_:m==mode['value'],lambda *_:dict(lot=1,price=825),transport=factory)
app.config['TRADE_COPIER_ENGINE']=e
app.register_blueprint(trade_copier_bp)
csrf.exempt(app.view_functions['trade_copier.bridge'])
for selected in ('paper','live'):
    mode['value']=selected
    for broker,name,client in [('fyers','Family · FYERS','FY-DEMO'),('zerodha','Investment · Zerodha','Z-DEMO'),('dhan','Trading · Dhan','D-DEMO')]:
        e.account('fixture',selected,dict(name=name,broker=broker,client_id=client,symbols=['NSE:SBIN','NSE:TCS'],
                                       credentials=dict(app_id='FIXTURE',access_token='NOT-A-REAL-TOKEN'),max_order_value=200000,max_daily_value=1000000))
    e.control('fixture',selected,'fyers','arm')
    for i in range(3):
        e.ingest('fixture',selected,'fyers',event(orderid=f'DEMO-{i+1}',average_price=825,filled_quantity=10,order_status='complete'))
        # Scope-aware bounded wait; no broker or app process is involved.
        import time
        while any(a['status'] in ('QUEUED','SUBMITTING') for a in e.snapshot('fixture',selected,'fyers')['attempts']):
            time.sleep(.01)
    e.control('fixture',selected,'fyers','disarm')
mode['value']='live'
@app.get('/auth/session-status')
def auth():
    session['user']='fixture';session['broker']='fyers'
    return jsonify(status='success',logged_in=True,user='fixture',broker='fyers',active_sessions=1)
@app.get('/auth/csrf-token')
def token():
    return jsonify(csrf_token=generate_csrf())
@app.get('/auth/analyzer-mode')
def analyzer():
    return jsonify(status='success',data={'analyze_mode':mode['value']=='paper'})
@app.post('/auth/analyzer-toggle')
def toggle():
    e.control('fixture',mode['value'],'fyers','disarm')
    mode['value']='paper' if mode['value']=='live' else 'live'
    return jsonify(status='success',data={'analyze_mode':mode['value']=='paper','message':'Synthetic fixture mode changed'})
@app.get('/api/broker/capabilities')
def capabilities():
    return jsonify(status='success',data={'broker_name':'fyers','broker_type':'IN_stock','supported_exchanges':['NSE']})
@app.get('/logo.png')
def logo():
    return send_from_directory(PREVIEW,'logo.png')
# Override only the preview page handler; real API routes stay unchanged.
app.view_functions['trade_copier.page']=lambda:send_from_directory(PREVIEW,'index.html')
@app.get('/health')
def health():
    return jsonify(preview=True,synthetic=True)
@app.post('/fixture/master')
def master():
    e.ingest('fixture',mode['value'],'fyers',event(orderid='UI-'+str(time.time_ns()),filled_quantity=10,order_status='complete'))
    return jsonify(ok=True)
atexit.register(e.close)
if __name__=='__main__':
    app.run(host='127.0.0.1',port=5011,use_reloader=False,threaded=True)
