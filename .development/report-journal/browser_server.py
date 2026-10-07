"""Read-only journal preview with synthetic reports. No production app imports."""
import json
import os
import runpy
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'test/conftest.py'))
os.environ['DATABASE_URL'] = 'sqlite:///log/test/live-sandbox-browser.db'
from flask import Flask, jsonify, request, send_from_directory, session
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from services.report_journal import journal
from services.scanner_strategy_reports import ReportStore
from test.test_report_journal import trade, report

DB = ROOT / 'log/test/report-journal-browser.db'
PREVIEW = ROOT / '.development/report-journal/dist'
if '--production-bundle' in sys.argv:
    PREVIEW = ROOT / 'frontend/dist'
store = ReportStore(DB)
try:
    for offset, profit in [(0,110),(1,-90),(2,60),(5,210),(6,10),(7,-50),(8,150)]:
        day = str(date(2026,10,1)+timedelta(days=offset))
        for sid,name in [('fixed','Sandbox · Nifty500 Fixed 3R'),('trail','Sandbox · Watchlist Trailing')]:
            ts=[trade(day,gross=profit),trade(day,start='11:30',end='12:00',gross=-40),trade(day,start='13:00',end='14:00',gross=10)] if sid=='fixed' else [trade(day,symbol='TCS',start='14:30',end='15:00',gross=110)]
            ts=[{**t,'exit': t['entry']+t['gross_pnl']/t['quantity'],'stop':99,'target':103,'reason':'fixture','signal_ts':t['entry_ts']} for t in ts]
            r=report(day,sid,ts)
            r['candles']={symbol:[dict(timestamp=ts[0]['entry_ts']-900+i*60,
                open=100,high=101,low=99.5,close=100.5,ha_open=100,ha_high=101,
                ha_low=99.5,ha_close=100.5,bb_upper=102,bb_middle=100,vwap=100.1)
                for i in range(340)] for symbol in {t['symbol'] for t in ts}}
            r['capital_per_trade']=10000
            r['kind']=name
            r['note']='Synthetic preview data only. Not actual trading results.'
            store.save('fixture',r)
finally:
    store.close()
app=Flask(__name__, static_folder=str(PREVIEW/'assets'),static_url_path='/assets')
app.secret_key='isolated-mode-fixture'
CSRFProtect(app)
preview_mode={'paper':True}
@app.get('/auth/session-status')
def auth():
    session['user']='fixture'
    session['broker']='fyers'
    return jsonify(status='success',logged_in=True,user='fixture',broker='fyers',active_sessions=1)
@app.get('/auth/csrf-token')
def csrf():
    return jsonify(csrf_token=generate_csrf())
@app.get('/auth/analyzer-mode')
def mode():
    return jsonify(status='success',data={'analyze_mode':preview_mode['paper']})
@app.get('/api/broker/capabilities')
def broker():
    return jsonify(status='success',data={'broker_name':'fyers','broker_type':'IN_stock','supported_exchanges':['NSE']})
@app.get('/market-scanner/api/report-journal')
def data():
    return jsonify(status='success',data=journal('fixture',int(request.args.get('year','2026')),request.args.get('scenario','PAPER'),request.args.get('strategy',''),request.args.get('symbol',''),path=DB, session_broker=request.args.get('preview_broker','fyers'), charge_basis=request.args.get('charges','estimated')))
@app.get('/market-scanner/api/report-journal/<report_id>')
def detail(report_id):
    from services.report_journal import journal_detail
    from services.report_brokerage import charges_csv
    from flask import Response
    result=journal_detail('fixture',report_id,'fyers',request.args.get('charges','estimated'),path=DB)
    if request.args.get('download')=='csv': return Response(charges_csv(result),mimetype='text/csv')
    return jsonify(status='success',data=result)
@app.get('/logo.png')
def logo():
    return send_from_directory(PREVIEW,'logo.png')
@app.get('/reports')
@app.get('/strategy-reports')
def frontend():
    return send_from_directory(PREVIEW,'index.html')

from services import investment_execution as execution, investment_mode, investment_service as ledger
from database import investment_db as investment_db
from utils import session as auth_session
from blueprints.investments import investments_bp
assert str(investment_db.engine.url).endswith('log/test/live-sandbox-browser.db')
investment_db.Base.metadata.drop_all(investment_db.engine)
investment_db.Base.metadata.create_all(investment_db.engine)
auth_session.is_session_valid=lambda: session.get('user')=='fixture'
investment_mode.get_analyze_mode=lambda: preview_mode['paper']
execution.authenticate=lambda *_: 'fixture-only'
execution.tick_check=lambda *_: None
execution.dispatch=lambda *args: (True, {'orderid':'FIXTURE-ORDER','trigger_id':'FIXTURE-GTT','message':'Synthetic broker acceptance; no broker called'}, 200)
app.register_blueprint(investments_bp)
for kind,qty in [('paper','3'),('live','7')]:
    account=ledger.save_account('fixture',{'name':kind.title()+' savings','kind':kind,'broker_label':'FYERS'})
    asset=ledger.save_asset('fixture',{'account_id':account['id'],'symbol':'SBIN','exchange':'NSE'})
    ledger.save_transaction('fixture',dict(asset_id=asset['id'],action='BUY',quantity=qty,price='100',trade_date='2026-09-01',trade_time='09:30'))
@app.post('/auth/analyzer-toggle')
def toggle_mode():
    preview_mode['paper']=not preview_mode['paper']
    return jsonify(status='success',data={'analyze_mode':preview_mode['paper'],'message':'Fixture mode changed'})
@app.get('/portfolio')
@app.get('/portfolio/stocks')
@app.get('/portfolio/reports')
@app.get('/portfolio/watchlists')
@app.get('/market-scanner')
def mode_frontend():
    return send_from_directory(PREVIEW,'index.html')
@app.get('/market-scanner/api/live')
def scanner_fixture():
    return jsonify(status='success',data={'enabled':False,'broker':'fyers','categories':[],
        'matching_counts':{},'options':{'lookback_days':20},'stale':True,'market_open':False,
        'volume_shockers':[],'top_gainers':[],'top_losers':[],'filtered_quotes':0,'timestamp_support':'fixture'})
if __name__=='__main__':
    (ROOT/'log/dev').mkdir(parents=True,exist_ok=True)
    (ROOT/'log/dev/report-journal-process.json').write_text(json.dumps({'pid':os.getpid(),'port':5011,'command':str(Path(__file__).resolve())}))
    app.run(host='127.0.0.1',port=5011,use_reloader=False)
