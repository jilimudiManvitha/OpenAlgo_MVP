"""No-order verification of regression sensitivity and repeated state cleanup."""

import gc
import inspect
import json
import tempfile
from pathlib import Path

import psutil

from strategies.top_gain_volumes.coordination import dispatch_lock

from . import engine
from .history import atomic_json
from .profiles import BACKTEST_ROOT
from .state import StateConflict, Store


def main():
    from test import test_nifty_options_strategies as cases

    original = cases.decision
    source = inspect.getsource(engine.decision)
    target = 'and (profile.positional or day == state["last_entry_day"])'
    assert source.count(target) == 1
    namespace = dict(engine.__dict__)
    exec(
        compile(source.replace(target, "and True"), "<in-memory-reentry-mutation>", "exec"),
        namespace,
    )
    try:
        cases.decision = namespace["decision"]
        try:
            cases.test_unfilled_adjustment_cannot_strand_next_cycle("intraday")
        except AssertionError:
            reentry_mutation_detected = True
        else:
            raise RuntimeError("Reentry regression did not detect a disabled guard")
    finally:
        cases.decision = original
    for holding in ("intraday", "positional"):
        cases.test_unfilled_adjustment_cannot_strand_next_cycle(holding)
    with tempfile.TemporaryDirectory(prefix="nifty-options-verify-") as directory:
        directory = Path(directory)
        store = Store(directory / "state.db")
        revision = 0
        process = psutil.Process()
        baseline = process.num_fds()
        for i in range(200):
            with dispatch_lock(directory / "dispatch.lock"):
                revision = store.save("test", "variant", revision, {"iteration": i})
                assert store.load("test", "variant") == (revision, {"iteration": i})
                try:
                    store.save("test", "variant", revision - 1, {})
                except StateConflict:
                    pass
                else:
                    raise RuntimeError("Revision guard failed")
            try:
                with dispatch_lock(directory / "dispatch.lock"):
                    raise ValueError("exercise exception cleanup")
            except ValueError:
                pass
        gc.collect()
        final = process.num_fds()
        if final != baseline:
            raise RuntimeError(f"Descriptor growth: {baseline} -> {final}")
    result = {
        "reentry_mutation_detected": reentry_mutation_detected,
        "restored_tests_passed": True,
        "state_and_lock_cycles": 200,
        "fd_before": baseline,
        "fd_after": final,
        "scope": "Measured SQLite success/conflict and lock success/error paths; static bounded queue/cache review. Not a live market soak.",
    }
    atomic_json(BACKTEST_ROOT / "verification/local_checks.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
