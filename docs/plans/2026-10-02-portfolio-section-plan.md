# Portfolio Section — Implementation Plan

**Status:** Phase 0 complete (decisions locked, plan written). Implementation not started.
**Created:** 2026-10-02
**Roadmap task:** Task 6 — "Sandbox investment watchlists and portfolio tracking"
([`2026-09-11-six-task-roadmap.md`](2026-09-11-six-task-roadmap.md):1482). **Unfrozen** by the
user on 2026-10-02; the September 12 freeze on Tasks 3–6 is superseded for T6 only.
**Supersedes the T6 scope in the roadmap** — this plan is broader (10 asset classes with full
read/write, reports, scoring and charts, vs. the roadmap's 4 watchlist styles and no transactions).

---

## 0. Legend

- **Files** — new (N) vs edited (E).
- **Acceptance** — hard gates; a phase is not done until every item passes.
- **Exit** — the state the codebase is left in.

Phases ship independently. Each ends in a working state; nothing half-built persists.

---

## 1. Problem statement

OpenAlgo currently has no way to track *actual* personal investments. The existing `portfolio/`
package and `/api/v1/portfolio` namespace are a **portfolio backtester** — they run a strategy
over historical candles and report tearsheets. Nothing reads or writes a user's own holdings.

The requested feature is an Investment Portfolio section covering ten asset classes:

| Class | Enum value | Pricing source |
|---|---|---|
| Stocks / ETFs | `STOCK` | Live broker quote |
| Mutual Funds | `MUTUAL_FUND` | Manual NAV + CSV import |
| ULIPs | `ULIP` | Manual NAV + CSV import |
| Fixed Income | `FIXED_INCOME` | Manual (coupon/accrual) |
| Bullion | `BULLION` | Manual (spot is not an exchange symbol) |
| Property | `PROPERTY` | Manual (appraisal) |
| Loans | `LOAN` | Manual (outstanding principal) — a **liability** |
| Other Assets | `OTHER_ASSET` | Manual |
| Other Borrowings | `OTHER_BORROWING` | Manual — a **liability** |

Read **and** write: the user records buys/sells/dividends with a timestamp, and the system derives
open lots, weighted cost, realized/unrealized P&L, invested amount, market value, return and days
held. It must never overwrite entry cost with a current quote.

---

## 2. Decisions locked (Phase 0)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 0.1 | Task 6 is frozen in the roadmap | **Unfreeze and implement** | The user's 2026-10-02 request is a direct instruction that supersedes the 2026-09-12 freeze. Roadmap status and `AGENTS.md` updated. |
| 0.2 | Where does the code live? | **`investment` / `investments` namespace** | `/api/v1/portfolio`, `portfolio/`, `src/api/portfolio.ts`, `/portfolio` and `database/strategy_portfolio_db.py` are all taken by the backtester. Only the user-facing route reclaims `/portfolio`. See §3. |
| 0.3 | Pricing for non-stock assets | **Manual price + `price_as_of` date, plus CSV import** | There is **no** AMFI/mfapi/NAV provider anywhere in the codebase today (verified). Adding one would add a network dependency and MF NAV is daily-only, so "today's gain" would be unavailable anyway. Manual entry is honest and offline-safe. CSV import covers bulk updates from an AMFI statement. |
| 0.4 | Delivery sequence | **Phase 1 = ledger + Dashboard + Stocks, then widen** | Proves the whole engine end-to-end before 9 more asset pages are built on it. |
| 0.5 | Cost basis / realization policy | **Weighted average cost** | Matches Indian broker holdings screens (Zerodha/Groww/Kuvera) and matches the user's own holdings table, which shows one `Per Unit Cost` per stock rather than per-lot cost. |
| 0.6 | Realized P&L for tax reports | Deferred to Phase 4 | Weighted average is not valid for Indian capital-gains tax reporting. The Capital Gain Report needs FIFO. Tracked as a Phase 4 decision, not silently conflated. |
| 0.7 | Multiple accounts | **Yes, first-class from Phase 1** (`investment_accounts`) | The UI already shows a "My Accounts / Add·Manage / All" bar. Retrofitting multi-account later would require a data migration of every transaction. |

---

## 3. Naming collisions — the constraint that shapes every path

Verified against the working tree on 2026-10-02.

| Taken by | What it is | How we avoid it |
|---|---|---|
| `restx_api/portfolio.py` → `/api/v1/portfolio` | Portfolio **backtester** RESTX namespace (`PortfolioBenchmarks`, `PortfolioBacktest`, `PortfolioTearsheet`, `PortfolioHoldings`), registered at `restx_api/__init__.py:77` | New CRUD is a **Flask blueprint**, not a RESTX resource |
| `portfolio/` (14 modules: `analytics.py`, `costs.py`, `holdings.py`, `engine.py`…) | Backtester engine | New code is `services/investment_service.py` |
| `frontend/src/api/portfolio.ts` (512 lines) | Backtester API client | New client is `src/api/investment.ts` |
| `frontend/src/pages/PortfolioBacktester.tsx`, `PortfolioBacktesterResults.tsx` | Backtester pages | Untouched; keep `/portfolio-backtester` |
| `frontend/src/App.tsx:211-214` — `/portfolio` redirects to `/portfolio-backtester` | The redirect exists *only* because the path was unused-but-ambiguous next to the analyzer (per its own comment) | **Remove** the redirect; `/portfolio` becomes the new section index. `/portfolio-backtester` keeps working. |
| `database/strategy_portfolio_db.py` (`strategy_portfolio` table) | Option legs for strategies — unrelated despite the name | Not touched |
| `database/sandbox_db.py` (`sandbox_orders`, `sandbox_trades`, `sandbox_positions`, `sandbox_holdings`, `sandbox_funds`) | Existing paper-trading engine | Phase 5 wires **into** it rather than duplicating — see §9 |
| `src/config/navigation.test.ts:13` asserts `navItems` has length **9** | Nav test | Bump to 10 in Phase 2 |

React Router matches by exact segment count, so `/portfolio/stocks` does not collide with the
backtester's `/portfolio-backtester`.

---

## 4. Phase 1 — Schema, ledger engine, API

**Goal:** the full engine, proven by tests, with no UI. If the ledger math is wrong, nothing
downstream is salvageable.

### Files

| File | Action |
|---|---|
| `database/investment_db.py` | **N** — models + `init_db()` |
| `services/investment_service.py` | **N** — ledger math, valuation, scoring |
| `blueprints/investments.py` | **N** — session-authenticated HTTP layer |
| `utils/db_sessions.py` | **E** — register the new `scoped_session` (line 22–49 list) |
| `app.py` | **E** — import + register blueprint (near line 272); add to `db_init_functions` (line 744–773) |
| `test/test_investment_ledger.py` | **N** |
| `test/test_investment_api.py` | **N** |

### 4.1 `database/investment_db.py`

Mirrors `database/watchlist_db.py` exactly — `create_db_engine()` (SQLite + NullPool +
`check_same_thread=False`), its own `scoped_session`, `Base`, `init_db()` delegating to
`database/db_init_helper.init_db_with_logging`. **There is no Alembic** in this repo; tables are
created by `create_all` at boot and only missing tables are added, so this is additive and safe.

Column types, non-negotiable:

- All money → `Numeric(18, 4)`
- All quantities → `Numeric(20, 6)` (fractional mutual-fund units)
- No `Float`. Float money in a ledger is a rounding bug waiting for a reconciliation.

| Table | Columns |
|---|---|
| `investment_accounts` | `id`, `user_id`, `name`, `broker_label`, `kind` (`live`\|`paper`), `created_at`, `updated_at` |
| `investment_assets` | `id`, `user_id`, `account_id`, `asset_class`, `name`, `symbol`, `exchange`, `scheme_code`, `price_source` (`live`\|`manual`), `manual_price`, `price_as_of`, `notes`, `is_watch_only`, `created_at`, `updated_at` |
| `investment_transactions` | `id`, `user_id`, `asset_id`, `action`, `quantity`, `price`, `brokerage`, `stt`, `gst`, `stamp_duty`, `sebi`, `exchange_charges`, `trade_date`, `trade_time`, `notes`, `created_at` |
| `investment_lots` | `id`, `asset_id`, `opened_at`, `quantity_remaining`, `cost_per_unit`, `quantity_closed`, `realized_gain`, `status` |
| `investment_valuations` | `id`, `asset_id`, `price`, `as_of`, `source`, `created_at` |

`action` ∈ `BUY`, `SELL`, `DIVIDEND`, `INTEREST`, `CORPORATE_ACTION`.
`asset_class` ∈ the ten values in §1.

**Design rule: a holding's quantity is never stored as a mutable balance.** It is derived from
`investment_lots`. A single code path handles every asset class and there is no way for a balance
to drift from its transactions.

The user's note — *"Investment costs include all charges mentioned while entering transaction"* —
is why charges are first-class columns rather than a single opaque total.

### 4.2 Ledger math (`services/investment_service.py`)

Weighted average (decision 0.5). `charges_per_unit = total_charges / quantity`.

```
BUY:
  avg' = (qty·avg + q·(price + charges_per_unit)) / (qty + q)

SELL (partial):
  realized_gain += (price − charges_per_unit − avg) · q
  qty           −= q
  avg            = unchanged

DIVIDEND / INTEREST:
  realized_gain += amount          (cash flow, no change to qty or avg)

CORPORATE_ACTION:
  adjustment is explicit and visible; it never silently rewrites cost
```

Invariants the tests must enforce:

1. Cost is never overwritten by a current quote.
2. `sum(lot.quantity_remaining) == asset quantity` after any transaction sequence.
3. A partial sell leaves `avg` unchanged.
4. An over-sell is rejected (HTTP 409), never clamped.
5. Fractional units round-trip exactly (`Numeric(20,6)`).
6. Charges raise cost basis, and a sell's charges reduce proceeds.

### 4.3 Valuation

- **Stocks** resolve through `services/quotes_service.get_quotes` (existing broker quote path,
  `services/quotes_service.py:157`). Each result carries a `price_as_of`.
- **Everything else** uses `manual_price` and is displayed with `price_as_of` and an explicit
  "manual" label.
- `today's_gain` is computed **only** for live-priced assets. Manual assets show
  change-since-last-update and say so, rather than pretending to have a daily move.
- A live quote older than a staleness threshold is labeled stale, not silently used.

### 4.4 Portfolio score

`Quality`, `Momentum`, `Diversification`, each 0–100, plus a weighted composite. **The algorithm
is written down here and unit-tested — no unexplained magic numbers.**

- *Quality* — per holding: concentration in the top few names, single-asset-class dependency,
  low-volatility share of the book.
- *Momentum* — trailing return dispersion across holdings, weighted by position size.
- *Diversification* — number of distinct asset classes and distinct instruments, plus evenness of
  weights (entropy-based, not a simple count).

Exact thresholds are pinned by tests. A score that cannot be reproduced from the inputs is a
score that cannot be trusted.

### 4.5 HTTP layer (`blueprints/investments.py`)

Session-authenticated with `@check_session_validity`, copied from `blueprints/watchlist.py:35-47`.
Session-auth rather than API-key-auth because these are the signed-in user's own records read from
the browser they are already authenticated to — same reasoning as the watchlist blueprint.

Routes under `/investments/api/…`:

```
GET    /accounts                      POST   /accounts
PATCH  /accounts/<id>                 DELETE /accounts/<id>
GET    /assets                        POST   /assets
PATCH  /assets/<id>                   DELETE /assets/<id>
GET    /holdings                      GET    /holdings/<id>
GET    /transactions                  POST   /transactions
DELETE /transactions/<id>
POST   /prices/import                 (CSV bulk NAV/price update)
GET    /dashboard                     (all summary numbers + score + allocation)
GET    /reports/<name>
```

### 4.6 Acceptance

- `uv run pytest test/test_investment_ledger.py test/test_investment_api.py` — pass
- `uv run ruff check` — clean on changed files
- All six invariants in §4.2 covered by an explicit test
- Buy 100 ATHER @ ₹1,000 → invested ₹1,00,000; @ ₹1,100 unrealized +₹10,000 (+10%);
  @ ₹950 unrealized −₹5,000 (−5%) — the roadmap's acceptance example (line 1490)
- Schema is additive: existing watchlists, sandbox tables and history untouched

### 4.7 Exit

Tables created at boot, ledger math proven, endpoints live. No UI. The app runs unchanged apart
from one new blueprint and one new set of tables.

---

## 5. Phase 2 — Frontend: Dashboard + Stocks

**Goal:** the user's actual spec on screen, for Stocks only.

### Files

| File | Action |
|---|---|
| `src/api/investment.ts` | **N** — client + query-key factory |
| `src/types/investment.ts` | **N** — shared types |
| `src/pages/portfolio/PortfolioIndex.tsx` | **N** — section index |
| `src/pages/portfolio/Dashboard.tsx` | **N** — Investment Dashboard |
| `src/pages/portfolio/Stocks.tsx` | **N** — holdings + transaction form |
| `src/components/portfolio/AddTransactionDialog.tsx` | **N** |
| `src/components/portfolio/AllocationChart.tsx` | already exists — reuse |
| `src/App.tsx` | **E** — 3 lazy routes; **remove** the `/portfolio` redirect (211–214) |
| `src/config/navigation.ts` | **E** — add nav item (40–52) |
| `src/config/navigation.test.ts` | **E** — `navItems` length 9 → 10 |
| `src/hooks/usePageTitle.ts` | **E** — 3 entries |
| `src/hooks/useProfileMenuItems.ts` | **E** — optional broker-capability gating |

### 5.1 Stack — no new dependencies

React 19 · Vite 8 · TypeScript 7 (strict) · Tailwind 4 · shadcn/ui · TanStack Query v5 · Zustand ·
React Router 8 · Biome.

**Charts: reuse what is installed.** No recharts, no chart.js in this repo, and none will be added.

| Need | Use | Why |
|---|---|---|
| Allocation pie | `src/components/portfolio/AllocationChart.tsx` | Already a hand-rolled SVG pie with hover |
| Performance line | `src/components/portfolio/PortfolioLineChart.tsx` | `openalgo-charts` + theme |
| Monthly/weekly returns | `MonthlyReturnsHeatmap.tsx`, `WeeklyReturnsHeatmap.tsx` | CSS-grid heatmaps already exist |
| Anything else | `src/lib/Plot2D.tsx` | Plotly, but only via the wrapper (Vite 8 CJS interop) |

### 5.2 Patterns to copy

- **Dashboard stat tiles** → `src/pages/PortfolioBacktesterResults.tsx:33-61` (`Stat`)
- **Holdings table** → `src/pages/Holdings.tsx:330-430` (right-aligned `font-mono` numerics,
  `TableFooter` totals, P&L colored via `cn(..., isProfit(x) ? 'text-green-600' : 'text-red-600')`)
- **Query + mutation + invalidate** → `src/pages/flow/FlowIndex.tsx:555-601`
- **Add/edit dialog with form** → `src/components/agent/config/AddModelDialog.tsx:366-602`
  (`useId()` for field ids, reset on open, disabled-while-pending, inline error)
- **Explicit `isError` branch** → `FlowIndex.tsx:666-682`. Without it a failed fetch silently
  shows the cheerful empty state. Copy this.
- **Toasts** → `showToast.success/error/warning(msg, 'category')` from `@/utils/toast`, never raw `toast()`

### 5.3 ⚠️ Navigation gotcha

`isActiveRoute` is **exact-match only** (`src/config/navigation.ts:103-105`), and
`navigation.test.ts:95-100` explicitly asserts that `/dashboard/sub` must **not** light up
`/dashboard`. A `/portfolio` nav item using the existing helper will therefore **not stay
highlighted** on `/portfolio/stocks`.

The fix must add prefix matching for this entry **only**, leaving the Dashboard assertion intact.
A section-local nav (the `/admin`, `/logs`, `/telegram` pattern) is the alternative.

### 5.4 The transaction form

Fields per the user's spec: Action (Buy/Sell/Dividend) · Stock Name (symbol search) · Exchange ·
Date · Quantity · Price/Stock · Amount (derived) · Select Broker · Total Charges (with
Detailed Charges breakdown) · Net Amount (derived) · Notes · Add SIP for this Stock · +Add More
Transactions.

Requirements it must satisfy:

- **Timestamp every buy and sell** — the explicit requirement: *"it has to timestamp when user
  bought when sold"*. `trade_date` + `trade_time`, both non-null.
- Charges allocate into the ledger's per-charge columns, not one opaque blob.
- Validation before submit; server re-validates. An over-sell returns 409.

### 5.5 Acceptance

- `npm run typecheck && npm run lint && npm run build` — clean
- `npm run test:run` — nav count updated, all existing tests still pass
- Reproduces the user's example exactly: ₹2,12,232 cost → ₹2,27,823 value → ₹15,591 (7.35%)
  unrealized; today's −₹2,974 (−1.29%); 2 of 3 in profit (₹17,561, 8.7%), 1 in loss (−₹1,971,
  −19%); Ather highest profit ₹15,871 (12.72%), Nitco highest loss −₹1,971 (−18.97%)
- Allocation pie renders for both cost and latest value
- Live prices refresh; a broker failure degrades to last-known price **labeled stale**, never a
  blank screen

---

## 6. Phase 3 — Remaining nine asset classes

Once the ledger is generalized, each additional class is: one enum value + per-class form fields +
price-source labeling. The engine does not change.

Order of implementation, by how often they are actually used:
`MUTUAL_FUND` → `FIXED_INCOME` → `BULLION` → `ULIP` → `PROPERTY` → `OTHER_ASSET` →
`LOAN` → `OTHER_BORROWING`.

Two classes are **liabilities** (`LOAN`, `OTHER_BORROWING`) and must be netted against assets in
every summary and allocation view, with weights that can go negative. Getting this wrong silently
overstates net worth.

Mutual funds: fractional units, dated NAV, multiple SIP purchases and redemptions without
rewriting history. MF SL/TP are **NAV watch thresholds, not intraday executable stops** (roadmap
line 1494). ETFs on an exchange are priced live and belong under `STOCK`, not `MUTUAL_FUND`.

CSV import (`POST /prices/import`) accepts `symbol,scheme_code,price,as_of` rows for bulk NAV
updates from an AMFI statement. All rows validated and rejected together on any bad row — a partial
NAV import is worse than none.

### Acceptance

- All ten classes add, edit, value and report correctly
- Liabilities net correctly in every total
- Fractional MF units survive buy → SIP → partial redemption → sell exactly
- MF staleness is labeled, not hidden

---

## 7. Phase 4 — Reports

The user's nine: Transaction History · Dividend Report · Corporate Action · Performance Report ·
Holding Report · Capital Gain Report · Profit & Loss Statement · Transaction Calendar ·
Consolidated Holding.

Consolidated Holding is the important one: the roadmap requires identical web/mobile valuation
(line 1498), so it must read the same service function the dashboard does, never a parallel
implementation.

**⚠️ Decision 0.6 resurfaces here.** Weighted average (decision 0.5) is valid for a holdings screen
but **not** for Indian capital-gains tax reporting, which needs FIFO. The Capital Gain Report must
either implement FIFO alongside weighted average, or say clearly that it is not tax-grade. It
must not quietly present weighted-average P&L as a capital-gains figure.

### Acceptance

- Each report matches the on-screen holdings row for row
- CSV export via `sanitizeCSV` from `@/lib/utils`
- Capital Gain Report states its realization policy explicitly

---

## 8. Phase 5 — Watchlists & paper trading

The user's ask: *"under stocks user can create watchlist of stocks like swing trading, long term,
ETFs… under this they can add stocks demo buy/sell for paper trading."*

Roadmap T6 (line 1484) requires named watchlists categorized Swing / Positional / Long-term /
Mutual Funds, and — critically — that a **symbol-to-watch is kept separate from a recorded
purchase**. `investment_assets.is_watch_only` carries this. Watching a stock must never create a
lot, move money, or imply ownership.

**⚠️ Requires a decision before coding.** Paper trading overlaps `database/sandbox_db.py`, which
already has `sandbox_orders`, `sandbox_trades`, `sandbox_positions`, `sandbox_holdings` and
`sandbox_funds`. The options are: wire portfolio paper trading into that engine, or build a
separate ledger. Wiring in is the recommendation — reusing a proven engine beats a second one —
but it needs the user's confirmation because it affects the existing sandbox reset behavior.

Two hard rules from the roadmap that survive into this phase:

- SL/TP default to **tracking/alert-only**. A recorded purchase never places a broker order, spends
  live cash, or resets the intraday sandbox balance (line 1492).
- Long-lived portfolios are **preserved** by the existing sandbox reset action by default; reset
  or archive is opt-in and must say which it is (line 1496).
- Restart/offline monitoring cannot prove a missed threshold from current LTP alone. Show
  history-derived events with their source, or label them unknown (line 1492).

---

## 9. Sequencing summary

| Phase | Scope | Gate |
|---|---|---|
| 0 | Decisions + plan | ✅ Done — this document |
| 1 | Schema, ledger, API, tests | Ledger math proven against the ATHER example |
| 2 | Dashboard + Stocks + transactions + charts | Reproduces the user's exact figures |
| 3 | Other nine asset classes | Liabilities net; MF fractions exact |
| 4 | Nine reports | Consistent with holdings; Capital Gain policy explicit |
| 5 | Watchlists + paper trading | ⚠️ Blocked on the sandbox-integration decision (§8) |

Each phase is independently valuable and independently mergeable. Do not start Phase 3 before
Phase 2's numbers reconcile against the user's own figures — the ledger is the foundation, and
every asset class inherits its bugs.

---

## 10. Repository boundary

- Only `investment`-named files are new, plus the four narrow edits in §4.1/§5.1.
- The backtester (`portfolio/`, `restx_api/portfolio.py`, `PortfolioBacktester*`) is **untouched**.
- `database/strategy_portfolio_db.py` and `database/sandbox_db.py` are untouched until Phase 5.
- Existing watchlists, sandbox history, strategies, scans and schedules are preserved.
- No live order is ever placed by this feature. No schedule is modified.

## 11. Verification commands

```bash
# Backend
uv run pytest test/test_investment_ledger.py test/test_investment_api.py
uv run ruff check database/investment_db.py services/investment_service.py blueprints/investments.py

# Frontend
cd frontend && npm run typecheck && npm run lint && npm run build
cd frontend && npm run test:run
```

Note: `test/conftest.py` creates `db/*-test.db` files and writes to `log/test/`. That is expected
test behavior, not a side effect to guard against.

---

## 12. Open questions for the user

1. **Paper trading** — wire into the existing `sandbox_db` engine, or a separate ledger? (§8)
2. **Capital Gain Report** — implement FIFO alongside weighted average, or ship the report labeled
   as not tax-grade? (Decision 0.6, §7)
3. **Account kinds** — `kind` is `live`/`paper`. Should accounts carry a broker link, or stay
   informational labels like "Zerodha · Groww · Manual"?
4. **SIP** — the Stocks form has "Add SIP for this Stock". A recurring schedule implies a future
   date and an execution model. Is a SIP schedule in scope, or is the button Phase 6?