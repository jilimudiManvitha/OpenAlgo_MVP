"""In-memory fault injection: prove split/idempotency tests catch broken guards."""
import inspect
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "test/conftest.py"))
import pytest
from services import investment_paper as paper
from services import investment_service as service

case = sys.argv[1]
if case == "split":
    service.valuation_matches_units = lambda *_: True
    test = "test_split_requires_a_price_in_post_split_units"
elif case == "idempotency":
    source = inspect.getsource(paper.place)
    needle = "        if existing:\n"
    assert source.count(needle) == 1
    namespace = vars(paper).copy()
    exec(compile(source.replace(needle, "        if False:\n"), "<idempotency-regression-probe>", "exec"), namespace)
    paper.place = namespace["place"]
    test = "test_paper_crash_recovery_never_resubmits_and_imports_once"
else:
    raise SystemExit("Choose split or idempotency")
status = pytest.main([f"test/test_investment_extensions.py::{test}", "-q"])
if status != 1:
    raise SystemExit(f"Expected assertion failure; got {status}")
print(f"PASS: {case} regression detected; source files never changed")
