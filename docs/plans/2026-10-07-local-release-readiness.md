# Local release readiness — October 7, 2026

The user requested the scheduled strategies and completed Investment Portfolio
to work together locally, followed by a Git push. This authorizes combining and
building the frontend and committing/pushing the reviewed work. It supersedes
the prior deployment hold. **The user still starts OpenAlgo.** Ports 5000/8765
were free before the build; no production process was started or signalled.

## Delivered

- Complete Investment Portfolio source and normal `frontend/dist` build, including
  asset classes, ledger, valuations, nine reports, watchlists and existing-Sandbox
  paper GTT integration. The browser check served this exact normal build from
  an isolated fixture on 5011. No real portfolio records/orders were created.
- Scheduled option subscription recovery, FYERS scanner streaming budget of
  1,000 (full REST universe preserved), required/active expiry chains, paced
  connections, persisted daily reports. All twelve launchers share these fixes.
- Stock close reconciliation now allows 60 seconds rather than three. A stopping
  snapshot is saved before a potentially slow closing batch and the final report
  timestamp is refreshed. The scheduler gives the twenty bundled paper runners
  90 seconds before forced termination, covering reconciliation and cleanup;
  custom strategies retain the five-second default. Stop waits remain outside
  the scheduler lock. Fresh-quote checks and entry cutoffs are unchanged.
- Sandbox `close_position()` treats an already-zero position as an idempotent
  success, without submitting an invalid zero-quantity order. The October 6
  missing-quantity log names **MCX the NSE equity symbol**, not necessarily the
  commodity exchange. The guard addresses the demonstrated zero-position case;
  it is not a redesign of cross-process order concurrency.
- [October 6 single HTML report](../../backtesting/all_scheduled_20261006/index.html)
  for all twenty strategies and forty modeled scenarios, with the original log
  review. Historical stale reports are preserved, not rewritten as final results.

## Verification

- **407 backend tests passed** across scheduled stock/options execution, real pool
  allocation offline, shutdown paths, Portfolio, Sandbox GTT and scheduler isolation.
  Two existing SQLAlchemy delete-count warnings remain. Pytest's existing atexit
  logger can also write to closed capture streams after success; that output is
  a test-harness shutdown warning, not a verified production failure.
- Additional readiness checks cover scheduler edge cases, graceful shutdown, history export, chart integration and optional OpenScript behavior. After rerunning the process-cleanup tests with macOS process-enumeration permission, the combined unique result is **738 backend tests passed, 4 optional tests skipped, zero failures/errors**. The restricted first run had eleven cleanup/setup errors in that test module; the permitted rerun passed 47 tests with one optional skip.
- **20 Portfolio frontend tests passed**. TypeScript and the normal Vite build
  passed. Vite reports existing large-chunk warnings.
- Desktop/mobile browser flows passed against the combined build: ledger CRUD,
  ATHER partial sale, fractional fund units, NAV CSV, liabilities, nine reports,
  FIFO export, watchlists and paper-order form without submission. Zero page errors.
- In-memory fault injection separately disables the subscription cap, chain
  filtering, connection delay, zero-position guard, closing grace and stopping
  report persistence. Each real regression fails at its intended assertion.
- Scoped lint passes for new services, runners, scheduler and app wiring.
  `blueprints/sandbox.py` retains two unchanged HEAD lint findings (import sorting
  and unused `ist` in the existing P&L route); no global clean-lint claim is made.
- Resource review: this release adds no sockets/threads/executors or unbounded
  cache. Existing `finally` cleanup remains. The suite includes 200 real report
  success/failure cycles with stable descriptor count. Portfolio's earlier
  300-cycle resource check also passed. No live market-hour soak was performed.
- Four production DBs pass read-only `quick_check` and their file hashes match
  before/after. Twenty saved schedules are byte-identical, SHA-256
  `da5150800eb92b1d6cc86f4e5bdfa38354a93bb5532b7508f03dec65776e905f`.
  The current user's one investment account/one asset and all existing data were
  preserved. The owned 5011 fixture was stopped after verification.

Local evidence: `log/test/combined-release.xml`, `combined-close-final.xml`,
`combined-frontend-build.log`, `combined-frontend-tests.log`,
`combined-readiness/`, `close-*-regression.log`, and
`.development/investment/artifacts/browser-verification.json`.

## Starting at 09:00 IST

Read-only checks at 00:15 IST show all twenty schedules enabled at 09:15 on
**October 7 and October 8**. The local NSE/NFO calendar has neither day closed.
The master contains the nearest listed expiries October 13 (472 contracts) and
October 19 (464 contracts); selection uses listed dates, not assumed Tuesdays.
Current Sandbox open positions are zero and automatic reset is `Never`.

1. Start locally with the existing command, e.g.
   `caffeinate -i uv run --no-sync app.py`, at 09:00 and keep the Mac awake.
2. Log in to FYERS that morning. A previous day's token or merely starting the
   web server does not establish a fresh broker session. Let the master/data
   initialization finish and check fresh quotes.
3. Verify the startup reports **20 restored schedules**. Their start remains
   09:15; option initial entries remain 09:30–09:31.
4. Populate the relevant weekday watchlist before strategy start. **Wed and Thu
   were both empty at this check**; their four strategies will have no candidates
   until the user adds symbols. No watchlist was seeded automatically.
5. Open `/portfolio`, `/portfolio/reports`, `/portfolio/watchlists` and `/reports`.
   Portfolio paper GTTs require explicit user prices/creation; examples were not
   submitted. Use its explicit confirmed-fill import action for ledger updates.

This is a verified local build and configuration, **not a guarantee of zero
errors or twenty trades**. Internet alone cannot guarantee broker availability,
authentication, quote freshness, sufficient funds or qualifying premium/delta
signals. A no-entry result can be correct. Transport and subscription-release
errors from October 6 still require market-hour observation; the existing exact
unsubscribe ownership checks have not been weakened to hide those errors.
Monitor status at 09:15/09:30 and final reports after closing. Do not force a late
option entry merely because the initial entry window was missed.
