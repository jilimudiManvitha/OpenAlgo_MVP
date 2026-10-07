"""Prove the new runtime test rejects the original crash, without editing source."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import pytest
from strategies.nifty_options import runtime

original = subprocess.check_output(
    ["git", "show", "HEAD:strategies/nifty_options/runtime.py"], cwd=ROOT, text=True
)
exec(compile(original, "<original-runtime>", "exec"), runtime.__dict__)
result = pytest.main([
    "test/test_nifty_options_runtime.py", "-q", "--tb=short",
    "-k", "scheduled_runner and premium_positional_next_week",
])
if result != pytest.ExitCode.TESTS_FAILED:
    raise SystemExit("Regression test did not reject the original runtime")
print("Verified: original runtime fails the new recovery regression; working tree unchanged.")
