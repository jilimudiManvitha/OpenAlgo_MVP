"""Run actual regression tests with deliberate in-memory defects; never edit runtime files."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
mutation = sys.argv[1]


class Defect:
    def pytest_runtest_call(self, item):
        m = item.funcargs["modules"]
        if mutation == "mixed":
            m.report.ORDER_TYPES = m.report.ORDER_TYPES | {"HISTORY"}
        elif mutation == "last_http":

            def replace(self, start, end):
                self.http_seconds = max(0, end - start)
                self.http_calls += 1

            m.monitor.LatencyTracker.record_http = replace
        elif mutation == "recent_100":
            original = m.report.summary
            m.report.summary = lambda rows: original(rows[-100:])


test = {
    "mixed": "test_orders_and_legacy_aliases_exclude_reads_and_fast_failures",
    "last_http": "test_http_multiple_calls_accumulate_and_helper_does_not_double_count",
    "recent_100": "test_one_snapshot_distribution_is_not_recent_100",
}[mutation]
code = pytest.main(
    ["--import-mode=importlib", "-q", "test/test_latency_isolated.py::" + test], plugins=[Defect()]
)
if code != 1:
    raise SystemExit("Mutation did not produce an assertion failure: " + str(code))
print("Expected failure confirmed:", mutation)
