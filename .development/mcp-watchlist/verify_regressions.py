"""Prove the ownership regression test fails if its actual owner filter is removed."""

import inspect
import runpy
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "test/conftest.py"))

import pytest

from services import watchlist_service as service

original = service._operate
source = textwrap.dedent(inspect.getsource(original))
guard = "session.query(Watchlist).filter_by(user_id=user)"
assert source.count(guard) == 1
try:
    exec(
        compile(source.replace(guard, "session.query(Watchlist)"), "<owner-regression>", "exec"),
        service.__dict__,
    )
    status = pytest.main(
        [
            "-q",
            "--tb=short",
            "test/test_watchlist_api_mcp.py::test_names_and_ownership_are_enforced",
        ]
    )
finally:
    service._operate = original
if status != pytest.ExitCode.TESTS_FAILED:
    raise SystemExit("Ownership regression was not detected")
print("Verified: removing the owner filter makes the regression fail; source unchanged.")
