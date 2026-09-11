"""Bounded read-only broker verification of the isolated scanner; no order imports."""
import json
import time
from pathlib import Path

from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent
load_dotenv(HERE.parents[1]/'.env')
import conftest  # noqa: F401,E402 - activate isolated scanner import paths
from database.auth_db import Auth, db_session  # noqa: E402
from services.market_scanner_live import import_categories, view_snapshot  # noqa: E402
from services.market_scanner_provider import provider_for, universe_for  # noqa: E402
from services.market_scanner_service import ScannerManager, validate_options  # noqa: E402

try:
    users=db_session.query(Auth.name).filter(Auth.broker=='fyers',Auth.is_revoked.is_(False)).all()
finally:
    db_session.remove()
if len(users)!=1:
    raise SystemExit('Live verification requires exactly one active Fyers login.')
user=users[0][0]
provider=provider_for(user,'fyers')
manager=ScannerManager(provider_factory=lambda _:provider,universe_loader=lambda:universe_for('fyers'))
result,_=manager.start(user,{'symbols':['RELIANCE','SBIN','ATHERENERG'],'limit':50})
deadline=time.monotonic()+180
while result['state']=='running' and time.monotonic()<deadline:
    time.sleep(1)
    result=manager.results(user)
if result['state']=='running':
    manager.cancel(user)
    raise SystemExit('Live probe timed out; cancellation requested.')
with manager.lock:
    result['rows']=manager.jobs[user]['rows']
view=view_snapshot(result,validate_options({'limit':50}),import_categories('stock_symbols_CSVs'))
out=HERE/'artifacts'
out.mkdir(exist_ok=True)
(out/'live-probe.json').write_text(json.dumps(view,indent=2,allow_nan=False),encoding='utf-8')
if manager._cache:
    manager._cache.engine.dispose()
print(json.dumps({'state':view['state'],'session_date':view['session_date'],
                  'valid_quotes':view['valid_quotes'],'total':view['total'],
                  'valid_baselines':view['valid_baselines'],'market_open':view['market_open'],
                  'error':view.get('error')}))
if view['state']!='completed' or view['valid_quotes']!=3:
    raise SystemExit(1)
