"""CSV diagnosis and isolated read-path resource checks. No production DB access."""

import csv
import gc
import hashlib
import json
import os
import runpy
import statistics
import sys
import tracemalloc
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "test/conftest.py"))
os.environ["LATENCY_DATABASE_URL"] = "sqlite:///" + str(ROOT / "log/test/latency/browser.db")
from services import latency_report as report
import psutil

with (ROOT / "Latency Logs.csv").open(newline="") as stream:
    rows = list(csv.DictReader(stream))
groups = defaultdict(list)
for row in rows:
    groups[row["Order Type"]].append(row)
analysis = {
    "rows": len(rows),
    "status": dict(Counter(r["Status"] for r in rows)),
    "newest_ist": rows[0]["Date & Time (IST)"],
    "oldest_ist": rows[-1]["Date & Time (IST)"],
    "order_actions": sum(r["Order Type"] in report.ORDER_TYPES for r in rows),
    "order_successes": sum(
        r["Order Type"] in report.ORDER_TYPES and r["Status"] == "SUCCESS" for r in rows
    ),
    "auth_failures": sum(
        r["Status"] != "SUCCESS"
        and ("api key" in r["Error (if any)"].lower() or "apikey" in r["Error (if any)"].lower())
        for r in rows
    ),
    "operations": {},
    "failure_reasons": dict(Counter(r["Error (if any)"] for r in rows if r["Status"] != "SUCCESS")),
}
for op, values in groups.items():
    nums = [float(r["Total Latency (ms)"]) for r in values]
    analysis["operations"][op] = {
        "count": len(values),
        "avg_ms": statistics.mean(nums),
        "p50_ms": statistics.median(nums),
        "max_ms": max(nums),
        "recorded_http_avg_ms": statistics.mean(
            float(r["Broker Confirmation (ms)"]) for r in values
        ),
        "recorded_other_avg_ms": statistics.mean(
            float(r["Platform Overhead (ms)"]) for r in values
        ),
    }
selected = report.filters({"period": "all", "kind": "all"})
for _ in range(10):
    report.snapshot(selected)
process = psutil.Process()
gc.collect()
before = process.num_fds()
tracemalloc.start()
base = tracemalloc.take_snapshot()
for _ in range(150):
    report.snapshot(selected)
gc.collect()
after = process.num_fds()
end = tracemalloc.take_snapshot()
analysis["resources"] = {
    "iterations": 150,
    "fd_before": before,
    "fd_after": after,
    "retained_bytes": sum(s.size_diff for s in end.compare_to(base, "filename")),
}
assert after == before
tracemalloc.stop()
(ROOT / "log/test/oct8-project/latency-resource-audit.json").write_text(json.dumps(analysis, indent=2))
print(json.dumps(analysis["resources"]))
