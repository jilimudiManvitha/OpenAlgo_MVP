# October 8 project review and three-month options backtest

The user explicitly authorized integrating isolated work into the main tree,
building directly, fixing project errors, and starting/stopping OpenAlgo as needed.
This supersedes the prior isolation/deployment/runtime hold for this task. Tests
still use disposable databases and schedules; trading records are preserved.
No broker orders, copier arming, credential changes or Git push are requested.

## Work checklist

- [x] Confirm production stopped; preserve 28 saved schedules.
- [x] Merge latency backend patch; report-writer patch is already integrated.
- [x] Run broad backend/frontend checks and fix reproduced failures.
- [x] Build normal frontend and verify integrated feature UI.
- [x] Check changed resource lifecycles and document remaining operational limits.
- [x] Assemble actual three-month options archive: July 8–October 7, 2026
  (last completed session; October 8 is excluded while incomplete).
- [x] Replay all 12 current hedged strategies under both modeled intrabar paths,
  with standard FYERS retail estimated fees, no fabricated missing observations.
- [x] Reconcile ledgers and produce a clear combined/per-strategy offline HTML
  report under `backtesting/`, including P&L, charges, trade outcomes, capital,
  drawdown, period breakdown and assumptions.

Prior July 3–October 1 results use older unhedged Delta/Premium rules and illustrative
fees. Preserve them; they are not results of this new request. Reuse verified raw
data where it covers the new period, download only missing coverage. Backtesting
does not write into the application's Reports database.

Evidence for this review lives in `log/test/oct8-project/`. The main test suite is
run with `test/conftest.py` isolation and `--import-mode=importlib`.

## Verified project changes

The latency backend now runs from the main source, with the normal frontend build.
Reports/Portfolio/Trade Copier were already combined; the report-writer patch
reverse-applies, confirming it is integrated. Browser checks against the rebuilt
bundle passed Portfolio ledger/reports/watchlists, combined strategy Reports,
Live/Sandbox partitions, copier controls and latency desktop/mobile interactions.
Only fixture accounts/orders were used for those browser mutations.

Runtime fixes cover request-session shadowing in seven XTS depth adapters, missing
reconnect jitter import in Dhan sandbox, Pocketful update subscription helpers,
Groww's obsolete convenience helper (now delegates to existing pooled REST), and
explicit unsupported Groww segment errors. Telegram type-only annotations and the
sandbox execution-engine standalone configuration import were corrected.

Full backend: **6,305 passed, 28 skipped, 1 expected failure**. An earlier run's scheduler
thread warning exposed an additional persistent scheduler shutdown race. Flow and
Historify now wait for dispatch bookkeeping without deleting saved jobs or holding
application locks while joining. All **21 lifecycle tests** pass with thread
exceptions treated as errors. Nine older tests return values (pytest warnings),
and the MCP dependency emits one forward-reference warning; these are recorded
rather than misrepresented as a warning-free full run.

Full frontend: **2,980 tests / 199 files passed**. After lint cleanup, 41 targeted
symbol-search/previous-close tests passed. The search test now waits for the existing
focus/select timer before typing. Frontend lint: no errors/warnings, two template
literal suggestions. Normal build passed; existing bundle-size notices remain.
Critical Python scan (`E9,F63,F7,F82`) went from 122 findings to zero; 101 were
Telegram type-only names. Broad style lint is not claimed clean.

15 SQLite files passed read-only quick checks. The 28 saved schedules remain
preserved. The merged latency snapshot path retained 3 file descriptors before and
after 150 calls (47,948 retained traced bytes after GC). Telemetry queues and
snapshots remain bounded; Pocketful's broken per-call helper threads were removed.
No live broker order was submitted, so broker exchange acceptance and real
confirmation-time improvement are not established by these checks.

Main runtime smoke passed: `/`, `/auth/login`, `/auth/session-status` and
`/auth/csrf-token` returned 200; ports 5000/8765 opened, FYERS market-data WebSocket
authenticated, then SIGINT drained the owned app and both ports closed. No runtime
errors appeared in that log. Saved configuration is byte-identical (SHA256
`79593c33ba051796fec66ca8068e4b691ba5ef0e83bc376577bbd32382d588fe`).

All 7,070 option contracts plus NIFTY spot archive coverage are assembled.
Final focused regressions: 34 passed; removing the persistent-scheduler barrier
in memory makes both new tests fail as expected. No production file mutation was
used for defect-injection checks.

## Completed backtest and final state

[Single offline HTML](../../backtesting/options_3months_2026-10-07.html) ·
[Per-strategy results, assumptions and reproduction evidence](../../backtesting/nifty_options/2026-07-08_2026-10-07/README.md).

64 trading sessions; 12 strategies × 2 alternate intrabar paths. OLHC gross
₹11,69,743.25, estimated charges ₹3,81,220.59, net ₹7,88,522.66 (3.2855% of
₹2.4 crore allocated across independent strategy simulations). OHLC gross
₹11,72,912.00, charges ₹3,81,156.51, net ₹7,91,755.49 (3.2990%). Each has 434
closed cycles, 252 wins and 182 losses; four open cycles are marked at the end.
Combined observed-minute drawdown is ₹5,45,928.08 / ₹5,45,377.29 respectively.
Do not add the two paths or treat their spread as guaranteed bounds.

All 24 ledgers and fee component totals reconcile, as do 3,520 closed-leg rows,
7,071 source hashes and 98 local links. Browser verification covered every
strategy/path, chart bars, table totals, charges, filtering, sorting, CSV and mobile
layout; no page errors or network requests. The mobile metric-card overflow found
in verification is fixed. A copy with identical bytes is the single HTML deliverable;
raw ledgers, source snapshots and deeper research artifacts remain in its results
subdirectory. No application's Reports records were changed by the backtest.

Final full backend run: 6,305 passed, 28 skipped, 1 expected failure, 10 warnings
(nine legacy test-return warnings and one dependency annotation warning); the
scheduler thread warning is resolved. The main app and scheduled strategy runners
remain stopped. All 28 saved schedules are retained for the user's next start.
All changes are local; no Git commit/push or broker order was performed.
