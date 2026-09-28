"""Mutation proof for daily entry guard; measured DuckDB resource lifecycle."""

import json

import duckdb
import numpy as np
import psutil
from engine import indicators, replay
from run import HERE
from test_engine import fixture


def main():
    raw = fixture()
    raw[100, 1:5] = [101, 110, 101, 108]
    raw[101, 1:5] = [107, 115, 98, 104]
    args = (raw, indicators(raw), np.ones(len(raw), dtype=np.bool_), 905, 1)
    assert len(replay(*args)) == 1
    text = (HERE / "engine.py").read_text(encoding="utf-8")
    assert text.count("active = used = True") == 1
    text = text.replace("active = used = True", "active = True")
    # No filesystem/module cache for the mutation; execute pure Python functions.
    text = text.replace("@njit(cache=True, nogil=True)", "").replace("@njit(cache=True)", "")
    namespace = {"__name__": "guard_mutation"}
    exec(compile(text, "guard_mutation", "exec"), namespace)
    assert len(namespace["replay"](*args)) == 2, "Neutering the guard must violate the test"
    process = psutil.Process()
    samples = []
    parquet = HERE / "output/candles/SBIN.parquet"
    for i in range(121):
        try:
            with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as db:
                db.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet)]).fetchone()
                if i % 2:
                    raise RuntimeError("Exercise exception cleanup")
        except RuntimeError:
            pass
        if i in [20, 70, 120]:
            samples.append(
                {
                    "cycles": i,
                    "handles": process.num_handles(),
                    "rss_bytes": process.memory_info().rss,
                }
            )
    assert samples[-1]["handles"] <= samples[0]["handles"] + 2
    result = {
        "daily_guard_mutation": "PASS: 1 correct trade becomes 2 with guard disabled",
        "duckdb_success_exception_cycles": 121,
        "resource_samples": samples,
        "memory_scope": "One symbol per worker, four workers; all handles and executor context-managed. RSS is measured, not a universal leak-free guarantee.",
    }
    (HERE / "artifacts/resource-and-mutation.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
