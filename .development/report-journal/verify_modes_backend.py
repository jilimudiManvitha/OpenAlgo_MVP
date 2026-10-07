"""Isolated API resource repetition and mutation proofs. No production app import."""
import gc
import inspect
import json
import runpy
import sys
import tempfile
import tracemalloc
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
runpy.run_path(str(ROOT/'test/conftest.py'))
import psutil
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from test import test_investment_api as api, test_investment_ledger as ledger, test_investment_modes as tests
from services import investment_mode as mode, investment_execution as execution

with tempfile.TemporaryDirectory(dir=ROOT/'log/test') as tmp, pytest.MonkeyPatch.context() as patch:
    fixture=ledger.ledger.__wrapped__(Path(tmp),patch)
    db=next(fixture)
    client=api.client.__wrapped__(db,patch)
    tests.seed('paper');tests.seed('live')
    state={'paper':True}
    patch.setattr(mode,'get_analyze_mode',lambda:state['paper'])
    def reads(count):
        for i in range(count):
            state['paper']=i%2==0
            response=client.get('/investments/api/dashboard')
            assert response.status_code==200,response.json
            assert response.json['data']['invested']=='300.0000'
            assert len(response.json['data']['holdings'])==1
    reads(30)
    gc.collect();process=psutil.Process();before=process.num_fds()
    tracemalloc.start();start=tracemalloc.get_traced_memory()[0]
    reads(200)
    gc.collect();growth=tracemalloc.get_traced_memory()[0]-start;after=process.num_fds()
    assert before==after,(before,after)
    assert growth<1_000_000,growth
    fixture.close()
    print(json.dumps({'api_requests':200,'fds_before':before,'fds_after':after,'retained_bytes':growth}))

caught=[]
for name in ('mode partition','mode assertion','duplicate dispatch'):
    with tempfile.TemporaryDirectory(dir=ROOT/'log/test') as tmp, pytest.MonkeyPatch.context() as patch:
        fixture=ledger.ledger.__wrapped__(Path(tmp),patch);db=next(fixture)
        client=api.client.__wrapped__(db,patch)
        try:
            if name=='mode partition':
                event.remove(Session,'do_orm_execute',mode.filter_ledger)
                try:
                    tests.test_partition_reads_and_direct_id_writes(client,patch)
                finally:
                    event.listen(Session,'do_orm_execute',mode.filter_ledger)
            elif name=='mode assertion':
                source=inspect.getsource(mode.begin_request)
                mutant=source.replace('expected is not None and expected != mode','False')
                assert mutant!=source
                namespace=dict(vars(mode));exec(mutant,namespace)
                client.application.before_request_funcs['investments'][0]=namespace['begin_request']
                tests.test_stale_mode_broker_and_account_relabelling(client,patch)
            else:
                boundary=tests.broker_boundary.__wrapped__(client,patch)
                source=inspect.getsource(execution.submit)
                mutant=source.replace('key = payload.get("request_key", "")','key = __import__("uuid").uuid4().hex')
                assert mutant!=source
                namespace=dict(vars(execution));exec(mutant,namespace)
                patch.setattr(execution,'submit',namespace['submit'])
                tests.test_pinned_dispatch_idempotency_and_history(client,patch,boundary,'paper','order')
        except AssertionError:
            if name=='duplicate dispatch':
                assert len(boundary)==2, 'Mutation did not reach two dispatches'
            caught.append(name)
        else:
            raise AssertionError(f'Mutation survived: {name}')
        finally:
            fixture.close()
print(json.dumps({'mutation_tests_caught':caught}))
