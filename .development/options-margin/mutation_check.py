"""In-memory mutation: prove the owner isolation test observes the query guard."""
import inspect
import runpy
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
runpy.run_path(str(root/'test/conftest.py'))
from services import options_capital as capital
source=inspect.getsource(capital.read_states)
needle='SELECT strategy,payload,updated_at FROM states WHERE owner=?'
assert source.count(needle)==1
source=source.replace(needle,'SELECT strategy,payload,updated_at FROM states WHERE ? IS NOT NULL')
exec(compile(source,'<mutation-owner-filter>','exec'),capital.__dict__)
import pytest
result=pytest.main(['--import-mode=importlib','test/test_options_capital.py::test_overview_readonly_budget_charges_and_owner','-q'])
if result != 1: raise SystemExit('Mutation was not detected')
print('Owner-filter mutation detected as expected; no source files changed.')
