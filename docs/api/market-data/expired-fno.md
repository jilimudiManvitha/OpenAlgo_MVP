# Expired futures and options data

Three authenticated, data-only endpoints implement expired-contract discovery
and history. FYERS is the first supported provider; other brokers return HTTP
501 until they implement this capability. Sandbox mode uses real market data.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/expired/expiry-dates` | Historical futures/options expiries |
| POST | `/api/v1/expired/contracts` | Expired contracts for an expiry |
| POST | `/api/v1/expired/history` | Intraday candles and optional OI |

Send the OpenAlgo API key in `apikey`. The server resolves the associated
broker login; do not send broker credentials. Restart OpenAlgo after installing
this code to register the new routes.

## Discover expiries and contracts

Expiry request:

```json
{
  "apikey": "<OPENALGO_API_KEY>",
  "symbol": "SBIN",
  "exchange": "NSE",
  "start_date": "2025-01-01",
  "end_date": "2025-03-31"
}
```

`symbol` and `exchange` use OpenAlgo format, e.g. `NIFTY` and `NSE_INDEX`.
Alternatively, replace **both** with `broker_symbol`, e.g. `NSE:SBIN-EQ`,
`NSE:NIFTY50-INDEX` or `BSE:SENSEX-INDEX`. This supports underlyings absent
from today's master. Providing both identifier forms is an error.

Success returns `{"status":"success","broker":"fyers","data":{...}}`.
The `data` object contains `broker_symbol`, `start_date`, `end_date`, and:

```json
{
  "expiry_dates": {
    "futures": ["2025-01-30", "2025-02-27", "2025-03-27"],
    "options": ["2025-01-30", "2025-02-27", "2025-03-27"]
  }
}
```

Select an expiry and request `/expired/contracts`:

```json
{
  "apikey": "<OPENALGO_API_KEY>",
  "broker_symbol": "NSE:SBIN-EQ",
  "expiry_date": "2025-03-27"
}
```

The same underlying identifier choices apply. `expiry_date` must precede today
in Asia/Kolkata. The response's `data` contains `broker_symbol`, `expiry_date`
and `contracts`, with separate `futures` and `options` lists of exact broker
symbols, e.g. `NSE:SBIN25MARFUT`.

Treat these strings as provider-issued historical identifiers. Pass one
unchanged to history. They are not inserted into the live master and are not
OpenAlgo order symbols. FYERS ultimately validates contract existence/expired
status. No contract catalogue is retained server-side.

## Download candles

```json
{
  "apikey": "<OPENALGO_API_KEY>",
  "broker_symbol": "NSE:SBIN25MARFUT",
  "interval": "5m",
  "start_date": "2025-03-27",
  "end_date": "2025-03-27",
  "include_oi": true
}
```

The response's `data` contains `broker_symbol`, `interval`, `start_date`,
`end_date`, `data_status`, `oi_included`, `empty_ranges`, and `candles`.
Each candle uses OpenAlgo field names, for example this candle observed in the
October 1, 2026 live smoke check:

```json
{
  "timestamp": 1743047100,
  "open": 762.15,
  "high": 765.15,
  "low": 759.5,
  "close": 765.15,
  "volume": 624750,
  "oi": 24410250
}
```

Timestamps are unchanged UTC epoch seconds. `include_oi` defaults to `true`;
when disabled, `oi` is zero and `oi_included` is false. Zero then means not
requested, not measured zero OI.

Supported intervals: `5s`, `1m`, `2m`, `3m`, `5m`, `10m`, `15m`, `20m`, `30m`,
`45m`, `60m`, `120m`, `180m`, `240m`, and aliases `1h`, `2h`, `3h`, `4h`.
Daily/weekly/monthly and other second resolutions are rejected. Greeks are
not available in the supplied FYERS contract; `include_greeks=true` is rejected.

## Limits and availability

- Dates use `YYYY-MM-DD`; OpenAlgo sends FYERS `date_format=1`. These common
  endpoints do not expose epoch-format requests. Future end dates are rejected.
- Expiry discovery accepts at most **366 inclusive calendar days** per call.
- Minute/hour history accepts at most **366 inclusive calendar days** per
  OpenAlgo call, split into nonoverlapping FYERS windows of at most **100 days**.
  Calls are synchronous; prefer shorter ranges for interactive use. Loop over
  bounded requests for larger research downloads.
- For `5s`, OpenAlgo imposes a **30-calendar-day request-size cap** to bound
  response size. This differs from FYERS' **last 30 trading days retention**;
  FYERS validates retention against its trading calendar. Splitting old
  requests does not bypass retention.
- Ranges starting before these supplied availability dates are rejected:
  NSE **2018-10-10**, BSE **2023-08-07**, MCX **2018-10-11**. Availability for a
  particular contract/range remains subject to FYERS.

## Errors and data integrity

| HTTP | Meaning |
|---|---|
| 400 | Invalid input, unsupported interval/Greeks, or classified broker request error |
| 403 | OpenAlgo key/broker login could not be resolved |
| 401 | FYERS rejected/expired the broker credential |
| 501 | Configured broker has no expired-data provider |
| 429 | Throttled; honor `retry_after` and the `Retry-After` response header |
| 502 | Upstream transport/service failure or malformed/inconsistent data |
| 500 | Unexpected internal failure |

Successful empty history has `data_status: "no_data"` and `candles: []`.
`empty_ranges` lists whole windows with no returned candles; this does not
certify every trading minute in a nonempty window. Any failed window aborts
the request, rather than returning a partial success. Candles are sorted;
identical duplicates collapse and conflicting duplicates fail. Schema, finite
values, OHLC consistency and requested timestamp bounds are checked.

Requests share the existing pooled FYERS client and process-local history rate
budget. Throttling returns immediately with the broker delay; callers control
retries. Independent processes can still share the same account quota.

## Python workflow

The installed OpenAlgo SDK has no helpers for these new local routes.
Use HTTP; set `OPENALGO_API_KEY` in your environment.

```python
import os
import requests

base = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000").rstrip("/")

def expired(operation, **payload):
    response = requests.post(
        f"{base}/api/v1/expired/{operation}",
        json={"apikey": os.environ["OPENALGO_API_KEY"], **payload},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["data"]

dates = expired("expiry-dates", broker_symbol="NSE:SBIN-EQ",
                start_date="2025-03-01", end_date="2025-03-31")
if not dates["expiry_dates"]["futures"]:
    raise RuntimeError("No futures expiry in this range")
expiry = dates["expiry_dates"]["futures"][-1]
contracts = expired("contracts", broker_symbol="NSE:SBIN-EQ", expiry_date=expiry)
if not contracts["contracts"]["futures"]:
    raise RuntimeError("No futures contract for this expiry")
history = expired("history", broker_symbol=contracts["contracts"]["futures"][0],
                  interval="5m", start_date=expiry, end_date=expiry,
                  include_oi=True)
print(history["data_status"], len(history["candles"]))
```

## Scope and verification

This adds broker, service and REST API support. Existing `/history`, `/expiry`,
equity strategies and schedules retain their behavior. Automatic Historify
storage, a browser expiry picker and F&O strategy execution are separate work.

Source contract: FYERS documentation supplied by the user on October 1, 2026;
endpoint/query paths cross-checked against the
[official FYERS SDK](https://github.com/FyersDev/fyers-c-sdk#expired-fo-historical-data).

`test/test_expired_fno_data.py` exercises registered Flask routes, service and
provider with mocked HTTP. `.development/expired-fno/verify_live.py` is the
read-only live probe, using the existing current FYERS login without restarting
the running application. Live smoke coverage is explicitly recorded in the
canonical roadmap; it is not a claim of every exchange/timeframe being tested.
