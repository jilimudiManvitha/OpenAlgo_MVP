"""Inspect one missing history response without exposing authentication or changing caches."""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".development/options-year"))
from setup import setup

OUT = ROOT / "backtesting/nifty_options/2026-04-08_2026-07-07"
setup(out=OUT, private_dir=ROOT / "log/test/options-previous-quarter/diagnostic-private")
from strategies.nifty_options import history as h
from strategies.nifty_options.data_probe import active_login
from services.expired_data_service import get_expired_data
from utils.httpx_client import cleanup_httpx_client

manifest = json.loads((OUT / "manifest.json").read_text())
c = next(c for c in manifest["contracts"] if not h.existing_cache_file(c["symbol"], c["start"], c["end"]).exists())
_, token = active_login()
try:
    ok, result, status = get_expired_data("history", dict(broker_symbol=c["symbol"], interval="1m", start_date=c["start"], end_date=c["end"], include_oi=True), auth_token=token, broker="fyers")
    code = result.get("code")
    report = dict(contract=c, ok=ok, http_status=status, code=code if isinstance(code, (int, float)) else None,
                  invalid_response=result.get("message") == "FYERS returned an invalid expired-data response.",
                  rows=len(result.get("data", {}).get("candles", [])))
    print(json.dumps(report, indent=2))
    if report["invalid_response"]:
        from broker.fyers.api.expired_data import BrokerExpiredData

        raw = BrokerExpiredData(token)._request("historical-data", dict(symbol=c["symbol"], resolution="1", date_format=1, range_from=c["start"], range_to=c["end"], include_oi=1))
        # Store market-data fields only; never request headers or authentication.
        fields = {key: raw.get(key) for key in ("s", "symbol", "resolution", "schema_version", "columns", "candles")}
        (ROOT / "log/test/options-previous-quarter/invalid-market-data.json").write_text(json.dumps(fields))
        candles = fields.get("candles") or []
        invalid = [r for r in candles if isinstance(r, list) and len(r) >= 5 and all(isinstance(v, (float, int)) for v in r)
                   and (any(not math.isfinite(v) for v in r) or min(r[1:]) < 0 or r[3] > min(r[1], r[4]) or r[2] < max(r[1], r[4]))]
        print(json.dumps(dict(schema_version=fields["schema_version"], columns=fields["columns"], rows=len(candles), invalid_rows=invalid[:10], invalid_row_count=len(invalid)), indent=2))
finally:
    cleanup_httpx_client()
