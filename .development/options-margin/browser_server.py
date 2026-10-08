"""Synthetic margin preview. Uses isolated fixture app; no broker requests."""
import json
import os
import runpy
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.argv.append('--production-bundle')
base = runpy.run_path(str(ROOT / '.development/report-journal/browser_server.py'))
app = base['app']
from flask import jsonify, request, send_from_directory
from services import options_capital
from strategies.nifty_options.state import Store
from test.test_nifty_options_strategies import opened
os.environ['NIFTY_OPTIONS_STATE_DB'] = str(ROOT / 'log/test/options-margin/browser-state.db')
store = Store(options_capital.state_path())
for name in options_capital.PROFILES:
    _, state, _ = opened(name, quantity=650)
    for leg in state['legs']:
        leg['symbol'] = 'NIFTY13OCT26' + str(leg['strike']) + leg['kind']
    quote = {'quoted_at':'2026-10-08T09:30:00+05:30','margin_total':1750000,
             'margin_new_order':1625000,'sizing_requirement':1750000}
    state['capital_snapshot'] = {'lots_per_leg':10,'basket':quote,
                                'one_lot':dict(quote,sizing_requirement=175000),'utilization_pct':87.5}
    rev, _ = store.load('fixture', name)
    store.save('fixture', name, rev, state)
@app.get('/market-scanner/api/options-capital')
def capital():
    return jsonify(status='success', data=options_capital.overview('fixture'))
@app.post('/market-scanner/api/options-capital/quote')
def margin():
    data=request.get_json()
    return jsonify(status='success',data={**quote,'fingerprint':data['fingerprint'],
                                          'strategy_id':data['strategy_id']})
@app.get('/dashboard')
def dashboard():
    return send_from_directory(ROOT/'frontend/dist','index.html')
@app.get('/auth/dashboard-data')
def funds():
    return jsonify(status='success',data={'availablecash':'49000000','collateral':'0',
      'm2munrealized':'1200','m2mrealized':'5000','utiliseddebits':'1000000'})
if __name__ == '__main__':
    (ROOT/'log/dev/options-margin-process.json').write_text(json.dumps({'pid':os.getpid(),'port':5011,'command':str(Path(__file__).resolve())}))
    app.run(host='127.0.0.1',port=5011,use_reloader=False)
