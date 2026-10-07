# Readiness and Investment Portfolio — complete handoff

**October 7 update:** The user authorized combining the application locally and a Git push. The completed Portfolio is now in the normal frontend build; 407 backend / 20 frontend tests and isolated browser checks pass. The user still starts production. [Release checklist](2026-10-07-local-release-readiness.md). This is the fresh authorization contemplated by §0.4; older deployment-hold statements are historical.

**October 6 current checkpoint:** The user resumed and requested completion. Phases 3–5 are now implemented and verified in lane D, with deployment pending “combine and launch.” Read the [completion handoff](2026-10-06-portfolio-completion.md). Section 0 below remains authoritative; later October 4 status/PID notes are historical, never process targets.

**Checkpoint:** October 4, 2026, approximately 21:40 IST. Section 0 updated later the same evening.  
**Repository:** `/Users/narasimhareddyasam/Downloads/OpenAlgo_Mac`  
**Branch / existing HEAD:** `main` / `2af96f002`, which is now pushed and identical to `origin/main`. That commit and `55a706486` contain the **separate NIFTY options request only** (strategies, tests, backtest outputs, docs) and were pushed at the user's request later on October 4. **All readiness and portfolio work below is still local and uncommitted**: 305 changed/untracked paths, including every new investment file, and 262 of those paths are `frontend/dist` churn — see §8 before staging anything.  
**Work state:** Stopped at the user's request: “give complete handoff notes/documention what we did how we did and stop.” Do not resume implementation until requested.  
**Application state (superseded later on October 4):** the user then asked for **everything OpenAlgo to be stopped so they can restart from a clean state**. All OpenAlgo processes were terminated: the `caffeinate -i uv run --no-sync app.py` wrapper chain (PIDs 15964/15963) and the app server (PID 15965), plus the MCP helpers `mcp/launch_local.py` (82809) and `mcp/mcpserver.py` (88903). `127.0.0.1:5000` and `:8765` are free and no OpenAlgo process remains. **The user, not an agent, restarts the production instance.** See §0 before touching anything.

---

## 0. STANDING ORDER — develop in parallel, never affect the user's OpenAlgo

**This section outranks any older instruction in this file, in the portfolio plan, or in habit.** It applies to every agent, in every session, including a fresh one with no memory of this work. The user runs OpenAlgo for real trading *while* the Investment Portfolio feature is being developed. Two lanes, never mixed:

| Lane | What it is | Owns exclusively |
|---|---|---|
| **P — production** | The OpenAlgo instance the user trades with. **Only the user starts and stops it.** | ports **5000** and **8765**; production databases; `db/nifty_options/`; `strategies/strategy_configs.json`; `log/*.log`; the broker session |
| **D — development** | All Investment Portfolio work in this repo. An agent's workspace. | port **5011** only; `log/test/*.db`; `.development/`; `test/`; new `investment`-named files |

### 0.1 Forbidden without a fresh explicit user request

1. **Never signal an OpenAlgo process.** No `kill`, `pkill`, `killall`, no Ctrl-C into a foreign terminal, nothing aimed at a PID you did not start yourself or at whatever holds 5000/8765. Identify by port, and only ever stop processes *you* launched in lane D. A past agent's PID in a document is stale information, never a target.
2. **Never start the production app** (`uv run --no-sync app.py`, or any `caffeinate`/`uv` wrapper around it) while working. Lane D uses the fixture server on 5011.
3. **Never write to a production database.** `db/openalgo.db`, `db/sandbox.db` and any other `db/*.db`, `db/scanner*`, `db/nifty_options/*`, `db/investment_fyers_reconciliation.json`. Any development process must set `DATABASE_URL` to a file under `log/test/`. Read-only is acceptable; the five production `investment_*` tables stay **empty** until the user says combine.
4. **Never run pytest without its isolation.** `test/conftest.py` forces a unique `PYTHON_STRATEGY_DATA_DIR` under `log/test/`, alive through scheduler atexit callbacks. Do not unset it, do not point it at `strategies/`, and do not run the NIFTY schedule installer even to "verify". A real incident replaced the 20-entry schedule file with a single strategy; read schedules only with `.venv/bin/python .development/monday-readiness/check_saved.py`. If schedules ever show fewer than 20, stop everything and restore from `db/nifty_options/schedules-before-*.json`, then tell the user.
5. **Never touch the user's git state destructively.** No `reset`, `checkout --`, `restore`, `clean`, `stash`, no branch switching. Preserve all local changes. Do not `git add -A` while Vite output is half-staged (see §8) and never commit or push without being asked.
6. **Never rebuild `frontend/dist` while the user's instance serves it**; Vite replaces hashed assets in place. `npm --prefix frontend run test:run` and `run lint` write nothing to `dist` and are safe. A `run build` requires the production instance to be stopped and is done only on user instruction, immediately before a user-approved restart.
7. **Never create sandbox, schedule, strategy, scanner or production investment data.** No broker orders, ever, from any lane. FYERS holdings checks are read-only, print no token, and keep their snapshot local at mode 0600 — never commit private holdings.
8. **Do not ask again** the answered questions: ATHER baseline accepted, existing sandbox integration chosen, FIFO alongside weighted average, categorized paper GTT examples only, empty weekday watchlists, twenty schedules preserved.

### 0.2 Approved lane-D commands

```sh
# isolated fixture app: port 5011, DB log/test/investment-browser.db, no scheduler/broker/sandbox
.venv/bin/python .development/investment/browser_server.py     # restart it to reset its DB
node .development/investment/verify_ui.cjs                     # in a second terminal

# focused tests only (isolation comes from test/conftest.py)
.venv/bin/python -m pytest test/test_investment_ledger.py test/test_investment_api.py -q
.venv/bin/python -m pytest test/test_python_strategy_config_isolation.py -q
.venv/bin/ruff check database/investment_db.py services/investment_service.py blueprints/investments.py
npm --prefix frontend run test:run -- portfolio        # vitest, no dist write
npm --prefix frontend run lint

# read-only production checks, no mutation, no orders
.venv/bin/python .development/monday-readiness/check_saved.py
```

Prefer these over the full backend/frontend suites: ~6,000 backend and ~3,000 frontend tests are slow, and the user's priority is their live instance, not suite breadth. Never run `strategies.nifty_options.live_check` or any FYERS script unless the user asks; they use live broker authentication.

### 0.3 Lane-D log discipline

Record every process an agent starts in `log/dev/` with its PID, port and command, and stop only those on cleanup. Before finishing a session, confirm `lsof -nP -iTCP:5000 -sTCP:LISTEN` shows the user's instance (or nothing, if the user has it stopped) and that no stray 5011 listener remains.

### 0.4 The only path to production — "combine and launch"

Nothing in Phases 3–5 reaches the user's OpenAlgo implicitly. Production changes **only** when the user says so, in this order: user stops the instance → review and stage the complete intended diff (never blind `-A`) → `npm --prefix frontend run build` → user restarts → verify HTTP 200 on `/portfolio` and `/portfolio/stocks`, twenty restored schedules, unchanged sandbox digest `68c24a2f…`, and the five investment tables still empty until the user imports real data. Portfolio code is additive and already deployed once, so a later combine should not require schema migration work.

---

### 0.5 Restarting the user's instance cleanly

The stop was clean, so a fresh start needs no repair: SIGTERM closed the wrapper chain and app server, SQLite had no open writers, and no lock or PID file gates startup. Nothing is left to fix. **An agent must not perform any of these** — they are the user's actions:

- Start with their own command, `caffeinate -i uv run --no-sync app.py`, after checking `lsof -nP -iTCP:5000 -sTCP:LISTEN` is empty.
- Expect the startup line `Restored 20 scheduled strategies` and Monday's 09:15 IST start for all twenty.
- If fewer than 20 schedules appear, do not restart repeatedly: restore `db/nifty_options/schedules-before-20261004-175016.json` and tell the user.
- `/portfolio` and `/portfolio/stocks` exist in the current local build; the MCP helpers on 5000 come back when the user restarts them.
- Data expectations after restart: sandbox digest still `68c24a2f…`, funds ₹5 crore, twenty schedules, weekday watchlists still empty until the user populates them before 09:00.

## 1. What the user authorized and decided

The user required a complete project readiness check before Monday's scheduled trading, followed by implementation of the canonical [Portfolio section plan](2026-10-02-portfolio-section-plan.md). Readiness work was completed first, then the initial investment ledger and Stocks/Dashboard slice was implemented and deployed locally.

Confirmed decisions, preserved across restarts:

- Keep the **20 scheduled strategies**: the original eight stock profiles plus twelve NIFTY options variants. Do not discard or replace the original eight.
- Weekday watchlists may stay empty now. The user will populate the relevant list **before 09:00 daily**. Do not seed them without instruction.
- Portfolio paper trading will use the **existing sandbox engine**, preserving current balances, positions and long-term holdings. This is authorization for the later integration; it is not yet implemented.
- Holdings use **weighted-average cost**, with **FIFO alongside it** for the future Capital Gain Report. FIFO lot math is already implemented; the full capital-gains report is not.
- User wants **paper GTT orders**, categorized by purpose, e.g. SBIN 10 shares Long-term and HDFCBANK 20 shares Swing. These are feature examples, not orders to submit or holdings to create. Prices/triggers must be supplied when creating an order.
- Account names/broker labels are informational in the current slice. Automatic recurring SIP execution has not been authorized; the user's response specified GTT instead.
- On request, checked **FYERS holdings read-only**. FYERS returned success with **zero holdings and zero totals**. No positions were imported and no orders were submitted.
- **Latest acceptance decision:** user explicitly answered **“Accept the ATHER baseline and continue.”** This replaces the old need to reconcile the original three-stock screenshot before Phase 3. The tested ATHER case, including a partial sale, is now the accepted baseline. Do not ask the same gate question again.
- Immediately afterward the user requested this handoff and stop. Thus **Phase 3 is authorized but has not started**. Resume only when the user asks.

The separate frozen roadmap tasks remain frozen: do not resume Task 1 or Tasks 3–5, or change the protected Crypto tree. Task 6 alone was unfrozen. See the [six-task roadmap](2026-09-11-six-task-roadmap.md).

## 2. Readiness outcome and Monday operating state

[Readiness report](2026-10-04-monday-readiness.md) contains the original evidence and the scheduler-isolation incident. Final post-portfolio checks also pass:

| Check | Verified result |
|---|---|
| Saved and restored schedules | 20; final startup explicitly logs `Restored 20 scheduled strategies` |
| Monday next start | October 5, 2026, 09:15 IST for all 20 |
| Original eight stock profiles | NSE, 09:15–15:00; definitions preserved |
| Twelve NIFTY profiles | NFO, 09:15–15:40; entry 09:30, intraday exits 15:20 |
| NIFTY instrument catalogue | 960 contracts; current expiry Oct 6, next expiry Oct 13 |
| Quote connection | Authenticated; read-only subscription accepted |
| Sample broker basket margin | ₹294,105.07, a verification sample, not a fixed margin assumption |
| Nifty500 universe | 500 symbols |
| Weekday watchlists | Empty by explicit user choice |
| SQLite integrity | `quick_check` passed for openalgo, sandbox, scanner and scanner reports DBs |
| Sandbox total capital | ₹50,000,000 (₹5 crore) |
| Available / used margin / realized P&L | ₹50,000,265.28 / ₹0 / ₹265.28 |
| Sandbox automatic reset | `Never` |
| Orders recorded October 4 at final pre-deployment check | 0 |

Before/after portfolio deployment, the full contents of `sandbox_funds`, `sandbox_positions`, `sandbox_holdings`, `sandbox_orders` and `sandbox_trades` had the same combined digest:
`68c24a2f5944a2b6f989332550dc61a1ec530ead6a83fd6b2f2e612ca3c264d9`.
Evidence: `log/test/investment-sandbox-before.sha256` and the deployment verification output.

Latest saved schedule file hash:
`1e4a019acf46cfaee3c50dc4d5278a6a43e49d53fe268f7dc295a8076a71a003`.
The earlier restored/pre-start hash was `fdb25622f3a22a6e9a88aff0472aa224065c48d33e7511efbb40405a7586cc76`; the application later reserialized the file. A semantic comparison confirmed the same 20 definitions and intended NFO/15:40 values, not another fixture overwrite.

Keep the Mac awake and OpenAlgo running, with a valid FYERS login before 09:15. User will populate lists by 09:00. Empty lists yield no candidates for the four weekday-watchlist profiles. These were Sunday/premarket checks; **fresh Monday ticks, broker availability, actual execution/fills, slippage and stop-loss execution have not been proven**. The earlier long-running app logged intermittent DNS/ping failures; the final restart/read-only connection check passed. Do not claim a guarantee of Monday fills or uninterrupted network availability.

## 3. Readiness changes — what and why

### Production or dependency changes

- `blueprints/python_strategy.py`: optional `PYTHON_STRATEGY_DATA_DIR` relocates script/config storage. Production still defaults to `strategies/`. Logs respect `LOG_DIR`. This enables actual isolation of scheduler tests.
- `app.py`: registers existing OpenScript and OpenScript Runner blueprints that previously were not registered. The optional compiled OpenScript engine is not installed on this Mac; none of the twenty scheduled Python strategies depends on it.
- `database/historify_db.py`: five export containment checks now compare resolved paths with `Path.is_relative_to`. Handles macOS `/var` versus `/private/var` symlinks and rejects sibling paths that merely share a text prefix.
- `utils/shutdown.py`: repeated shutdown signals return after shutdown has started, avoiding an interrupt during cleanup.
- `requirements.txt` and `requirements-nginx.txt`: add the already-installed `polars==1.44.2` to match project dependencies.
- `services/agent/tools/chart.py`: indicator-count documentation corrected from 102 to the actual 105.

### Test repairs and isolation

- `frontend/src/test/setup.ts`: explicitly uses jsdom's real local/session storage. Native Node storage was shadowing it and caused hundreds of unrelated frontend failures.
- Navigation expectations corrected to include existing Scanner/Reports; subsequently updated to twelve entries after adding Portfolio.
- `test/test_flow_custom_legs.py`: fixed clock for date-dependent expiry fixtures.
- OpenScript tests: Python 3.13 `pathlib` annotation compatibility; missing optional native engine now causes explicit skips instead of collection failure.
- Telegram startup test: eventlet is an explicit optional skip on this Mac; eventlet was not installed into the main app environment.
- TradeSmart limiter tests aligned with the existing two-budget broker contract. No broker rate-limiter production code was changed.
- `test/conftest.py`: excludes standalone manual broker/order/Telegram diagnostics from automatic pytest collection. They remain available for deliberate operator use; some make real requests or submit orders/notifications, and should not be run as ordinary tests.

### Important incident: a test overwrote the real schedules

The first full-suite run invoked real scheduler `save_configs()` against `strategies/strategy_configs.json`. A test fixture replaced the 20-entry file with one strategy. A restart check caught this immediately by restoring only one schedule.

Recovery performed:

1. Stopped that verification instance.
2. Saved the bad fixture file as `db/nifty_options/readiness-test-fixture-config.json`.
3. Restored the 20-entry backup `db/nifty_options/schedules-before-20261003-190556.json`.
4. Ran the already-authorized NIFTY offline installer to restore final NFO 09:15–15:40 values; its new backup is `db/nifty_options/schedules-before-20261004-175016.json`.
5. Compared the original eight definitions against the earlier backup; they were unchanged.
6. Fixed isolation: pytest forces a unique temporary `PYTHON_STRATEGY_DATA_DIR` under `log/test/`, kept alive through scheduler atexit callbacks.
7. Added `test/test_python_strategy_config_isolation.py`, which calls real save logic. Deliberately pointing it at production makes it fail before any write.
8. Reran the entire suite with the real schedule bytes unchanged, restarted, and verified all twenty restored.

Sandbox funds remained unchanged; no orders were recorded during the incident. Do not rerun old scheduler tests without the isolation fix.

## 4. Portfolio implementation now available

Live local pages:

- `http://127.0.0.1:5000/portfolio` — Investment Dashboard.
- `http://127.0.0.1:5000/portfolio/stocks` — Stocks & ETFs.

Both returned HTTP 200 after deployment; unauthenticated `/investments/api/accounts` returned 401. Full create/edit workflows were exercised against an isolated test database with real routes and CSRF. They were **not** exercised by creating records in the operator's production account. The five production investment tables were created and contained **zero records** at deployment verification.

### Files and responsibilities

| File / directory | Responsibility |
|---|---|
| `database/investment_db.py` | Five additive SQLAlchemy models, independent metadata/session, existing engine factory and initialization helper |
| `services/investment_service.py` | Validation, owner checks, transactional CRUD, weighted-average/FIFO replay, valuations, dashboard and scores |
| `blueprints/investments.py` | Session-authenticated HTTP routes; application CSRF; request cleanup |
| `app.py`, `utils/db_sessions.py` | Blueprint registration, additive startup schema creation, scoped-session cleanup |
| `blueprints/react_app.py` | Serves `/portfolio` and direct `/portfolio/stocks` refreshes; preserves backtester routes |
| `frontend/src/api/investment.ts` | Cookie/CSRF-aware client using existing `webClient`, investment-only query keys |
| `frontend/src/types/investment.ts` | Decimal-string data contracts |
| `frontend/src/pages/portfolio/PortfolioIndex.tsx` | Account selector and add/manage account forms, section navigation |
| `frontend/src/pages/portfolio/Dashboard.tsx` | Cost/value/P&L/income/coverage tiles, scores, allocation |
| `frontend/src/pages/portfolio/Stocks.tsx` | Stock records, watch-only flag, price entry, history, deletion and pagination |
| `frontend/src/components/investment/` | Transaction form, allocation donut, shared presentation/field helpers |
| `frontend/src/App.tsx`, navigation and page-title files | Routes, Portfolio entry, section-only active matching |
| `frontend/src/components/layout/Navbar.tsx` | Bounded horizontal navigation overflow so the additional item does not widen the page |

The existing `portfolio/` backtester, `restx_api/portfolio.py`, its pages and `database/strategy_portfolio_db.py` were not repurposed. The old allocation component is actually a stacked area chart, not the pie described in the original plan; a small SVG investment donut was added instead of changing the backtester component. Existing symbol search was reused. No frontend dependencies were added.

### Persistence and ledger rules

Tables: `investment_accounts`, `investment_assets`, `investment_transactions`, `investment_lots`, `investment_valuations` in the existing OpenAlgo database, created additively. Money uses `Numeric(18,4)`; quantity uses `Numeric(20,6)`; service arithmetic uses `Decimal`. API financial values are decimal strings, with UI formatting only at display time.

- Transactions are the authority; chronological replay orders by date, time and ID.
- BUY includes all six charge fields in cost: brokerage, STT, GST, stamp duty, SEBI, exchange charges.
- Partial SELL leaves weighted-average unit cost unchanged and deducts sale charges from proceeds.
- FIFO lots retain separate cost/quantity/realization; they are rebuilt atomically, not substituted for weighted-average holdings.
- Quantity is derived from replayed lots, never a freely edited holding balance.
- DIVIDEND/INTEREST are explicit cash flows; they do not alter quantity or cost.
- CORPORATE_ACTION currently means explicit split/consolidation: positive new-to-old ratio, quantity 1, price/charges zero, explanatory notes. It preserves cost and rejects fractions beyond six decimal places. Other corporate-action types remain future work.
- Backdated additions and deletions replay all affected transactions. Oversells, including those created by deleting an old purchase, return 409 and roll back.
- SQLite writes use `BEGIN IMMEDIATE` to serialize read/replay/write. A concurrent-sale regression proves two simultaneous sells cannot consume the same available quantity.
- Every account/asset/transaction operation checks the signed-in owner. Accounts with instruments and instruments with transactions cannot be silently deleted. Financial identity cannot change after a transaction exists.
- Watch-only assets create no purchase/lot/cash movement. They must be converted explicitly before recording a transaction.
- All current writes are bookkeeping. **There is no portfolio order placement, GTT monitor or sandbox-funds integration yet.**

Request bounds: at most 50 accounts per user, 100 instruments per user, 10,000 transactions per instrument; history responses cap at 500 rows (UI pages of 50). Numeric precision, finite/nonnegative inputs and supported size bounds are validated.

### Implemented endpoints

All under `/investments/api`, with normal logged-in session and CSRF protection for mutations:

- `GET/POST /accounts`; `PATCH/DELETE /accounts/<id>`.
- `GET/POST /assets`; `PATCH/DELETE /assets/<id>`.
- `GET /holdings`; `GET /holdings/<id>`.
- `GET/POST /transactions`; `DELETE /transactions/<id>`.
- `POST /assets/<id>/price` — explicit manual timestamp with timezone.
- `POST /prices/refresh` — bounded read-only broker quote refresh; optional asset IDs.
- `GET /dashboard` — same holdings calculation used by the UI.

Only `STOCK` (including ETFs) is enabled. `/prices/import`, the nine report endpoints and remaining asset-class operations are **not implemented yet**; the original plan's endpoint list includes future phases.

### Valuation and scoring behavior

- Quote changes never overwrite purchase cost.
- Missing valuations remain unavailable; incomplete coverage does not masquerade as a complete portfolio total.
- Manual prices carry source and date. Quote refresh uses existing authenticated `get_quotes` and retains prior saved values on a broker failure.
- Normalized broker quotes do not guarantee a market timestamp. They are stored as `broker_snapshot` with fetch time and labeled stale/unverified; they are not presented as proven fresh trades. Today's gain remains unavailable without a current provider-timestamped quote and previous close.
- Quality is currently an allocation proxy: `50 × (1 − sum(cost_weight²))`; its remaining defensive-asset component is not available in the stock-only slice.
- Diversification: `min(100, 100 × weight entropy / ln(10))`.
- Momentum: clamp `50 + 500 × weighted 30-day price return − 100 × return standard deviation` to 0–100. Requires a recent price for every holding, a 30–37-day prior price and no intervening split.
- Composite: 40% quality + 30% diversification + 30% momentum, only when all required data exists. Missing history yields unavailable, not a fabricated score.
- Formula is shown in the UI and pinned by a regression. These are allocation measures, not fundamental/company ratings or a recommendation engine.

## 5. Accepted reconciliation and verification evidence

Accepted ATHER case:

1. Buy 100 at ₹1,000 → cost ₹100,000.
2. Value at ₹1,100 → value ₹110,000, gain ₹10,000 (10%).
3. Alternative valuation ₹950 → loss ₹5,000 (−5%).
4. Sell 10 at ₹1,200 → remaining quantity 90, average cost ₹1,000, cost ₹90,000.
5. Value remainder at ₹1,100 → ₹99,000 value, ₹9,000 unrealized gain, ₹2,000 realized gain.

Backend tests also verify charged purchases/sales, divergent FIFO versus weighted average, fractional quantities, restart/session round trips, split basis preservation, missing/stale/fresh prices, account isolation, CSRF, duplicate rejection, backdated rebuilds and concurrent oversell rejection.

| Verification | Result / evidence |
|---|---|
| Readiness full backend before portfolio | 5,932 passed, 28 skipped, 1 xfailed; `log/test/readiness-backend.log` and XML |
| Readiness frontend before portfolio | 2,956 tests, 194 files passed; `log/test/frontend-readiness.log` |
| Scheduled strategy families | 114 passed; `log/test/readiness-strategies.log` |
| Full backend with initial portfolio implementation | **5,961 passed**, 28 skipped, 1 xfailed, 11 warnings; `log/test/investment-full-backend.log` and XML |
| Full frontend with portfolio | **2,962 tests**, 195 files passed; `log/test/investment-full-frontend.log` |
| Final focused backend after precision/ID checks and SPA deep-link registration | **30 passed**; `log/test/investment-backend-final.log` |
| Final focused UI/navigation after accessible-label/layout fixes | **21 passed**, 3 files; `log/test/investment-frontend-final.log` |
| Production TypeScript/Vite build | Passed; `log/test/investment-build.log`; existing large-bundle warning remains |
| Frontend lint | Exit zero; four existing warnings, two infos; `log/test/investment-lint.log` |
| Scoped backend Ruff and whitespace | Passed on new feature files; existing app/Historify lint baseline not broadly reformatted |
| Ownership mutation check | Removing owner predicate in memory makes the real ownership test fail; `log/test/investment-mutation.log`; source never changed |
| Resource checks | 100 repeated success/failure service cycles left no scoped session registered; static review of bounded request collections, NullPool and cleanup paths. Not a full RSS/descriptor production soak |
| Browser workflow | Real isolated ledger + CSRF + SQLite; all expected figures, persistence, forms, cost/value charts, desktop/mobile overflow and zero page errors passed |
| Final production deployment | Pages HTTP 200, unauthenticated ledger 401, five additive tables and zero investment records, twenty schedules restored, sandbox digest unchanged |

The full suites preceded the last small fixes; final focused suites cover those fixes. Do not misrepresent the full-suite count as a later rerun of the exact final tree. Optional-engine skips and the existing thread warning are not passes for their untested areas.

Browser artifacts (synthetic fixture, not actual holdings):

- [Verification JSON](../../.development/investment/artifacts/browser-verification.json).
- [Desktop Dashboard](../../.development/investment/artifacts/dashboard-desktop.png).
- [Mobile Dashboard](../../.development/investment/artifacts/dashboard-mobile.png).
- [Mobile Stocks](../../.development/investment/artifacts/stocks-mobile.png).

## 6. Reproduction helpers and safeguards

From repository root:

```sh
.venv/bin/python -m pytest test/test_investment_ledger.py test/test_investment_api.py -q
.venv/bin/ruff check database/investment_db.py services/investment_service.py blueprints/investments.py
npm --prefix frontend run test:run
npm --prefix frontend run build
npm --prefix frontend run lint
.venv/bin/python .development/monday-readiness/check_saved.py
.venv/bin/python -m strategies.nifty_options.live_check
```

The last command uses current broker authentication and network access but submits no orders. Do not invoke the schedule installer simply to check readiness; `check_saved.py` verifies saved definitions without mutation.

Browser test reproduction:

```sh
.venv/bin/python .development/investment/browser_server.py
# In a second terminal:
node .development/investment/verify_ui.cjs
```

The fixture server binds **5011**, uses **`log/test/investment-browser.db`**, explicitly disables dotenv via the test setup, and drops/recreates only its own five investment tables on startup. It serves the compiled frontend and real investment/CSRF routes with a synthetic signed-in user. It does not load the production app, broker adapter, sandbox or scheduler. **Restart the fixture server to reset its database before rerunning the browser test**; the workflow creates records. Stop only this fixture process afterward, never the user's production instance (§0).

- `.development/investment/verify_regression.py`: ownership predicate mutation test; expected nested pytest failure means the outer checker passes.
- `.development/investment/read_fyers.py`: read-only FYERS holdings snapshot with existing saved login. No token printed, no import/order. Snapshot `db/investment_fyers_reconciliation.json` is mode 0600 and newly ignored by git. It was empty when checked; never commit future private holdings data.
- `.development/monday-readiness/check_saved.py` / `saved_checks.json`: schedules, Monday timing, catalogue/watchlist, funds and integrity checks. Monday date is deliberately fixed to Oct 5, 2026; update intentionally for a future readiness exercise.
- `log/investment-startup.log`: final app startup; `log/monday-readiness-startup.log`: earlier readiness instance and subsequent network history.
- `backtest/nifty_options/verification/live_checks.json`: latest post-restart read-only verification.

## 7. Remaining authorized work — not done yet

**Pending size, stated plainly:** Phases 1 and 2 are complete and deployed. Three phases remain, all unstarted, plus four hardening items. In units: **8 further asset classes**, **all 9 reports**, **2 integration surfaces (categorized watchlists, paper GTT on the existing sandbox)**, plus CSV price import and the verification/labeling items below. Phases 1–2 were the largest build; Phases 3–4 are largely repetitive per-class and per-report work built on the finished ledger, and Phase 5 is the only one that touches existing shared state (`database/sandbox_db.py`). Nothing in the pending list is started; there is no partial Phase 3 code in the tree.

The user's ATHER acceptance resolves the old gate. On a future resume, working in lane D only (§0):

1. **Phase 3:** implement remaining classes, per-class metadata/forms, manual NAV/price updates and atomic CSV imports. Net `LOAN` and `OTHER_BORROWING` as liabilities throughout summaries/allocation. Validate MF fractional SIP/redemption math. The original plan says “ten classes” but enumerates nine enum values because Stocks/ETFs are combined; preserve this distinction rather than inventing an extra class.
2. **Phase 4:** implement all nine reports: Transaction History, Dividend, Corporate Action, Performance, Holding, Capital Gain, P&L, Transaction Calendar, Consolidated Holding. Current stock history is a working transaction list, not completion of all report pages. Use the same valuation service; implement explicit FIFO realization reporting and safe CSV export. Do not describe current weighted-average totals as tax-grade reports.
3. **Phase 5:** categorized watchlists and paper GTT orders integrated with the existing sandbox, with clear trigger/order/quantity semantics, restart-safe monitoring and reconciliation. Preserve current balances and long-term holdings. Do not duplicate balances or create a second paper engine. No automatic recurring SIPs or live broker orders are authorized by the feature examples.
4. Continue date/source labeling. Consider adding verified provider timestamps through the appropriate quote interface before promising live daily P&L. Never infer missed offline GTT/SL/TP events from a single current LTP.
5. Extend scoring only with reproducible inputs. Add report/corporate-action coverage as those phases are implemented. No generic corporate-action processing beyond split/consolidation currently exists.
6. Review and verify each phase; update the canonical plan and this handoff. Avoid repeated broad tests after passing unless a new change or unresolved concern warrants them.

No implementation of Phase 3, full report suite or paper GTT integration was started after the latest approval because the user immediately requested this handoff and stop.

## 8. Repository and artifact handling

Preserve all local changes. No commit, push, reset, clean or unrelated worktree operation was performed for the readiness/portfolio work; the only later commits are the two NIFTY-only pushes named in the header. The app uses the locally built frontend. **305 local paths are uncommitted, 262 of them `frontend/dist`** — an agent must not "tidy" these away.

**Generated frontend caution:** Vite replaced old hashed assets in `frontend/dist/`. Some old dist files are tracked despite the directory being gitignored, so `git status` shows many deleted old bundles and a changed index; replacement bundles exist locally but may be ignored. Do not blindly commit/push only those deletions/index or assume `git add -A` includes the replacements. Follow the repository's build-artifact policy, either reproducibly rebuilding in delivery/CI or explicitly reviewing/staging the matching complete build. Do not delete or restore the running build casually, and do not rebuild it while the user's instance is serving (§0.1 item 6).

Evidence logs, databases, snapshots and test fixtures are not production user records to import. All browser sample holdings remain in the isolated test DB; production investment tables are empty.

The prior NIFTY request remains complete locally: [combined three-month dashboard](../../backtest/nifty_options/2026-07-03_2026-10-01/results/combined_dashboard.html), 12 variants / 24 modeled paths / 64 sessions / 2,428 closed legs. This session did not rerun those historical simulations. All future backtest outputs belong under `backtest/`, not application Reports. Earlier existing Reports records remain preserved.
