# Task 2 live scanner development copy

**Integrated into the normal OpenAlgo application on September 12.** The current
source of truth is the root `services/`, `blueprints/` and `frontend/src/` tree,
with regression tests in `test/test_market_scanner_live.py`. This development
copy and its original patch/manifest are historical evidence; do not reapply
or regenerate the integration patch. See the current checkpoint in
`docs/plans/2026-09-11-six-task-roadmap.md` for verification and frozen tasks.

Current integrated verification: 76 backend tests, five navbar tests, nine built-SPA
browser checks, full typecheck/build, scanner lint and a 500-cycle SQLite audit
with zero handle growth. Integrated browser/resource artifacts are under
`artifacts/integrated/`. Run `verify_integrated_browser.cjs` against the production
Vite preview at localhost:5188; it uses synthetic sessions and scanner data.

The notes below record the pre-integration development verification.

The page provides Volume Shockers, Top Gainers and Top Losers; top 50 within the
selected index; previous-close price change; separate volume change and RVOL;
real observed-price SVG lines; price/volume filters; per-account saved preferences;
pause/resume; timestamps, stale/partial coverage and closed-market states.

One SQLite-elected coordinator shares results across web workers and tabs. Broker
login attaches automatically; saved controls resume on app startup. Historical
baselines reuse the existing scanner cache. Full-universe quote passes repeat
after 60 seconds, and the browser reads shared results every five seconds. This
is a refresh interval, not a promise that a whole-universe pass completes in one
instant. Cold baseline loading and provider limits can make it slower.

An account-owned connection to the existing OpenAlgo WebSocket proxy shares its
broker adapter. By default it requests up to 500 Quote subscriptions in batches
of 50 (`SCANNER_STREAM_LIMIT`, bounded to 1–5000). Remaining or refused instruments
continue through full-universe polling. Rankings always use the full available
universe, not just streaming symbols. Only newer, complete, timestamped quotes
refresh rows; depth-derived midprices, stale ticks and decreasing session volume
are rejected. Native trade timestamps are kept separate from receipt time.

No per-row sockets or historical requests are created. Price lines contain up to
120 observations per symbol, labeled “since connected,” with visible gaps. Index
membership is reimported from local `stock_symbols_CSVs` through the page and keeps
the source/hash/import time; the supplied files have unknown effective dates.

## Verified broker capability matrix

| Adapter | Quote path | Verification |
|---|---|---|
| Fyers | Native timestamped batch quotes + shared proxy | Real September 11 closing-session quotes and volume baselines passed for RELIANCE, SBIN and ATHERENERG |
| Zerodha | Native timestamp retained; common history service | Offline native response, timestamp and previous-close calculation test passed; account-live test pending |
| Other Indian equity brokers | Common quote/history services | Capability-dependent fallback; no claim of account-live verification. Quotes without native trade timestamps are excluded; missing volume remains N/A where price/time are valid |
| Crypto/non-NSE markets | Not part of this NSE stock scanner | Not exposed |

The shared-stream merge and connection cleanup passed deterministic tests. Live
market-hours streaming and production multi-worker/reload testing remain pending;
the real broker check ran after the market closed.

## Verification and restart

- 68 backend tests passed, including the 52 existing scanner tests. Changing the
  volume baseline clears the old RVOL until refreshed, preventing incorrect labels.
- Eight Chrome browser checks passed: 50 rows, price/volume percentages,
  automatic price update, SVG charts, categories, keyboard tabs, pause control,
  desktop/mobile layout; zero page errors. Screenshots use labeled test fixtures.
- Full isolated TypeScript check and Vite build passed with `openalgo-charts`
  **2.1.7**, matching the updated repository. The original installed package is
  2.0.2; it was preserved. `dependencies/` supplies only the isolated override.
- Python lint and scanner-page Biome checks passed.
- 500 repeated SQLite publish/read cycles: 192 handles before and after, zero
  growth. Static review covered SQL sessions, owned proxy disconnects, bounded
  accounts/series, and browser request/timer cleanup. This is not a long-running
  production socket stress test.

From the repository root:

```powershell
& .venv/Scripts/python.exe -m pytest .development/task2-scanner/test_live.py test/test_market_scanner.py --confcutdir=.development/task2-scanner -o addopts= -p no:cacheprovider --basetemp=.development/task2-scanner/test-tmp -q
& .venv/Scripts/python.exe .development/task2-scanner/prepare_integration.py
```

To recreate the isolated dependency setup, run `npm.cmd install --prefix
.development/task2-scanner/dependencies --ignore-scripts --no-audit --no-fund`,
then the local `prepare_environment.ps1`. It removes only the verified old
development junction and creates dependency links, preserving the original
installation. Run the isolated Vite server on port 5187 for `verify_browser.cjs`.
`scanner-preview.html` is a browser-test harness; it does not authenticate a real
account and is not included in the production build.

`probe_live.py` is an explicitly run, read-only three-stock Fyers check using an
existing login. It never imports an order API. Test and broker evidence lives in
`artifacts/`; no credentials are included.
