# October 8 morning FYERS repair and validation

The user explicitly requested stopping OpenAlgo, correcting the 08:50 rate-limit
errors and testing the morning brokerage, basket-margin and ₹20 lakh allocation
work. Verified the current app PID from listeners and process ownership, then sent
SIGTERM to that app. Its uv/caffeinate launchers also exited; production ports
5000/8765 are free. **Only the user restarts production.** No real or Sandbox orders
were submitted by these checks. Production databases and all 28 schedules match
the post-stop SHA-256 baseline.

## Finding and correction

Position MTM already batches its price requests, but FYERS multiquotes enriched
small derivative batches with one depth call per symbol for open interest. Twelve
positions therefore generated thirteen HTTP requests before retries. OI is not
needed to calculate position P&L. MTM now passes internal `include_oi=False`, so
that path makes one batched quote call. Other consumers retain the existing OI
contract; other brokers' signatures remain unchanged.

FYERS now documents category/plan-specific quotas, whereas the old adapter used
shared process-local limits based on older published numbers. The user answered
**Standard / not sure**. New `broker/fyers/api/data_budget.py` therefore defaults to
Standard and budgets data calls below the advertised limits:

| Plan | Local spacing | Local calls/minute | Local calls/day |
|---|---:|---:|---:|
| Standard (default) | 0.22 seconds | 45 | 4,800 |
| Prime (explicit configuration) | 0.13 seconds | 450 | 480,000 |

`FYERS_API_PLAN=prime` is for a confirmed Prime entitlement only. No upgrade or
subscription purchase is performed. Source: [FYERS plan limits](https://support.fyers.in/portal/en/kb/articles/what-are-the-fyers-api-rate-limits-for-standard-and-prime-plans), checked October 8.

Counters and a stable file lock in `log/fyers-budget/` coordinate processes of this
installation, partitioned by an API-key hash. No token/key is stored in the file.
Counters persist across process restarts, roll at the IST day boundary and retain
only one minute of timestamps. Atomic replacement protects writes. Invalid state
fails closed. Data quota exhaustion returns promptly rather than blocking a quote
request for a minute. HTTP 429 and broker-body 429/-429 establish a shared cooldown
of at least 60 seconds, respecting longer Retry-After values. Subsequent symbols
cannot produce a fresh depth retry storm during that cooldown. Transaction and
user-info calls retain their existing separate pacing behavior.

Tests force budget storage under their temporary strategy data directory. No test
changes production quota files. Counts do not reconstruct calls made before this
repair or on other machines/apps; FYERS responses remain authoritative. The file
is operational state: deleting it defeats restart accounting and is not a fix.
Plan-specific data entitlements, including historical-data availability, remain
subject to broker enforcement.

## Brokerage, baskets and capital

The morning [capital display](2026-10-08-fyers-capital-display.md) remains in the
normal Dashboard/Reports build. Strategy opening preparation is factored into a
small function for direct behavior tests; selection, reserve, sizing and dispatch
rules are unchanged. All twelve variants are tested with complete four-leg baskets,
equal quantities, one-lot and full-basket FYERS checks, ₹20 lakh allocation and
₹18 lakh deployable ceiling. A basket over ₹18 lakh is rejected before an intent
is created. Opening-intent/fill persistence, carried hedges, stops, restart recovery
and charges/reporting remain covered by the regression suite.

The request concerns basket margin and existing Sandbox execution. No live basket
order was placed or claimed tested. Charges remain tariff-based estimates, not
broker contract-note reconciliation. Account Sandbox blocked premium remains a
separate figure; existing held quantities are not resized to force utilization.

## Validation results

- **485 backend tests passed, 10 skipped**, 33.12 seconds. Coverage: new shared
  quota/request counts, FYERS history/subscription recovery, WebSocket shutdown,
  capital/fees, all options variants/recovery, scanner and Sandbox suites. Ten
  existing fixture-dependent CNC/margin tests skipped. Two existing GTT fixture
  SQLAlchemy deletion-count warnings; no test failures.
- **12 frontend tests passed** across Reports/capital components. Normal frontend
  TypeScript/Vite build passed; generated assets unchanged from the morning build.
- Desktop/mobile isolated browser checks passed for twelve baskets, individual and
  combined margin, quantities, fee breakdown and Reports mode separation; zero
  JavaScript page errors.
- New four-process test proves the shared file budget allows only one simultaneous
  slot reservation. Standard/Prime rolling limits, daily reset, corrupt state,
  HTTP/body throttling, and no-OI MTM path have direct tests.
- In-memory guard mutations intentionally caused the cooldown and over-budget
  tests to fail. No source file was altered by the mutation checks.
- 300 repeated success/cooldown/error cycles: **3 → 3 file descriptors**, retained
  traced memory +9,383 bytes after GC; bounded quota file 79 bytes in that run.
  File locks and temporary files close/clean on all paths. No new threads, sockets,
  caches or broker sessions are created by the budget helper.
- Focused Ruff checks pass. Two pre-existing unused variables/set-comprehension
  warnings in position_manager and deprecated typing imports in quotes_service
  were excluded; unrelated code was preserved.

## Actual read-only broker checks

The probe uses a private temporary snapshot of the auth/symbol database and a
client wrapper allowing only quote GET and margin POST endpoints. Network access
was initially sandbox-blocked, then the approved read-only probe succeeded.
At **09:07:29–09:07:32 IST**, FYERS returned prices for **12/12 held contracts** and
positive margin quotes for **all six open baskets plus the combined net basket**.
The combined saved basket margin was **₹75,71,834.87**. This is a current estimate
for six open positional baskets, not the ₹2.4 crore allocation for all twelve or
an entry-time reconstruction. Older Delta/Premium held shorts still await their
existing hedge-recovery path after runners start and obtain fresh quotes.

Evidence is under `log/test/fyers-morning/`; reusable isolated probe/resource/
mutation scripts are in `.development/fyers-morning/`. No secrets are printed or
included in reports. Private auth snapshot is removed after the probe.

## Operational limits and restart

FYERS currently lists **50 streaming symbols on Standard**, versus 5,000 on Prime.
The configured Nifty500 scanner and options chains can require more than Standard
allows. This rate-limit repair does not raise that entitlement or prove that all
28 schedules can run simultaneously with complete feeds on Standard. Schedules,
watchlists and strategy risk rules have not been reduced/changed automatically.
Confirm actual broker entitlement or explicitly choose a smaller symbol/strategy
scope before treating full simultaneous operation as verified.

The 07:27 expired-token errors were separate from 08:50 rate limiting. The successful
read-only checks demonstrate that the saved login worked at 09:07; no token was
fabricated or rotated. User should start OpenAlgo and confirm login/feed freshness.
If started after the 09:15 scheduled process start, verify runner Running status;
restoring schedules does not itself guarantee missed starts are replayed. Initial
new option entries still obey the existing 09:30–09:31 window. While stopped,
carried-position risk monitoring and exits do not run.
