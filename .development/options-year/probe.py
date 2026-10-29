import json, time
from datetime import date
from setup import ROOT, OUT, setup

setup()
from strategies.nifty_options import history as h
from strategies.nifty_options.data_probe import active_login, expired_call
from broker.fyers.api import data_budget

_, token = active_login()
start = date(2025, 10, 9)
end = date(2026, 10, 8)
m = h.discover(token, start, end, OUT)
missing = sum(
    not h.existing_cache_file(c["symbol"], c["start"], c["end"]).exists() for c in m["contracts"]
)
state = data_budget.read(data_budget.state_path(), time.time())
limit = data_budget.PLANS[data_budget.plan()][2]
first = [c for c in m["contracts"] if c["start"] == str(start)]
# Probe an actual listed near-ATM historical contract; no guessed expiry symbol.
c = min((c for c in first if c["kind"] == "CE"), key=lambda c: abs(c["strike"] - 25000))
p = h.cache_file(c["symbol"], c["start"], c["end"])
if not p.exists():
    d = expired_call(
        token,
        "history",
        {
            "broker_symbol": c["symbol"],
            "interval": "1m",
            "start_date": c["start"],
            "end_date": c["end"],
            "include_oi": True,
        },
    )
    h.validate_rows(d["candles"])
    h.write_candles(p, d)
else:
    d = h.read_candles(p)
result = {
    "start": str(start),
    "end": str(end),
    "contracts": len(m["contracts"]),
    "exact_cache_missing": missing,
    "plan": data_budget.plan(),
    "data_budget_used": state["count"],
    "daily_budget_limit": limit,
    "oldest_probe": {
        "symbol": c["symbol"],
        "rows": len(d["candles"]),
        "first": d["candles"][0]["timestamp"] if d["candles"] else None,
    },
}
h.atomic_json(OUT / "coverage_probe.json", result)
print(json.dumps(result, indent=2))
