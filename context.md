# OpenAlgo fork - AI agent context

**October 8 after-hours runtime:** User requested running OpenAlgo and mock latency tests, explicitly noting the market is closed. OpenAlgo is now running in its unchanged Sandbox mode with 28 schedules preserved; no strategy runners were manually started and no real orders sent. Quote/depth throttling now preserves HTTP 429 and retry delay instead of becoming 500. See [after-hours latency results](docs/plans/2026-10-08-after-hours-latency.md): 300 successful mock/paper orders, 45 regression tests passed. Earlier “app stopped” checkpoints below are historical.

**October 8 current checkpoint:** [Main integration, project checks and new three-month options replay](docs/plans/2026-10-08-project-review-options-backtest.md). User authorized main-tree work and app start/stop, superseding the historical holds below. Latency now runs from main source and rebuilt frontend. Integrated browser checks and the full backend/frontend suites passed; scheduler-race regression follow-up passed. Main app startup/read-only routes/FYERS WebSocket connection and graceful shutdown verified; ports 5000/8765 free and 28 schedules unchanged. No broker orders or Git push. July 8–October 7 current-hedged backtest is complete: [single HTML](backtesting/options_3months_2026-10-07.html), OLHC net ₹7,88,522.66 / OHLC net ₹7,91,755.49; alternate simulations on ₹20 lakh per strategy. Full backend final: 6,305 passed / 28 skipped / 1 expected failure.

**October 8 explicit shutdown:** User requested stopping OpenAlgo and scheduled strategies. Sent graceful termination to the verified app and running strategy processes and stopped its MCP helpers. Final process check found no OpenAlgo runtime processes; ports 5000/8765 are free. Read-only verification retained all 28 saved schedules. No restart or latency-lane deployment was performed; only the user starts production. Saved schedules were not disabled and remain available for the next start.

**October 8 latency request:** [Isolated monitor improvement](docs/plans/2026-10-08-latency-monitor.md) separates order/data requests, unifies metric filters, fixes last-HTTP attribution, bounds queries/telemetry and documents the supplied CSV. Backend replacements stay in `.development/latency/overlays`; frontend source requires those API changes before a future build. Not deployed; production source/assets/schedules preserved. Backtesting remains paused.

**Current implementation map:** [October 7 feature status](docs/plans/2026-10-07-feature-implementation-status.md) records Portfolio, Reports/calendar, broker estimates, Screener, Trade Copier, 28 schedules and current limits. The evening integration supersedes historical isolated/not-deployed entries below. **October 8: user asked to skip further backtesting.** The already generated October 7 HTML is retained under `backtesting/`; final preservation verification was unresolved. Do not resume without a new request. See the implementation map’s backtest checkpoint.

**October 7 options hedges:** Delta/Premium now buy 200-point wings, bringing all 12 variants under the hedge rule. Carried positions recover missing wings at next runner start; 129 isolated checks pass. See [current rules](strategies/nifty_options/README.md). Existing schedules and state preserved; historical backtests not rerun.

**October 7 evening:** [Combined release: 28 schedules, equity 15:15 exits, restart recovery, Reports/Portfolio/Copier integration](docs/plans/2026-10-07-evening-combine.md). User starts OpenAlgo.

**October 7 isolated Trade Copier:** [Local master/child copier handoff](docs/plans/2026-10-07-trade-copier.md) — native FYERS/Zerodha/Dhan, bridge for other OpenAlgo brokers, separate Sandbox children, durable copy state/risk/stop controls. Not activated; no real orders sent.

October 7 short equity request — eight Sandbox-only short counterparts of the equity longs are implemented under `.development/equity-shorts/`, with an isolated add-only 28-schedule preview (original 20 + 8 shorts). All signal/entry HA OHLC below VWAP, lower-BB/signal-low entry, stop above signal high and mirrored fixed/trailing exits. 109 focused checks pass; 575 protected files unchanged. Not activated; evening merge after 15:30 awaits the user stopping the app, and only the user restarts it. [Rules, verification and integration steps](docs/plans/2026-10-07-short-equity-strategies.md).

October 7 Live/Sandbox follow-up — mode-separated Portfolio/reporting, explicit broker order/GTT tickets, broker fee estimates in ledger/order review and newly imported paper fills, Strategy Builder Live/PAPER journal adapter, and mode-aware Screener are implemented in isolation. Real order/GTT development explicitly authorized; no real orders or deployment. [Behavior, verification, limits and activation](docs/plans/2026-10-07-live-sandbox-features.md).

October 7 broker-fee follow-up — standard retail estimates for eight verified brokers now feed daily/strategy/stock net P&L and calendar streaks, including Sandbox and stored live reports. 106 backend / 7 frontend checks and isolated browser checks pass. Broker capture hook is tested in an overlay; production ReportStore/strategy code and serving frontend remain unchanged. No deployment. [Rates, limits and required integration patch](docs/plans/2026-10-07-report-brokerage.md).

October 7 Reports update — user requested isolated development while OpenAlgo runs. Combined daily strategy/stock reports and FY performance calendar with filters/streaks implemented and verified (75 backend / 5 frontend tests, desktop/mobile browser, resource audit). Saved fees and entry-value capital limitations are explicit. Production assets, 20 schedules and running instance preserved. Not deployed or committed. [Implementation and handoff](docs/plans/2026-10-07-report-journal.md).


October 7 local release — user authorized combining Portfolio and scheduled-strategy fixes and pushing to Git. Normal frontend rebuilt while production was stopped; 407 backend and 20 frontend tests pass, browser checks pass against this build on isolated 5011. Added bounded stock close/reconciliation grace and idempotent zero-position square-off. Four production DB hashes and twenty schedules preserved. The user starts OpenAlgo at 09:00 and logs in before 09:15; Wed/Thu lists are empty. [Full release checklist and limits](docs/plans/2026-10-07-local-release-readiness.md). This supersedes the prior Portfolio deployment hold.

October 6 session review — today's 20 scheduled strategies replayed in 40 independent scenarios; [single offline HTML](backtesting/all_scheduled_20261006/index.html), [complete results/evidence](backtesting/all_scheduled_20261006/README.md). Twelve option runs missed entry amid shared-pool capacity errors and transport failures. FYERS scanner now capped at 1,000 streaming symbols with full REST universe retained; option runners select required/active expiry chains and stagger connections. 139 focused tests and three fault-injection regressions pass; real pool allocator fits the tested demand into 2,461/3,000 slots. **Scanner cap requires user restart**; app was not restarted. Six stale stock reports, network disruptions and MCX missing-quantity error remain follow-up items. Twenty schedules and all 520 protected files unchanged. Portfolio build scope complete locally; deployment/operational acceptance pending “combine and launch.” See [repair checkpoint](docs/plans/2026-10-03-nifty-options-strategies.md#october-6--capacity-repair-and-all-schedule-daily-backtest).

October 6 — user resumed and requested completion of the remaining Investment Portfolio. Phases 3–5 are implemented and verified in isolated development: all requested classes, liabilities, dated CSV prices, nine reports, watchlists and existing-Sandbox paper GTTs with idempotent confirmed-fill reconciliation and reset protection. 59 portfolio backend / 113 Sandbox GTT / 20 frontend checks pass, plus type/lint/build and desktop/mobile browser verification. **Not deployed**; user’s “combine and launch” is still required. No production process, database, schedule or frontend build was changed. [Completion handoff](docs/plans/2026-10-06-portfolio-completion.md). This supersedes older portfolio “stopped / not started” notes below.

October 5 — user authorized scheduled-options repair while OpenAlgo remains
running. All twelve runners crashed on a rejected subscription batch; shared
runtime now retries missing acknowledgements with pacing and publishes daily
Sandbox reports to `/reports`. 109 focused tests pass; original-code regression
fails as expected; 961 read-only quote subscriptions accepted after hours.
Twenty schedules preserved byte-for-byte. New backtest outputs use
`backtesting/nifty_options/` per latest user instruction; existing `backtest/`
artifacts preserved. No orders, production DB writes, app restart or frontend
build. Next separate strategy launch loads the repair; no late/replayed entries.
[Complete repair checkpoint](docs/plans/2026-10-03-nifty-options-strategies.md#october-5--scheduled-startup-repair-and-daily-reports).
Portfolio work remains stopped and unrelated local edits remain intact.

October 4 evening — **parallel-development standing order is now in force.** The user
intends to use OpenAlgo for live trading *while* Portfolio work continues. Every
OpenAlgo process was stopped at the user's request so they can restart clean: the
`caffeinate`/`uv` wrapper (15964/15963), app server (15965) and MCP helpers (82809,
88903); ports 5000/8765 free. **The user restarts production, not an agent.** Agents
work only in a development lane: fixture server on 5011, databases under `log/test/`,
never signalling a process they did not start, never the production databases,
schedules or `frontend/dist` rebuild. Portfolio code ships only on "combine and
launch". Full rule set in handoff §0 and at the top of `AGENTS.md`.

October 4 final checkpoint — [complete readiness and investment handoff](docs/plans/2026-10-04-readiness-portfolio-handoff.md).
Initial investment ledger and Dashboard/Stocks deployed at `/portfolio`; weighted-average
and FIFO, owner/CSRF protection, dated valuations, charts and stock transaction history.
5,961 backend / 2,962 frontend full-suite passes; final focused 30 backend / 21 frontend
passes after last small fixes. Browser workflow and deployment checks pass. User accepted
the verified ATHER baseline, resolving the Phase 3 gate; existing sandbox/preserve holdings,
FIFO and categorized paper GTT decisions are settled. Phase 3/reports/GTT integration are
not started. Earlier note corrected: OpenAlgo is **not** running — it was stopped later on
October 4 as described above; twenty schedules restored, sandbox financial
tables unchanged, new investment tables empty. No orders. Only the separate NIFTY
options work was committed and pushed (`55a706486`, `2af96f002`). Test server stopped.
This supersedes earlier “implementation not started,” pending reconciliation and PID notes below.

October 4 readiness: [checks and scheduler test-isolation repair](docs/plans/2026-10-04-monday-readiness.md) complete. OpenAlgo PID 11869 running, all 20 schedules restored; leave running. User confirms existing sandbox/preserve holdings, FIFO alongside weighted average, categorized paper GTT orders (examples only). FYERS read-only holdings API returned an empty account on October 4; no import/orders. Task 6 Phase 1 may now start; exact three-stock reconciliation remains pending.

October 4 follow-up — combined three-month dashboard is complete:
[All 12 strategies in one offline report](backtest/nifty_options/2026-07-03_2026-10-01/results/combined_dashboard.html).
Cycle win rate/profit factor/payoff, trade counts, six charts, monthly P&L and
trade-cycle details; switch OLHC/OHLC without double counting. Metrics reconcile
and browser interactions pass for all 24 scenarios. Reporting only; no rerun,
app restart, schedule changes or Reports writes.

October 4 — separate NIFTY options request is active. Twelve Sandbox-only Python
variants are implemented under `strategies/nifty_options/` with separate parent
launchers. User-approved restart installed 12 NFO weekday schedules (09:15–15:40,
entries 09:30, intraday exits 15:20) alongside the eight original schedules;
the original definitions were verified unchanged. NRML is used for all twelve
to avoid the existing 15:15 MIS auto-square-off. Sandbox capital is ₹5 crore,
₹20 lakh/₹20k loss threshold per variant. SQLite persists owner-scoped positions,
loss cycles and uniquely tagged pending orders. **45 tests pass**; no orders placed.
The user now says OpenAlgo is running: **leave it running**.

Latest backtest scope **2026-07-03 through 2026-10-01 only** is now complete,
replacing five years. All 7,096 contract archive requests finished; 64 sessions,
24 modeled scenarios, 2,428 closed-leg records, 7,097 source hashes and 98 local
links verified. Nine variants positive, three negative in both paths. Two open
premium positional legs remain marked in each path. Price/Greek gaps, estimated
margin/costs/deltas and assumed candle ordering are disclosed. Market-hour live
fills remain unverified. No app restart or orders in this final completion turn.
[Results](backtest/nifty_options/2026-07-03_2026-10-01/README.md).
All new/future outputs belong in `backtest/`, never application Reports.
[Full checkpoint](docs/plans/2026-10-03-nifty-options-strategies.md).
Other six-task work/Crypto/investment remains untouched by this request.

October 2 — user requested a new Investment Portfolio section: ten asset classes
(Stocks, Mutual Funds, ULIPs, Fixed Income, Bullion, Property, Loans, Other Assets,
Other Borrowings) with full read/write, a timestamped transaction ledger, nine
reports, portfolio scoring and charts. This is roadmap Task 6, which the user
**unfroze**, replacing the September 12 freeze and the original 4-watchlist-style
scope. Locked decisions: weighted-average cost basis on holdings screens; manual
price entry plus CSV import for non-stock assets (the codebase has **no** AMFI/mfapi
NAV provider); new code under the `investment` namespace because `/api/v1/portfolio`,
`portfolio/`, `src/api/portfolio.ts` and `/portfolio` are all taken by the portfolio
backtester — only the user-facing route is reclaimed, and `/portfolio-backtester`
keeps working. Phase 1 = schema + ledger + API, Phase 2 = Dashboard + Stocks, then
widen. **Phase 0 (decisions + plan) only; documentation changed, no implementation.**
Full plan: [docs/plans/2026-10-02-portfolio-section-plan.md](docs/plans/2026-10-02-portfolio-section-plan.md).
Four open questions remain in its section 12, the first being whether paper trading
wires into the existing `database/sandbox_db.py` engine. No orders, schedules, strategies
or the Crypto tree were touched.

October 1 evening — user manually has OpenAlgo running; MCP calls succeeded.
At user request cleared all 18 Wed entries and verified empty. Subsequent request
completed today's backtests for all eight saved scheduled profiles: 73/73 scanner
stocks, 20/20 current Thu stocks, both modeled paths, 1,240 ledger rows verified,
69 focused tests passed. [Results](backtesting/eight_scheduled_20261001/README.md).
Nifty500 fixed 1m +₹536.55/−₹631.85 OLHC/OHLC; all other profiles lost both paths.
Retrospective scanner/current-watchlist selection, modeled ticks and illustrative
cost limitations are documented. No orders, strategy starts, schedule edits or
restart; app left running. This supersedes the stopped note below. See canonical
roadmap checkpoint for details. Browser rendering unavailable; artifact checks pass.

October 1 — user requested stopping OpenAlgo after MCP verification. SIGINT sent
to PID 22153; verified app/launchers/strategy-script processes and listeners on
5000/8765 are gone. Saved schedules, MCP configuration and local changes remain.
Do not restart without a new instruction; this supersedes running notes below.

October 1, 21:10 IST — MCP watchlist feature implemented and verified locally.
Eight watchlist tools plus three expired F&O tools bring the shared registry to
60. Authenticated `/api/v1/watchlist` updates the same saved lists as the chart;
pasted comma/space/newline stock batches support add/remove and explicit replace.
Installed Codex/ChatGPT desktop local entry in `~/.codex/config.toml` using a
private key-file launcher. Repaired stale OpenCode key using the existing current
application key with approval; no key rotation. Exact configured stdio handshake
and live list read pass (HTTP 200; Mon/Tue/Wed/Thu/Fri). Clients need reload/new
session; desktop UI reload itself remains unverified. Remote MCP stays disabled.
User explicitly approved app start: **PID 22153**, terminal session **60287**,
running since 21:01:50 on 127.0.0.1:5000/8765; **leave running**. No real watchlists,
orders or schedules changed. **173 targeted tests pass**; owner-filter mutation
detected; DB session cleanup verified through 100 isolated edit/error cycles.
See canonical roadmap for details and [MCP guide](mcp/README.md) for prompts.
Current MCP changes uncommitted/unpushed; prior snapshot pushed as `fc3d646b6`.

October 1 synchronization: user authorized pushing pending changes to
`jilimudiManvitha/OpenAlgo_MVP` origin/main. Snapshot includes expired F&O APIs,
startup/session/scanner/subscription fixes and documentation. **403 tests pass**;
the broader run exposed an outdated shutdown-test namespace, now updated to
include the actual startup helper. See canonical roadmap for validation and
scope; final remote commit verification is recorded in the session response.
No app restart or strategy/schedule changes.

October 1 expired F&O feature: user authorized all three APIs. Implemented
authenticated `/api/v1/expired/expiry-dates`, `/contracts`, `/history` with FYERS
provider, validation, bounded history windows, exact discovered contract IDs,
OHLCV/OI and explicit errors/no-data. **136 tests passed** (86 new); live FYERS
SBIN 2025-03-27 discovery returned 1 future/150 options and 75 five-minute candles
with OI each for SBIN25MARFUT and SBIN25MAR760CE. API/service scope only; no
Historify UI/storage or F&O strategy was added. Existing app was not restarted;
new HTTP routes load on the user's next manual restart. No orders or schedule
changes. See canonical roadmap for evidence/limitations and
[API guide](docs/api/market-data/expired-fno.md) for usage. Unrelated local changes
and earlier fixes retained; no commit/push.

Latest live check, October 1 11:18 IST: user's manual app PID 7918 is running,
HTTP 200 and both listeners verified. No new ERROR logs since 11:15 startup.
Scanner completed 2670-symbol scan, zero rate-limit retries, and fresh WebSocket
ticks verified for TCS/SONACOMS/SUNPHARMA/TATASTEEL/SBIN. See canonical checkpoint
for coverage limits. All eight schedules are enabled but **no strategy process
is running** (configs false/null); app started after their 09:15 trigger. No
strategy start, order, restart or schedule modification performed. Keep app alive.

October 1 manual-start fixes: user authorized repairing the remaining reported
failures. FYERS symbol-token HTTP now uses pooled/paced, bounded requests and
separates service/JSON/auth failures from genuine invalid symbols. Subscription
worker retries transient failures with bounded delays, honors Retry-After,
cancels stale retries on teardown, and records pending/retrying/dispatched/
rejected/failed status. Earlier startup-order, rollover and scanner pacing fixes
remain. **232 focused tests pass**; real-timer 100-cycle thread/descriptor check
is stable; no new Ruff findings. See canonical roadmap for limitations.
User's app was not stopped/restarted; next manual restart loads the changes.
No schedule/execution-mode/credential changes, orders, commit or push.

October 1 10:18 diagnosis: user's 10:14:59 manual restart connected cleanly,
but a symbol-token JSON parse failure prevented one later HSM subscription
batch. Offline mocks confirm the converter incorrectly labels service failure
as invalid symbols, and batch flush drops a False subscription result without
retry. Not fixed in this status-check turn; see canonical roadmap. App left
running, no schedule/source changes. Older stopped notes are historical.

Latest process state, October 1 10:14 IST: stopped at user's request via SIGINT
to app PID 5720. Verified app/launcher/strategy-script processes and OpenAlgo
5000/8765 listeners exited. Saved schedules and local fixes retained. User will
start manually; do not restart. Earlier running/stopped notes are historical.

October 1 startup-order follow-up: user manually restarted at 10:07:47. Their
log shows local WebSocket refusal followed by successful auth/subscriptions
five seconds later. Scanner was starting inside create_app() before the proxy.
Moved it after proxy integration and added a bounded listener-readiness wait
for the threaded local proxy. 163 focused tests passed; no new Ruff findings.
App left running, schedules unchanged; next manual restart loads the fix.
See canonical roadmap for evidence/limitations. Earlier stopped states below
are historical; no automatic restart is authorized.

Latest process state, October 1 10:07 IST: stopped at the user's request using
SIGINT to app PID 3321. Verified app, uv/caffeinate launcher and strategy-script
processes exited, and OpenAlgo's 5000/8765 listeners are gone. User will start
manually; do not restart. Saved schedules and scanner fixes remain unchanged.

October 1 scanner 429 follow-up: user supplied manual startup at 08:45 with
successful app initialization followed by FYERS quote throttling. Added local
scanner batch pacing (1.25s), removed scanner-only nested HTTP retries and
preserved server retry delays in cancellable cooldowns. Focused suite: 113
passed; initial three pacing regressions failed before the fix. App was not
restarted or stopped; live recovery is unverified and requires a controlled
restart to load changes. See canonical roadmap for scope/resource review.
The 08:44 stopped state below is historical. Eight schedules remain untouched.

September 30 entry timing checked at user request: all eight saved scheduled
profiles already submit on a qualifying intrabar signal-high cross, without
waiting for the entry candle close. Added eight regression cases (including
strict trailing and 5m); focused suite 69 passed. Runtime and Sandbox execution
mode unchanged; see canonical roadmap for evidence and existing entry filters.

September 30 source synchronization: user authorized pushing all pending changes
to origin/main (jilimudiManvitha/OpenAlgo_MVP). Local snapshot `9b3033c5e` merged
with remote `a6013c291`, preserving chart documentation and both HSM fixes.
See the canonical roadmap synchronization checkpoint for validation and scope.

Latest process state, October 1 08:44 IST: OpenAlgo stopped cleanly at the user's
request via Ctrl+C to session 59588; terminal exited 130 after scheduler, health
collector and checkpoint cleanup. Verified app PID 3047, uv/caffeinate and
WebSocket listener are gone. Eight saved schedules remain. User will run manually;
do not restart without a new instruction. Startup stale-session fix remains local
(79 focused tests passed). User activity completed FYERS master-contract processing
before shutdown. See canonical checkpoint; earlier running notes are historical.

Current six-task request (2026-09-11): see
[`docs/plans/2026-09-11-six-task-roadmap.md`](docs/plans/2026-09-11-six-task-roadmap.md)
for the canonical plan, pending decisions, task checklist and restart instructions.
Planning is complete; this session did not implement features or run backtests.
Its task numbers are separate from the historical task sections below.

2026-09-30 documentation: [Four-strategy chart guide](strategies/FOUR_STRATEGIES_CHART_GUIDE.md)
explains the four current ₹10,000 Sandbox profiles with separate flow diagrams
and linked offline interactive examples. Prices are illustrative, not new
backtest results. Source rules and app state were unchanged; see the canonical
roadmap's documentation checkpoint for verification and the prior operational state.

This file lets a new AI agent pick up where the previous session stopped
instead of starting from scratch. It is updated at the end of every task.

September 30 evening: user authorized four new 5m HA Sandbox profiles plus fixes
to the four original 1m runs. **Eight schedules are now restored in the running
app**, next start October 1 09:15 IST, stop 15:00. User will populate Thu before
09:15. See the latest canonical roadmap checkpoint for incident diagnosis,
136-test verification and the active server PID/session. Historical notes below
do not override that checkpoint.

September 30 follow-up: today's backtests completed for all eight profiles,
both modeled paths. [Results and artifacts](backtesting/eight_scheduled_20260930/README.md).
76/76 scanner and 16/18 Wed coverage (two BE-series exclusions), all ledgers
verified, 61 focused tests passed. Exact-session history queries resolved FYERS
duplicate/conflicting full-day responses; scheduled warmup uses the same fix.
No schedule changes or server restart during backtesting. The latest canonical
checkpoint records limitations; simulated results are not today's forward fills.

## Repository map

2026-09-29 synchronization: the newly requested push destination is
`https://github.com/jilimudiManvitha/OpenAlgo_MVP.git`. The old origin below is
preserved for historical/LFS access. See the current six-task roadmap checkpoint
for merge and push status, and `docs/installation-guidelines/macos-local-fork.md`
for Mac clone/restore instructions. Earlier sole-remote instructions are historical.
The merge through upstream `fe6aa9783` and complete portable snapshot
`7fa72c7ea` were successfully pushed to the new destination's `main`;
all 228 unique LFS objects are present remotely. Use `portable-backup/latest/`
with the separately transferred `mac-restore-20260929-latest.key` for restore.

2026-09-11 restart correction: the user added `upstream` and merged its `main`
into local `main` (`36f8c2742`). `origin` remains the requested private repository
below. Preserve both current remotes; the earlier sole-remote instruction is
historical. Task 2 now has an isolated prototype in `.development/task2-scanner/`
(`11ca386ab`), with implementation gaps and verification recorded in the canonical
six-task roadmap. It is not yet integrated into the original application.

- Only active remote: `origin`, https://github.com/Narasimha722/openalo_indian_markets_mvp.git (private).
- Local branch: `main`; use `origin/main` for future pulls and pushes. Do not recreate the former `fork` or upstream remotes.
- New-laptop migration and the encrypted database/settings backup: [migration.md](migration.md).
- The Fyers volume-shocker/top-gainer/top-loser backend and custom skill mirrors are committed. UI work remains deferred until the user requests it.
- The task sections below are historical context and may describe earlier repository states.

## TASK 6 - calculator redesign + brokerage fees - IN PROGRESS (this session)

Ready for commit: backend estimator, API, tests, frontend client, calculator
redesign, order-book Charges column - all verified. Not yet pushed.

- **`data/broker_charges_comparison.csv`** (new): copy of the user's tariff
  sheet (`D:\Personal\broker_charges_comparison.csv`) + a Groww section
  appended (flat Rs 20/order, delivery Rs 0, STT/SEBI/stamp/txn mirroring
  Zerodha, delivery DP Rs 15 incl GST). Source had Fyers/Zerodha/Dhan only.
- **`services/brokerage_charges.py`** (new): pure estimator, no Flask. Reads
  the CSV once (lru_cache), resolves the segment from
  exchange/product/symbol/instrumenttype (`Equity Delivery`, `Equity Intraday`,
  `Futures`, `Options`; Dhan "Futures (Equity F&O)"/"Options (Equity F&O)"
  aliased), merges global rows ("All Equity Segments" GST/SEBI/IPFT and
  "DP Charges"/"Demat Account" DP) into every segment, returns per-component
  amounts + total + notes. Supported: `fyers, zerodha, dhan, groww`.
  Three parser defects fixed mid-task and pinned by tests: equity symbols
  ending in "CE"/"PE" (RELIANCE, BAJFINANCE) resolving to Options; STT
  "0.1% on buy and sell" parsing as sell-only; global-segment rows never
  loading. DP buy-row clash (Groww, Fyers) resolved by keeping the sell row.
- **`blueprints/brokerage_charges.py`** (new): `POST /brokerage-charges/api/estimate`
  and `/api/estimate/batch` (`{orders:[...]}`), both `@check_session_validity`,
  broker from session, 403 outside the supported four. Registered in `app.py`.
- **`frontend/src/api/brokerage.ts`** (new): `estimate` / `estimateBatch` via
  `webClient` (auto-CSRF). Exports `BROKERAGE_BROKERS` set for UI gating.
- **`PositionCalculator.tsx`** redesigned: header = symbol + live price beside
  it + exchange/product badges + Buy/Sell toggle; Trade Type tiles directly
  below; "Price" section (Market/Limit tiles + limit input + validation hint);
  Capital section; Quantity card with Leverage `Nx` as just the number, lot
  size, input + Max + max-qty readout, and a Brokerage chip that pops open the
  estimate breakdown. Risk Management is gone - replaced by an "Add Stop Loss /
  Target Price" expander (SL / Target / Trailing SL). Bid/ask display removed.
  Dialog widened to `sm:max-w-lg` with inner scroll. Brokerage chip hidden
  unless `authStore.user.broker` is in the supported set; estimate debounced
  400 ms, valued at LTP (Market) or the limit price (Limit).
- **`OrderBook.tsx`**: new "Charges" column (header + cell) only for supported
  brokers and `!isCrypto`; one batch call estimates every priced row
  (`price>0 && quantity>0`); cell shows the total with a hover tooltip
  (segment + per-component breakdown); unpriced rows stay blank.
- Verification done: `pytest test/test_brokerage_charges.py` 19/19 passed
  (locked vectors: Zerodha intraday BUY 100@500 = 21.07, delivery SELL =
  67.21 incl STT 50 + DP 15.34, Fyers options SELL 1 lot @200 lot75 = 54.00,
  Groww delivery SELL = 66.87 with DP 15, Dhan intraday BUY = 111.23, Zerodha
  Futures BUY 1 lot @48000 lot35 = 95.46); `ruff check` clean;
  `tsc -b` clean; `vitest terminal.test.ts` 53/53; biome lint clean;
  `npm run build` clean (new chunk `brokerage-*.js` contains
  `brokerage-charges/api`).
- Docs updated: `Documentation.md` (Task 6 section) + this file.

## TASK 5 - calculator leverage gate + Market/Limit + 3D UI - DONE

All plan items from the previous section are implemented, verified and
committed. Implementation summary (what changed vs the plan):

- `PositionCalculator.tsx`: `effectiveLeverage = tradeType === 'INTRADAY' ?
  leverage : 1`. Sizing basis is the LIMIT price when a Limit order is chosen
  with a valid price, else live LTP. `maxQuantity = floor(capital *
  effectiveLeverage / priceBasis)`. Outcome now carries `orderType` and
  `price?`. New 3D dark-glass styling (raised/inset `Tile` component, gradient
  glow cards, gradient CTAs) - pure Tailwind CSS, no new deps. Limit price
  must be beyond the market (buy below LTP, sell above LTP) or confirm is
  blocked with an explanation; the "scheduled order" semantics the user asked
  for.
- `terminal.ts`: `confirmOrder`/`_executeOrder` opts gain `price?: number`;
  `_executeOrder` prices LIMIT orders from `opts.price` instead of snapping
  to the chart context price.
- `ChartPane.tsx`: `handleCalcConfirm` passes `outcome.orderType` (was
  `calcParams.type`) and `outcome.price` into `confirmOrder`.
- Verified: `tsc -b` clean; `vitest terminal.test.ts` 53/53; biome lint
  clean; `npm run build` clean; rebuilt `PositionCalculator-*.js` chunk
  contains Market/Limit/"not applicable"/"cash value".
- Docs updated: `Documentation.md` (outcome/order-type/quantity/layout
  sections, terminal LIMIT-price note, change summary) and this file.

Existing plan section below is kept for reference history.

Goals (user requirements, verbatim intent):

1. Leverage must apply ONLY to INTRADAY. For OVERNIGHT and GTT the multiplier
   is not applicable: capital/price only (SBI at Rs 100, capital Rs 100 ->
   exactly 1 share). Current code fetches the intraday multiplier and uses it
   for every trade type - GATE IT.
2. New order-type selector in the calculator: MARKET vs LIMIT.
   - MARKET = execute now at current market price (leverage applies for
     Intraday, not for Overnight/GTT).
   - LIMIT = schedule at a chosen price; executes when the market reaches it
     (e.g. buy SBI only when it comes down to 80). Same leverage rules.
3. Rebuild the calculator UI as a "3D UI" (depth/raised-inset controls,
   glass gradients, glow). Keep every existing prop/outcome contract and the
   wiring below intact unless the plan says otherwise.

Design decisions:

- Effective multiplier = tradeType === 'INTRADAY' ? apiMultiplier : 1.
- Order price basis for sizing: LIMIT + valid price use the limit price;
  MARKET uses live LTP (currentPrice).
- maxQuantity = floor(capital * effectiveMultiplier / priceBasis). Clamp/
  reset user quantity when tradeType or orderType changes so it never exceeds
  the new max.
- Outcome gains `orderType: 'MARKET' | 'LIMIT'` and `price?: number` (limit
  price; required when LIMIT). Product/stoploss/target/trailingStoploss/gtt
  unchanged.
- Terminal: `confirmOrder`/`_executeOrder` opts gain `price?: number`;
  `_executeOrder` uses it for LIMIT px instead of snapping to ctx price.
  Both the REST risk path and the feed path already send px as `price`, so a
  LIMIT order with a user price flows through unchanged.
- ChartPane `handleCalcConfirm` passes `outcome.orderType` as the order type
  and `outcome.price` through opts (currently it forwards calcParams.type,
  which is always MARKET - change this).

Files to change: `frontend/src/components/trading/PositionCalculator.tsx`,
`frontend/src/lib/trading/terminal.ts`, `frontend/src/components/trading/
ChartPane.tsx`, `Documentation.md`, `context.md`.

Verification: `npx tsc -b`, `npx vitest run src/lib/trading/terminal.test.ts`,
`npm run build` (re-verify PositionCalculator chunk), then rebuild/commit
frontend/dist and update Documentation.md + this file.

## What this fork adds on top of upstream (feature: Intraday Position Calculator)

The charting terminal's Buy/Sell (One-Click off) opens a Position Calculator
dialog before placing an order. It auto-sizes the quantity from the user's
available capital and the symbol's intraday leverage multiplier, and adds
trade-type and risk controls.

Feature files (all local, verified working):

- `database/intraday_leverage_db.py` - Intraday Leverage DB (1,579 NSE stocks,
  1x/2x/4x/5x multipliers), init + lookup functions.
- `blueprints/intraday_leverage.py` - REST API exposing the multiplier lookup.
- `upgrade/migrate_intraday_leverage.py` - migration + seeds from the Excel
  sheet; registered in `upgrade/migrate_all.py`.
- `frontend/src/components/trading/PositionCalculator.tsx` - the dialog. New
  props/contract in the current head:
  - `onConfirm(outcome: PositionCalculatorOutcome)`
  - Buy/Sell toggle (top-right), Intraday/Overnight/GTT segmented control,
    hidden max-quantity formula, Stop Loss / Target Price / Trailing Stop Loss
    fields, GTT switch.
- `frontend/src/api/intradayLeverage.ts` - API client.
- `frontend/src/components/trading/ChartPane.tsx` - wiring: `onOrderRequest`
  opens the calculator; `handleCalcConfirm` writes qty/product into the
  terminal and calls `terminal.confirmOrder(action, type, opts)`.
- `frontend/src/pages/Holdings.tsx`, `frontend/src/pages/OptionChain.tsx` -
  same calculator, then open PlaceOrderDialog with outcome qty/action.
- `frontend/src/lib/trading/terminal.ts` - `confirmOrder(side, type, opts?)`
  and `_executeOrder(side, type, opts?)`. Risk params route through a SINGLE
  REST `POST /api/v1/placeorder`; otherwise the SocketIO feed path is used.
- `restx_api/schemas.py` - `OrderSchema` extended with `stoploss`, `target`,
  `trailing_stoploss` (float, optional) and `gtt` (bool, default false).
- `services/place_order_service.py` - the four risk keys are popped from
  `order_data` only in the LIVE broker branch (5 adapters forward the whole
  dict and would reject the unknown `gtt` key); sandbox path keeps them as
  metadata and logs preserve them via `original_data`.

## Order flow after the merge (this is the part a fresh agent must know)

Upstream (43 commits merged) redesigned the chart order path with a
One-Click armed/disarmed ticket system (`onOrderTicket` + `PlaceOrderDialog`
+ `buildOrderTicket`/`placeTicket`). Conflict resolution integrated both:

- `placeFromMenu(side, type)` -> always calls `_executeOrder(side, type)`.
  Guards run there, not in the caller.
- `_executeOrder(side, type, opts?)`:
  1. Guards: replay lock, symbol/trade present, quote-only, freeze limit,
     stop-on-wrong-side-of-LTP.
  2. `!opts && !this.armed` (menu click while One-Click is OFF):
     - `cb.onOrderRequest` set -> open the Position Calculator and return.
     - else `cb.onOrderTicket` set -> open the classic PlaceOrderDialog
       ticket and return.
     - else -> toast 'One-Click is off' and return.
  3. Otherwise (armed, or calculator confirm): double-fire cooldown, then
     place. `opts` present (calculator confirm) -> risk params sent via REST
     placeorder; else the normal `trade.place` feed path.
- `confirmOrder(side, type, opts?)` is what the calculator calls; it always
  places (opts present, never bounces to the ticket).
- `ChartPane` registers BOTH `onOrderRequest` (calculator) and
  `onOrderTicket` (ticket); the calculator wins when One-Click is off.
  Armed One-Click clicks still place instantly (upstream behaviour kept).

## Verified state

- Backend schema loads stoploss/target/trailing_stoploss/gtt correctly.
- Frontend `tsc -b` clean; `npx vitest run src/lib/trading/terminal.test.ts`
  -> 53 passed. `npm run build` clean; `PositionCalculator-*.js` chunk
  contains Intraday/Overnight/GTT/Risk Management.
- `frontend/dist` is freshly rebuilt for this merged head and tracks the
  feature. Note: the fork's CI runs a `chore: auto-build frontend dist [skip ci]`
  job that pushes its own rebuild; when a push is rejected, merge fork/main
  (taking their dist), rebuild locally, `git add -A -- frontend/dist` +
  `git add -f -- frontend/dist`, commit, push (`origin` has no such job).

## Not yet done / open items

- User's own idea backlog lives in `task.txt` (repo root) - crypto calculator,
  per-stock news section, vertical candle-drag on the chart, scanners. Ask the
  user which to pick up next rather than guessing.
- Brokers outside Fyers/Zerodha/Dhan/Groww get no brokerage estimate (tariff
  sheet only covers those four). Treatment for trades on other brokers:
  hidden chip / blank column - intentional, per the user's list.
- Live-broker runtime verification of the calculator + Charges column (both
  analyze/sandbox and live mode) - user tests.
- Optional: a future broker adapter could opt back in to consume
  stoploss/target/trailing_stoploss on a plain base order (currently only
  sandbox records them; live brokers place a single-leg order).
- GTT is currently a flag + Overnight product only; full
  `/place_gtt_order` trigger-leg placement is deferred (broker-specific).

## Task list history

1. Position calculator UX: Buy/Sell toggle, Intraday/Overnight/GTT, hidden
   formula, SL/TP/Trailing fields - DONE.
2. Backend risk-param schema + live strip / sandbox passthrough - DONE.
3. Merge 43 upstream commits (agent module, chart ticket redesign, shoonya /
   kotak fixes) - DONE.
4. Rebuild dist, create this file, push to Narasimha722/openalgo_opensource -
   DONE (this task).
5. Calculator leverage gating + Market/Limit order type + 3D UI redesign -
   DONE (this task; summary at top of file).
6. Calculator redesign (stock+LTP header, Price section, Capital/Qty split,
   leverage as a number, Add SL/TP expander) + brokerage fees in calculator and
   order book (Fyers/Zerodha/Dhan/Groww) - IN PROGRESS: implemented and
   verified; commit + push pending. Summary at top of file.
