"""Resource repetition and in-memory mutation checks using synthetic databases."""
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
from services import report_journal as service
from test import test_report_journal as tests

with tempfile.TemporaryDirectory(dir=ROOT/'log/test') as temp:
    db=tests.saved.__wrapped__(Path(temp))
    process=psutil.Process()
    for _ in range(10): service.journal('alice',2026,path=db)
    gc.collect()
    fds=process.num_fds()
    tracemalloc.start()
    initial=tracemalloc.get_traced_memory()[0]
    for _ in range(150): service.journal('alice',2026,path=db)
    gc.collect()
    final_fds=process.num_fds()
    growth=tracemalloc.get_traced_memory()[0]-initial
    assert final_fds==fds,(fds,final_fds)
    assert growth<100_000,growth
    source=inspect.getsource(service)
    mutations={
        'owner isolation':source.replace('WHERE owner=? AND day>=?', 'WHERE ? IS NOT NULL AND day>=?'),
        'simultaneous capital':source.replace('    return result\n', '    result["peak_capital"] = sum(t["entry"] * t["quantity"] for t in trades)\n    return result\n'),
    }
    caught=[]
    for name,mutant in mutations.items():
        assert mutant!=source
        namespace={}
        exec(compile(mutant,'<mutation>','exec'),namespace)
        original=tests.journal
        tests.journal=namespace['journal']
        try:
            try:
                if name=='owner isolation': tests.test_owner_filter_and_stock_calendar(db)
                else: tests.test_combined_arithmetic_and_three_stock_entries(db)
            except AssertionError: caught.append(name)
            else: raise AssertionError(f'Mutation survived: {name}')
        finally: tests.journal=original
    print(json.dumps({'requests':150,'fds_before':fds,'fds_after':final_fds,'retained_growth_bytes':growth,'mutations_caught':caught}))

from services import report_brokerage as fees
from test import test_report_brokerage as fee_tests
fee_source=inspect.getsource(fees)
fee_mutations={
    'GST included': (fee_source.replace('values["gst"] = 0.18', 'values["gst"] = 0.0'),fee_tests.test_fyers_exact_example_and_net_after_all_costs),
    'actual fee precedence': (fee_source.replace('if t.get("fees_actual") is True:', 'if False:'),fee_tests.test_actual_fees_override_estimates_without_double_deduction),
    'broker snapshot precedence': (fee_source.replace('context = report.get("brokerage_context") or {}', 'context = {}'),fee_tests.test_broker_snapshot_survives_login_and_tariff_changes),
}
fee_caught=[]
for name,(mutant,check) in fee_mutations.items():
    assert mutant!=fee_source
    namespace={};exec(compile(mutant,'<fee-mutation>','exec'),namespace)
    original=fee_tests.estimate_report;fee_tests.estimate_report=namespace['estimate_report']
    try:
        try: check()
        except AssertionError: fee_caught.append(name)
        else: raise AssertionError(f'Mutation survived: {name}')
    finally: fee_tests.estimate_report=original
print(json.dumps({'fee_mutations_caught':fee_caught}))
