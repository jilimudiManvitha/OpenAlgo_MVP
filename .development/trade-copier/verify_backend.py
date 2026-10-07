"""Offline resource measurement and targeted mutation proofs; no source edits."""
import gc
import inspect
import json
import runpy
import subprocess
import sys
import tempfile
import textwrap
import time
import tracemalloc
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
runpy.run_path(str(ROOT/'test/conftest.py'))
from services.trade_copier import engine as module
from test.test_trade_copier import Engine, Fake, add, arm, event, ingest, settled

mutations={
 'loss_gate':('_risk','if snapshot[1]["pnl"] <= -p["max_daily_loss"]:','if False:', 'test_loss_limit_and_mode_flip'),
 'owner_partition':('snapshot','m.Account.owner == owner, m.Account.mode == mode','m.Account.mode == mode','test_secrets_encrypted_and_owner_mode_isolation'),
 'fill_delta':('ingest','qty = target - cursor.target','qty = target','test_partial_fill_duplicate_concurrent_and_regressive'),
}
if len(sys.argv)>1:
    method,old,new,test=mutations[sys.argv[1]]
    source=textwrap.dedent(inspect.getsource(getattr(Engine,method)))
    assert source.count(old)==1,(method,source.count(old))
    namespace=dict(vars(module));exec(compile(source.replace(old,new),'<mutated-copier>','exec'),namespace)
    setattr(Engine,method,namespace[method])
    import pytest
    raise SystemExit(pytest.main(['-q','--tb=short',f'test/test_trade_copier.py::{test}']))

import psutil
from cryptography.fernet import Fernet
vault=Fernet(Fernet.generate_key())
fakes={}
with tempfile.TemporaryDirectory(dir=ROOT/'log/test',prefix='copier-resource-') as td:
    e=Engine('sqlite:///'+td+'/copier.db',lambda s:vault.encrypt(s.encode()).decode(),lambda s:vault.decrypt(s.encode()).decode(),
             lambda *_:([],['MASTER']),lambda *_:True,lambda *_:dict(lot=1,price=100),transport=lambda a:fakes.setdefault(a.id,Fake(a.client_id)))
    try:
        add(e);arm(e);ingest(e);settled(e)
        for _ in range(20):e.snapshot('owner','paper','fyers')
        proc=psutil.Process();gc.collect();before=proc.num_fds()
        tracemalloc.start();mem_before=tracemalloc.get_traced_memory()[0]
        for _ in range(300):
            ingest(e) # exact replay: zero new submits or growing state
            e.snapshot('owner','paper','fyers')
        gc.collect();mem_after,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        after=proc.num_fds()
        assert after==before,(before,after)
        assert sum(len(f.calls) for f in fakes.values())==1
        result={'snapshot_and_duplicate_iterations':300,'fd_before':before,'fd_after':after,'retained_bytes_delta':mem_after-mem_before,'peak_bytes':peak}
    finally:e.close()
for name in mutations:
    p=subprocess.run([sys.executable,__file__,name],cwd=ROOT,capture_output=True,text=True)
    (ROOT/f'log/test/copier-mutation-{name}.log').write_text(p.stdout+p.stderr)
    assert p.returncode==1 and '1 failed' in p.stdout,(name,p.returncode,p.stdout[-2000:])
    result[name]='expected test failure observed'
(ROOT/'.development/trade-copier/verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
