"""Prove the chunk boundary test detects a real regression without source edits."""

import inspect
import runpy
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "test" / "conftest.py"))

import pytest

from broker.fyers.api.expired_data import BrokerExpiredData

original = BrokerExpiredData.get_history
source = textwrap.dedent(inspect.getsource(original))
assert source.count("timedelta(days=99)") == 1
namespace = dict(original.__globals__)
exec(
    compile(
        source.replace("timedelta(days=99)", "timedelta(days=100)"), "<chunk-regression>", "exec"
    ),
    namespace,
)
BrokerExpiredData.get_history = namespace["get_history"]
try:
    status = pytest.main(
        [
            "-q",
            "--tb=short",
            "test/test_expired_fno_data.py::test_history_windows_are_inclusive_nonoverlapping_and_bounded",
        ]
    )
finally:
    BrokerExpiredData.get_history = original
if status != pytest.ExitCode.TESTS_FAILED:
    raise SystemExit("Mutation check failed: the 101-day regression was not detected")
print(
    "Verified: injecting a 101-day request makes the regression fail; original restored in memory."
)
