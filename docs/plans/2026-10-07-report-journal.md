# Daily strategy reports and performance calendar

**Evening integration:** Combined into the normal local build with user authorization. [Current release and restart checklist](2026-10-07-evening-combine.md) supersedes the staged-only status below.

**October 7 mode follow-up:** [Live/Sandbox implementation and current limits](2026-10-07-live-sandbox-features.md) adds mode-separated Portfolio, real order/GTT tickets and confirmed Strategy Builder fill reports in both modes. Still isolated and not deployed.


**Brokerage follow-up:** [Broker-specific retail estimates](2026-10-07-report-brokerage.md) now implemented in isolation; supersedes recorded-fees-only limits below. The production writer hook is staged separately to avoid affecting scheduled subprocesses.

User request: build in isolation while local OpenAlgo continues running. Combine
all strategy reports under each IST trading date, with strategy and symbol groups,
P&L, trades, wins/losses, charges, capital and a financial-year calendar resembling
`Calender_View.png`. Calendar filters include strategy and stock, with streaks.

## Isolation and design

- No production startup/shutdown, orders, schedule changes or database writes.
- Preview only on 5011, generated assets in `.development/report-journal/dist`.
- Read-only, owner-scoped report reader; existing saved reports remain unchanged.
- April–March calendar, daily drilldown, all/strategy/symbol filtering.
- PAPER, OLHC and OHLC remain separate; backtests never add to paper totals.
- Realized results use report date; carried open legs are snapshots, not new entries.
- Wins/losses use recorded net P&L; options count legs, not baskets.
- Capital means simultaneous entry value within the day, not broker margin.
- Recorded charges are shown; Sandbox brokerage is excluded by existing producers.
- Streaks count consecutive recorded days with closed trades, ignoring no-trade
  days. A breakeven day breaks a streak. Scope is the selected financial year.

## Progress

- [x] Inspect report producers, UI and isolation rules; capture protected asset/schedule hashes.
- [x] Implement read-only journal aggregation and authenticated API.
- [x] Implement combined day/strategy/stock summaries and financial-year calendar.
- [x] Verify arithmetic, account isolation, scenario separation, carry handling and UI.
- [x] Record preview evidence, cleanup and handoff. No deployment or push requested.

## Completed implementation and verification

Implemented in `services/report_journal.py`, the authenticated
`GET /market-scanner/api/report-journal` route, and
`frontend/src/components/reports/`. `StrategyReports.tsx` now opens the journal.
The existing individual trade chart and CSV download remain available within each
strategy. The old schedule-all button was removed from this reporting surface;
this feature does not change schedules.

The journal reads existing reports through SQLite `mode=ro`, with owner and
financial-year predicates and no 100-report truncation. Candle/coverage payloads
are omitted from the annual response; individual details load on demand. No
schema migration, new table, or producer change is needed. Default scenario is
PAPER; historical OLHC/OHLC records remain available separately. Unknown/missing
dates stay gray. Stock entry counts exclude unconfirmed orders, including the
three-SBIN-entries test case. Combined capital uses simultaneous entry events,
clipped to the selected day for carried positions, rather than adding each
strategy's individual peak. Equal-time entries precede exits conservatively.

Validation:

- 75 backend tests passed: journal (9), four/eight-stock strategy suites and
  scheduled NIFTY runtime suite. Owner scoping, FY boundaries, >100 reports,
  separate scenarios, pending fills, carried legs, stock grouping, fees/P&L,
  capital overlap and streak behavior covered.
- 5 frontend tests passed: leap-year calendar, accessible dates, missing-data
  distinction, strategy/stock filtering, daily list/scenarios, request failure.
- TypeScript no-emit check, focused Biome lint and Ruff checks passed.
- Isolated Vite build passed to `.development/report-journal/dist`; existing
  large-vendor-chunk and unresolved asset warnings remain.
- Browser checks on 5011 passed at 1920px desktop and 390px mobile: combined day,
  strategy expansion, stock and strategy filters, list/calendar switch, empty
  financial year, individual trade/HA/full-session charts, no page overflow and
  no JavaScript page errors. Synthetic data only.
- Resource audit (fd-audit): direct SQLite connection is enclosed in `closing`
  including error paths; no persistent caches/registries. 150 reads kept FDs at
  **3 → 3**, with **17,682 bytes** retained traced allocation after GC.
- In-memory mutations of owner scoping and capital math both made their relevant
  tests fail. Original source was never replaced during this mutation check.
- Read-only compatibility check against actual saved reports found 20 PAPER and
  8 historical strategies, across three report dates per scenario. No October 7
  report existed at the check time (before strategy startup). No trades invented.
- All **524 protected paths** (production frontend assets and schedule file)
  matched their initial hashes; **20 schedules** preserved. Production listener
  PID 48036 remained on 5000/8765 throughout. PID is evidence, never a future target.

Limits: charges are the saved round-trip fees on closed trades, not an estimate
of absent brokerage. Sandbox producers currently exclude brokerage. Capital is
entry value/premium exposure, not available funds or broker margin. Unrecorded
fees, margin and unrealized P&L cannot be reconstructed honestly from these
snapshots. Option trade counts mean legs. Streaks are scoped to the selected FY
and available recorded days with closures, not proof of uninterrupted reporting.

## Reproduce in isolation

```sh
.venv/bin/python -m pytest test/test_report_journal.py test/test_four_sandbox_strategies.py test/test_eight_sandbox_strategies.py test/test_nifty_options_runtime.py -q
.venv/bin/python .development/report-journal/verify_backend.py
# From frontend/ (never run the normal production build for this preview):
./node_modules/.bin/vitest run src/components/reports/ReportJournal.test.tsx
./node_modules/.bin/tsc --noEmit -p tsconfig.app.json
./node_modules/.bin/vite build --outDir ../.development/report-journal/dist
# From repository root; only if 5011 is free:
.venv/bin/python .development/report-journal/browser_server.py
node .development/report-journal/verify_ui.cjs
```

Screenshots: `.development/report-journal/artifacts/calendar-desktop.png`,
`daily-list-desktop.png`, `strategy-detail-desktop.png`, `calendar-mobile.png`,
`strategy-mobile.png`. Generated assets/screenshots and local baseline are ignored.
No commit, push, production build or launch was requested or performed.

Cleanup completed: the agent-owned 5011 preview was stopped and reaped. Final
listener check shows only the user's unchanged process on 5000/8765; no 5011
listener remains. Preview screenshots remain available locally.
