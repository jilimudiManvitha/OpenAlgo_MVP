# October 8 latency monitor — integrated improvement

**Integration update:** The later direct-build request authorized merging this work. Main backend modules and normal frontend build are now updated; desktop/mobile browser checks and the main-module tests passed. See [project review](2026-10-08-project-review-options-backtest.md). Main-app smoke passed and it was stopped again; 28 schedules are unchanged. The following opening notes describe the earlier isolated phase.

User supplied `Latency Logs.csv` and the Order Latency Monitor screen and requested
improvement **without affecting the running OpenAlgo**. This work is staged only:
backend replacements are under `.development/latency/overlays/`, frontend source
is updated, and the preview bundle is `.development/latency/dist`. The running
backend modules and `frontend/dist` were not changed. No app restart, schedule
installation, production database write or broker request/order was performed.

## What the evidence shows

The CSV contains **1,439 requests**, September 30 through October 7 at 21:09 IST:
1,304 SUCCESS and 135 FAILED. It is an older snapshot than the user's pasted
October 8 screen, so its totals should not equal 1,476 / 134 failed.

- Only **56 records are order actions**, including historical OPTIONSORDER and
  OPTIONSMULTIORDER names. **None of these 56 succeeded.** The 1,304 successes are
  data/account/other endpoint requests, not successful order confirmations.
- **121 of 135 failures concern API-key authentication**. Six are rate-limit
  errors; other failures include validation and request errors. These cannot be
  interpreted as broker trade rejections from the dashboard totals alone.
- The old header aggregates retained history, its percentiles use a different
  30-day window, and the distribution uses only the latest 100 rows. Broker rows
  omit unattributed requests. Their displayed populations therefore differ.
- HTTP timing overwrites `g.broker_api_time` on every call, retaining only the
  final HTTP call. When no hook runs, the whole local endpoint is labeled RTT.
  The displayed broker/platform attribution is not reliable for old records.
- A read-only query of the production latency table confirmed the October 8
  08:50:31 POSITIONBOOK sample: **26,343.10 ms total**, **45.54 ms recorded last
  HTTP**, **26,297.55 ms recorded remainder**. Other contemporaneous position reads
  took about 5.98–7.21 seconds. This establishes slow endpoint responses, not
  slow order confirmations or the exact cause of their waits.

Selected CSV operation statistics (all outcomes):

| Operation | Requests | Average total | P50 | Maximum |
|---|---:|---:|---:|---:|
| POSITIONBOOK | 422 | 88.21 ms | 5.13 ms | 5,022.87 ms |
| ORDERBOOK | 387 | 15.72 ms | 5.32 ms | 315.01 ms |
| HISTORY | 212 | 498.56 ms | 379.33 ms | 2,641.49 ms |
| MULTIQUOTES | 84 | 385.58 ms | 351.79 ms | 3,726.73 ms |

These averages are diagnostic measurements from this export, not promises about
future trading. New instrumented traces are needed to attribute the 26-second
wait to throttling, HTTP attempts, SQL waits or other work. Broker rate limits,
order retries, position freshness and trading behavior were not weakened.

## Implemented changes

### Consistent dashboard

`frontend/src/pages/monitoring/LatencyDashboard.tsx` now uses a single
`GET /latency/api/dashboard` snapshot, with cancellation and query-key isolation
when filters change. It polls every 30 seconds; failed refreshes show an error
instead of a success toast. Defaults are **Order actions / Today (IST)**.

Filters cover order/data/all categories, today/24h/7d/30d/all retained history,
broker, operation, outcome, and Live/Sandbox/unknown request mode. Cards,
distribution, percentiles and broker/operation comparisons use the same sample.
Speed statistics use valid successful timings only. Failed and partial requests
remain visible in request counts, success rate and failure reasons.

All response paths load at most **10,000 newest matching records**, explicitly
disclosing truncation and the matched count. The recent table displays 100.
CSV uses the same filters and cap, with a fresh export snapshot and truncation
headers; it is not presented as the recent-table export. Formula-like text cells
are escaped. JSON request/response bodies and credentials are not exported.
One SELECT supplies the snapshot/count; the connection closes before rendering.
No all-history histogram materialization or independent per-broker raw fetch is
needed for the new dashboard. SQL still scans matching retained rows to count;
this is a memory/query-count improvement, not constant-time database performance.

The UI says **Request Latency Monitor / endpoint response time**, and explains
that an acknowledgement is not an exchange fill. It removes made-up per-stage
millisecond estimates. Old mode and HTTP attribution are visibly unknown; no
historical records are relabeled or rewritten. Installation-wide diagnostics
remain session-authenticated, matching the prior monitor's access scope.

### Correct future instrumentation

The staged `utils/httpx_client.py` times each shared-client `send()` with a
monotonic clock, including transport exceptions. Non-streaming calls include
body receipt; streaming sends cover opening the response, not later iteration.
Captured sends accumulate rather than replacing the previous call. The helper
request wrapper does not count the same send twice. Request-local measurement
is removed in `finally`; nested decorators do not double-log an endpoint.

The staged `utils/latency_monitor.py` records total handler duration, captured
HTTP time and remaining duration. A local request with no captured HTTP records
zero captured HTTP, not an invented broker confirmation. Calls made outside the
request context or through other transports are not reconstructed. Remaining
elapsed time includes waits, retries and other processing; it is not a CPU timer.
Responses with error status in a successful HTTP envelope are recorded as failed.

Safe metadata in the existing JSON column records timing version, captured send
count and request mode. Explicit response mode takes precedence over the setting
captured at request start. No new schema column/migration is needed. For data
calls, Sandbox mode still uses real market quotes.

Telemetry persistence remains off the response path. A nonblocking 512-slot
bound prevents unlimited queued records; saturation drops telemetry with a warning
instead of blocking trading. Executor shutdown/failure cannot replace an endpoint
result. Counts can therefore have gaps if telemetry is saturated; warnings are
in the process log. Both database sessions are removed by the persistence worker.
Historical namespace aliases are classified as order actions, and newly wrapped
options namespaces normalize to their existing retention types.

## Verification

- **10 isolated backend tests** pass: classification/aliases, failure exclusion,
  full-sample distribution, thresholds/percentiles, IST boundary and mode filters,
  bounded single-query reads, multiple HTTP calls, helper deduplication, failed
  HTTP attempts, nested/local/error responses, saturated/shutdown telemetry,
  real Flask filters/CSV/session authentication.
- Three deliberate in-memory defects fail the corresponding actual tests:
  mixing HISTORY into orders, retaining only the last HTTP call, and calculating
  from only the latest 100. Production source was never mutated for these checks.
- TypeScript, focused Biome/Ruff and isolated Vite build pass. Existing large
  chunk warnings remain; the normal frontend build was not run.
- Desktop and 390px mobile Chrome checks pass: same-sample 84% speed score,
  category/mode/empty filters, legacy versus measured details, full filtered CSV,
  failed refresh, no page overflow and no JavaScript errors.
- 150 isolated snapshot reads: descriptors **3 → 3**, about **47 KB** retained
  traced allocations after warmup. New state is request-bounded; no query cache,
  growing symbol registry or new repeated executor is introduced. This is not a
  production soak or a guarantee about unrelated modules.
- Baseline check of **535 source/build/config paths** found only the intended
  frontend source changed. Running backend source, schedules and served assets
  matched. Operational DB hashes were not used as a preservation test because
  the user is actively running OpenAlgo. Only a read-only latency query was made.

Evidence: `log/test/latency/{audit.json,pytest.log,build.log,mutation-*.log,screenshots/}`.
Fixture server uses port 5011 and synthetic `log/test/latency/browser.db`; it was
stopped and reaped after checks. Historical PIDs are never future signal targets.

## Integration handoff

Do not deploy this lane while the user's instance is serving it. No new approval
is being requested by this handoff. When the user authorizes integration:

1. Review `.development/latency/integration.patch` against the current files;
   its baseline hashes are in `.development/latency/baseline.json`. Preserve other
   ongoing edits. Backend targets are `blueprints/latency.py`,
   `utils/latency_monitor.py`, `utils/httpx_client.py`, and new
   `services/latency_report.py`. The frontend source is already staged in the tree.
2. Integrate backend and frontend together. The new page requires the new
   `/latency/api/dashboard`; rebuilding only the page would leave that API missing.
3. Re-run focused checks under `test/conftest.py` isolation. Use
   `--import-mode=importlib` for this checkout's package layout.
4. Only during an authorized stopped release, build the normal frontend. The
   user restarts production. New timing/mode metadata applies to future calls;
   legacy rows remain uncertain. No broker orders are needed to view the monitor.

This improves measurement, diagnosis and monitor resource usage. It does **not**
claim that the actual 26-second POSITIONBOOK wait is fixed, that broker order
confirmation is below 150 ms, or that the existing 95% target has been achieved.
Backtesting remains paused per the user's October 8 instruction.
