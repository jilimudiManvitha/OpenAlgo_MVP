"""Start/stop the authorized main app; no login or broker order requests."""
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'log/test/oct8-project'
def port_open(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1',port))==0
assert not any(port_open(p) for p in (5000,8765)), 'Another app owns a production port'
config=ROOT/'strategies/strategy_configs.json'
before=json.loads(config.read_text())
assert len(before)==28 and not any(c.get('is_running') for c in before.values())
result={'before_schedule_hash':hashlib.sha256(config.read_bytes()).hexdigest(),'routes':{}}
with (OUT/'app-startup.log').open('w') as log:
    child=subprocess.Popen([str(ROOT/'.venv/bin/python'),'app.py'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'FLASK_DEBUG':'False'})
    result['owned_pid']=child.pid
    try:
        for _ in range(120):
            if child.poll() is not None:raise RuntimeError('Main app exited during startup')
            if port_open(5000) and port_open(8765):break
            time.sleep(.5)
        else:raise RuntimeError('Main application ports did not start')
        for path in ('/','/auth/login','/auth/session-status','/auth/csrf-token'):
            with urllib.request.urlopen('http://127.0.0.1:5000'+path,timeout=15) as response:
                result['routes'][path]={'status':response.status,'content_type':response.headers.get('Content-Type')}
                response.read()
        time.sleep(15)
        assert child.poll() is None
        result['ports_while_running']={str(p):port_open(p) for p in (5000,8765)}
    finally:
        child.send_signal(signal.SIGINT)
        try:result['exit_code']=child.wait(timeout=45)
        except subprocess.TimeoutExpired:
            child.terminate();result['exit_code']=child.wait(timeout=15)
            result['needed_terminate']=True
        result['ports_after_stop']={str(p):port_open(p) for p in (5000,8765)}
        after=json.loads(config.read_text())
        result['schedules_equal']=after==before
        result['after_schedule_hash']=hashlib.sha256(config.read_bytes()).hexdigest()
        (OUT/'app-smoke.json').write_text(json.dumps(result,indent=2))
assert result['schedules_equal'] and not any(result['ports_after_stop'].values())
print(json.dumps(result,indent=2))
