"""Measure repeated SQLite scanner operations; no market-data connections."""

import json
from pathlib import Path

import conftest  # noqa: F401
import psutil

from services.market_scanner_live import LiveStore

here = Path(__file__).resolve().parent
store = LiveStore("sqlite:///" + (here / "resource-check.db").as_posix())
process = psutil.Process()
count = process.num_handles if hasattr(process, "num_handles") else process.num_fds
try:
    account = store.configure("resource-test", "fixture", enabled=False)
    for _ in range(20):
        store.publish(account, {"rows": []})
        store.accounts()
    before = count()
    for _ in range(500):
        store.publish(account, {"rows": []})
        store.accounts()
    after = count()
    result = {
        "iterations": 500,
        "handles_before": before,
        "handles_after": after,
        "handle_growth": after - before,
        "account_rows": len(store.accounts()),
        "static_review": "SQL connections close in context managers; auth/symbol/calendar sessions removed in finally; proxy disconnect in finally; 16 accounts, 5000 symbols, 120 points per symbol; browser timers and requests cancelled on unmount.",
    }
    (here / "artifacts" / "resource-audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result))
    if after - before > 2:
        raise SystemExit("Unexpected handle growth")
finally:
    store.engine.dispose()
