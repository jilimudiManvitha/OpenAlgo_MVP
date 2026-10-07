"""Repeat success/error DB paths in a disposable test DB; measure this process only."""
import gc
import json
import os
import runpy
import sys
import tracemalloc
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "test/conftest.py"))
os.environ["DATABASE_URL"] = "sqlite:///log/test/investment-resources.db"
import psutil
from database import investment_db as db
from services import investment_service as s, investment_reports as reports, investment_watchlists as watches

db.Base.metadata.drop_all(db.engine)  # Explicitly disposable test database only.
db.Base.metadata.create_all(db.engine)
account = s.save_account("resource-fixture", {"name": "Resource audit"})
asset = s.save_asset("resource-fixture", {"account_id": account["id"], "symbol": "FIXTURE"})
s.set_price("resource-fixture", asset["id"], "100", datetime(2026, 10, 1))
watch = watches.save("resource-fixture", {"name": "Audit", "category": "Other"})
watches.save_item("resource-fixture", watch["id"], {"asset_id": asset["id"]})

def cycle():
    reports.build("resource-fixture", "performance")
    watches.lists("resource-fixture")
    s.dashboard("resource-fixture")
    try:
        reports.import_prices("resource-fixture", "symbol,scheme_code,price,as_of\nUNKNOWN,,1,2026-10-01T00:00:00Z")
    except s.InvestmentError:
        pass
    else:
        raise AssertionError("Error path did not execute")
    assert not s.db_session.registry.has(), "Session retained after request"

process = psutil.Process()
tracemalloc.start()
samples = []
for batch in range(3):
    for _ in range(100):
        cycle()
    gc.collect()
    samples.append({"iterations": (batch + 1) * 100, "fds": process.num_fds(), "traced_bytes": tracemalloc.get_traced_memory()[0]})
tracemalloc.stop()
assert len({sample["fds"] for sample in samples}) == 1, samples
result = {"passed": True, "samples": samples, "scope": "300 mixed report/watch/dashboard/error cycles; no broker, order or production DB access"}
(ROOT / ".development/investment/artifacts/resources.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
db.db_session.remove()
db.engine.dispose()
