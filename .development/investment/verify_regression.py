"""Prove the actual ownership test detects a removed owner predicate (isolated DB)."""
import inspect
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'test/conftest.py'))
import pytest
from services import investment_service as service

original = service.owned
source = inspect.getsource(original)
needle = 'model.id == identifier(record_id), model.user_id == user'
assert needle in source
namespace = vars(service).copy()
exec(compile(source.replace(needle, 'model.id == identifier(record_id)'), '<ownership-regression-probe>', 'exec'), namespace)
service.owned = namespace['owned']
try:
    status = pytest.main(['test/test_investment_ledger.py::test_all_owned_mutations_and_reads_refuse_other_user', '-q'])
    if status != 1:
        raise SystemExit(f'Expected ownership test failure; got {status}')
    print('PASS: the real ownership test detects owner-filter removal; source never changed')
finally:
    service.owned = original
