"""Prove the regression checks detect bypassed guards; in-memory edits only."""
import inspect
import runpy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));runpy.run_path(str(ROOT/'test/conftest.py'))
import pytest
if sys.argv[1]=='cooldown':
 from broker.fyers.api import data_budget as module
 source=inspect.getsource(module.acquire)
 needle='if state["cooldown"] > now:'
 assert source.count(needle)==1
 exec(source.replace(needle,'if False:'),module.__dict__)
 target='test/test_fyers_data_budget.py::test_429_prevents_other_symbol_requests'
else:
 from strategies.nifty_options import runtime as module
 source=inspect.getsource(module.prepare_opening)
 needle='if full_margin["sizing_requirement"] > profile.capital * 0.90:'
 assert source.count(needle)==1
 exec(source.replace(needle,'if False:'),module.__dict__)
 target='test/test_options_capital.py::test_full_basket_over_budget_rejected_before_intent'
code=pytest.main(['--import-mode=importlib',target,'-q'])
assert code==1,'Mutation was not detected'
print('Guard mutation detected; no source files changed.')
