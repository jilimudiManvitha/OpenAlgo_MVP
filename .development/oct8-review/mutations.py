"""Prove regressions against baseline source/in-memory defects, never edit production files."""
import importlib
import os
import runpy
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
runpy.run_path(str(ROOT/'test/conftest.py'))
import pytest
mode=sys.argv[1]
if mode=='sessions':
    original=Path.read_text
    files={ROOT/'broker'/b/'api/data.py':subprocess.check_output(['git','show','HEAD:broker/'+b+'/api/data.py'],cwd=ROOT,text=True) for b in ('compositedge','fivepaisaxts','ibulls','iifl','jainamxts','rmoney','wisdom')}
    Path.read_text=lambda p,*a,**k: files[p] if p in files else original(p,*a,**k)
    selection='test_depth_uses_request_credentials_without_shadowing_sql_session'
elif mode=='dhan':
    mod=importlib.import_module('broker.dhan_sandbox.streaming.dhan_websocket');del mod.random
    selection='test_dhan_reconnect_failure_reaches_bounded_backoff'
elif mode=='pocketful':
    mod=importlib.import_module('broker.pocketful.api.pocketfulwebsocket')
    mod.PocketfulSocket._set_updates_subscription=lambda *a:True
    selection='test_pocketful_updates_use_real_socket_and_shared_channel'
elif mode=='scheduler':
    original=Path.read_text
    def without_barrier(p,*a,**k):
        text=original(p,*a,**k)
        if p.name in ('flow_scheduler_service.py','historify_scheduler_service.py'):
            return text.replace('            scheduler.get_jobs()\n','')
        return text
    Path.read_text=without_barrier
    selection='test_persistent_shutdown_waits_for_dispatch_bookkeeping'
else:raise ValueError(mode)
file='test/test_scheduler_shutdown_lifecycle.py' if mode=='scheduler' else 'test/test_oct8_runtime_regressions.py'
result=pytest.main([file+'::'+selection,'--import-mode=importlib','-q'])
if result!=1:raise SystemExit('Mutation did not produce the expected assertion failure: '+str(result))
print('Expected failing regression confirmed: '+mode)
