"""Isolated browser fixture: real investment API/CSRF/SQLite, fake signed-in identity.

Never loads the operator's .env, scheduler, broker adapter or sandbox engine.
"""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'test/conftest.py'))
os.environ['DATABASE_URL'] = 'sqlite:///log/test/investment-browser.db'
from flask import Flask, jsonify, send_from_directory, session
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from database import investment_db as db
from utils import session as auth

auth.is_session_valid = lambda: session.get('user') == 'investment_browser_fixture'
from blueprints.investments import investments_bp

db.Base.metadata.drop_all(db.engine)  # Only this explicitly isolated fixture database.
db.Base.metadata.create_all(db.engine)
from database import settings_db
settings_db.init_db()
settings_db.set_analyze_mode(True)
PREVIEW = ROOT / ('frontend/dist' if '--production-bundle' in sys.argv else '.development/investment/dist')
if not (PREVIEW / 'index.html').is_file():
    raise RuntimeError('Build the isolated investment preview before starting this fixture')
app = Flask(__name__, static_folder=str(PREVIEW / 'assets'), static_url_path='/assets')
app.secret_key = 'isolated-browser-fixture-not-production'
CSRFProtect(app)
app.register_blueprint(investments_bp)

@app.get('/auth/session-status')
def login():
    session['user'] = 'investment_browser_fixture'
    session['broker'] = 'fyers'
    return jsonify(status='success', logged_in=True, user=session['user'], broker='fyers', active_sessions=1)

@app.get('/auth/csrf-token')
def csrf():
    return jsonify(csrf_token=generate_csrf())

@app.get('/api/broker/capabilities')
def broker():
    return jsonify(status='success', data={'broker_name': 'fyers', 'broker_type': 'IN_stock', 'supported_exchanges': ['NSE', 'BSE']})

@app.get('/auth/analyzer-mode')
def mode():
    return jsonify(status='success', data={'analyze_mode': True})

@app.get('/portfolio')
@app.get('/portfolio/stocks')
@app.get('/portfolio/reports')
@app.get('/portfolio/watchlists')
@app.get('/portfolio/assets/<asset_class>')
def frontend(asset_class=None):
    return send_from_directory(PREVIEW, 'index.html')

if __name__ == '__main__':
    import json
    (ROOT / 'log/dev').mkdir(parents=True, exist_ok=True)
    (ROOT / 'log/dev/investment-preview-process.json').write_text(json.dumps({
        'pid': os.getpid(), 'port': 5011, 'command': str(Path(__file__).resolve()),
    }))
    app.run(host='127.0.0.1', port=5011, use_reloader=False)
