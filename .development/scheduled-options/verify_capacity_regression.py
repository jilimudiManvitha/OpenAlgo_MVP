"""Fault injection in memory only, after loading the normal pytest isolation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest

import test.conftest  # noqa: F401 — isolation before any application import
from services import market_scanner_feed
from strategies.nifty_options import runtime

mode = sys.argv[1]
if mode == "capacity":
    market_scanner_feed.stream_limit = lambda broker: 5000
    target = "test/test_scheduled_option_capacity.py::test_scanner_and_all_twelve_profiles_fit_real_shared_pool"
elif mode == "chain":
    runtime.required_contracts = lambda contracts, *_: contracts
    target = "test/test_nifty_options_runtime.py::test_scheduled_runner_survives_subscription_failure_and_writes_report[premium_positional_next_week]"
elif mode == "stagger":
    runtime.connection_delay = lambda *_args, **_kwargs: 0
    target = "test/test_nifty_options_runtime.py::test_scheduled_runner_survives_subscription_failure_and_writes_report[premium_positional_next_week]"
else:
    raise SystemExit("Choose capacity, chain, or stagger")


class Failures:
    failures = []

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failures.append(report)


capture = Failures()
status = pytest.main([target, "-q", "--tb=short"], plugins=[capture])
assert status == pytest.ExitCode.TESTS_FAILED
assert len(capture.failures) == 1
failure = capture.failures[0]
assert failure.when == "call" and "AssertionError" in failure.longreprtext
print(f"Verified {mode}: the actual test rejects the disabled fix; source unchanged.")
