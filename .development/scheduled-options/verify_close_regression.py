"""Disable the closing guards in memory; leave all source and user data intact."""

import inspect
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest

import test.conftest  # noqa: F401 — isolate before importing application modules

mode = sys.argv[1]
if mode == "quantity":
    from sandbox import position_manager

    source = textwrap.dedent(inspect.getsource(position_manager.PositionManager.close_position))
    assert source.count("if position.quantity == 0:") == 1
    scope = position_manager.__dict__
    exec(
        compile(source.replace("if position.quantity == 0:", "if False:"), "<old-close>", "exec"),
        scope,
    )
    position_manager.PositionManager.close_position = scope["close_position"]
    target = "test/test_scheduled_session_close.py::test_squareoff_does_not_submit_an_order_for_an_already_closed_position[0]"
elif mode == "grace":
    from blueprints import python_strategy

    python_strategy.strategy_shutdown_timeout = lambda _: 5
    target = "test/test_scheduled_session_close.py::test_scheduler_passes_sufficient_grace_through_every_stop_path[popen-Nifty500_Scanner_Fixed_3R_10K_5m.py]"
elif mode == "report":
    from strategies.top_gain_volumes import runtime

    original = runtime.stopping_phase
    runtime.stopping_phase = lambda report, now, clock, deadline, persist: original(
        report, now, clock, deadline, lambda: None
    )
    target = "test/test_scheduled_session_close.py::test_stopping_snapshot_is_durable_before_slow_batch_and_deadline_does_not_extend"
else:
    raise SystemExit("Choose quantity, grace or report")


class Failures:
    failures = []

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failures.append(report)


capture = Failures()
status = pytest.main([target, "-q", "--tb=short"], plugins=[capture])
assert status == pytest.ExitCode.TESTS_FAILED
assert len(capture.failures) == 1 and capture.failures[0].when == "call"
expected = {
    "quantity": 'assert response.get("already_closed")',
    "grace": "assert timeout ==",
    "report": "assert saved is not None",
}[mode]
assert expected in capture.failures[0].longreprtext
print(f"Verified {mode}: actual regression rejects disabled guard; source unchanged.")
