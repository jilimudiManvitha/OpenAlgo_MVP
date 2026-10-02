# Features Implemented in This Fork

This document captures all features, improvements, and fixes implemented in this OpenAlgo fork (from the start of this work). It serves as a complete changelog for what was built and why.

---
## 1. Scanners, Screeners, Top Gainers/Losers

### Scanner Engine Hardening
- **Pacing control**: Added batch pacing (~1.25s delay between scanner batches) to reduce request bursts.
- **Retry cleanup**: Removed nested scanner-only retries; server Retry-After headers are now preserved.
- **Cancellable cooldowns**: Implemented cancellable cooldown windows to prevent retry storms under throttling.

### Subscription Worker Resilience
- **State tracking**: Tracks `pending`, `retrying`, `dispatched`, `rejected`, and `failed` states for subscriptions.
- **Retry-After compliance**: Honors `Retry-After` responses and backs off appropriately.
- **Stale retry cancellation**: Cancels stale retries on teardown to avoid leaks.
- **Clean recovery**: Recovers gracefully from transient failures without spamming retries.

### Symbol-Token Fetching (FYERS)
- **Pooled/paced HTTP**: Bounded, paced requests with pooling to reduce burst pressure.
- **Bounded request sizes**: Prevents oversized batches from overwhelming the provider.
- **Correct failure classification**: Fixed false "invalid symbol" classification by properly separating service/JSON/auth failures from genuinely invalid symbols.

### Top Gainers / Top Losers / Volume Shockers (FYERS)
- **Backend implemented**: API/backend support for Top Gainers, Top Losers, and Volume Shockers (FYERS provider). Committed.
- **UI pending**: Frontend UI for these lists remains deferred (per backlog).

### Scanner Startup Timing Fix
- **Correct initialization order**: Moved scanner initialization after proxy integration.
- **Bounded listener-readiness wait**: Added a bounded readiness wait for the threaded local proxy to eliminate the startup race where subscriptions fired before the local WebSocket proxy was ready.

**Impact**: More stable scans under throttling, fewer false failures, and cleaner startup sequencing.

---

## 2. Position Calculator (Intraday Leverage + Risk)

Major addition to the charting/order workflow.

### Intraday Leverage DB + API
- **Database**: `database/intraday_leverage_db.py` with 1,579 NSE stocks and multipliers (1x, 2x, 4x, 5x).
- **Seeding**: Excel-based migration via `upgrade/migrate_intraday_leverage.py` (registered in `upgrade/migrate_all.py`).
- **API**: Exposed via `blueprints/intraday_leverage.py` for runtime lookup.

### Intraday-Only Leverage Gating (Task 5)
- **Gating rule**: Effective leverage applies **only to INTRADAY**. `OVERNIGHT` and `GTT` use 1x (capital/price only).
- **Sizing basis**: Uses LIMIT price when a valid LIMIT is selected; otherwise uses live LTP.
- **Quantity formula**: `maxQuantity = floor(capital * effectiveLeverage / priceBasis)`. Quantity auto-clamps when trade/order type changes.

### Market vs LIMIT Order Type (Task 5)
- **Selector**: Added MARKET/LIMIT order type in the calculator.
- **LIMIT validation**: Requires a valid limit price with guard/confirmation (BUY must be below/at LTP logic per guard; SELL above LTP as applicable). Rejects/blocks invalid limit placement with explanation.
- **Outcome contract**: Calculator outcome now carries `orderType: 'MARKET' | 'LIMIT'` and optional `price?: number` (limit price when LIMIT).

### 3D Glass UI Redesign (Task 5)
- **Visual redesign**: Rebuilt Position Calculator with raised/inset tiles, glass gradients, and glow CTAs.
- **Implementation**: Pure Tailwind CSS, no new dependencies.
- **Compatibility**: All existing props, contracts, and wiring preserved.

### Risk Management (SL/TP/Trailing/GTT)
- **New controls**: Stop Loss, Target Price, Trailing Stop Loss, and GTT toggle.
- **Order routing**: Risk parameters flow through a single REST `POST /api/v1/placeorder` on the calculator-confirm path (opts present).
- **Sandbox handling**: Sandbox stores and preserves risk params as metadata; original data/logs retain them.
- **Live broker handling**: Live broker path strips unknown keys safely; single-leg order placement behavior preserved (full GTT trigger-leg placement deferred as broker-specific).

### App-Wide Wiring
- **Components**: Wired into `frontend/src/components/trading/ChartPane.tsx`, `frontend/src/pages/Holdings.tsx`, `frontend/src/pages/OptionChain.tsx`.
- **Terminal**: `frontend/src/lib/trading/terminal.ts` — `confirmOrder(side, type, opts?)` and `_executeOrder(side, type, opts?)` accept optional `price` for LIMIT orders. `_executeOrder` uses the provided LIMIT price (does not snap to chart context).
- **ChartPane confirm**: Passes `outcome.orderType` and `outcome.price` through cleanly (calculator-confirm path uses REST with risk params).

**Impact**: Correct, intraday-only leverage, proper LIMIT scheduling semantics, cleaner risk controls, and consistent UX across Chart/Holdings/Option Chain.

---

## 3. Brokerage Charges Estimator (Task 6)

Real per-broker brokerage breakdown integrated into calculator and Order Book.

### Broker Tariff Data
- **CSV**: `data/broker_charges_comparison.csv` covering Fyers, Zerodha, Dhan, plus appended Groww.
- **Coverage**: Equity Delivery/Intraday, Futures, Options; global SEBI/IPFT/GST and DP charges included.

### Pure Estimator Service
- **Service**: `services/brokerage_charges.py` (no Flask dependency). Pure, cacheable (lru_cache on CSV load), deterministic.
- **Segment detection**: Auto-detects segment (`Equity Delivery`, `Equity Intraday`, `Futures`, `Options`). Handles Dhan aliases (`Futures (Equity F&O)`, `Options (Equity F&O)`).
- **Global merge**: Merges "All Equity Segments" global rows and DP/Demat rows into every applicable segment.
- **Edge cases fixed/pinned**: CE/PE equity symbols resolving to Options, STT "0.1% on buy and sell" parsing (sell-only case handled correctly), global-segment rows loading, DP buy/sell row conflicts (prefer sell row where applicable).
- **Supported brokers**: `fyers`, `zerodha`, `dhan`, `groww`.

### APIs
- **Blueprint**: `blueprints/brokerage_charges.py` exposes:
  - `POST /brokerage-charges/api/estimate` (single order estimate)
  - `POST /api/estimate/batch` (batch estimates for multiple orders: `{orders:[...]}`)
- **Auth/gating**: `@check_session_validity`, broker inferred from session, returns 403 for unsupported brokers.

### Frontend Integration
- **API client**: `frontend/src/api/brokerage.ts` (uses `webClient` with auto-CSRF). Exports `BROKERAGE_BROKERS` for UI gating.
- **Position Calculator**: "Brokerage" chip (debounced 400ms), valued at LTP (Market) or limit price (Limit). Opens a breakdown tooltip (segment + per-component amounts + totals).
- **OrderBook**: `frontend/src/pages/OrderBook.tsx` gains a **Charges column** (header + cell). Batch-estimates every priced row (`price>0 && quantity>0`). Shows total with hover tooltip (segment + full per-component breakdown). Unpriced rows remain blank; hidden/blank for unsupported brokers or when not applicable (`!isCrypto` gating as intended).

### Tests
- **Locked regressions**: `test/test_brokerage_charges.py` — 19/19 passing. Pins exact totals per broker/segment (includes STT + DP cases). Examples: Zerodha Intraday BUY 100@500=21.07, Delivery SELL incl STT 50+DP 15.34=67.21, Fyers Options SELL 1 lot@200 lot75=54.00, Groww Delivery SELL=66.87 (DP 15), Dhan Intraday BUY=111.23, Zerodha Futures BUY 1 lot@48000 lot35=95.46.

**Impact**: Real, broker-specific charges visible at decision time (calculator) and in history (OrderBook).

---

## 4. F&O - Expired Contracts (Historical Data)

Discovery + historical OHLCV/OI for expired F&O contracts (FYERS provider).

### APIs
- `GET/POST`-style authenticated endpoints (per blueprint): `/api/v1/expired/expiry-dates`, `/api/v1/expired/contracts`, `/api/v1/expired/history` (FYERS provider).

### Safety & Validation
- **Bounded windows**: Strict date/range validation. Minute requests split into ≤100-day windows. 5s interval restricted to ≤30 calendar days (subject to broker retention). Daily/weekly/monthly/Greeks not supported as intended.
- **Bars capped**: `bars` 1–5000, total/truncation metadata returned.
- **Explicit errors/no-data**: Clear error messages and no-data responses; avoids silent empty returns.

### Contract Discovery
- **Exact contract IDs**: Uses discovered contract IDs from expiry/contract discovery (not live order symbols). Returns separate futures/options lists by expiry.
- **OHLCV + OI**: Returns candles with OI included where available (`include_oi` supported).

### Verification
- **Live verification**: SBIN 2025-03-27 discovery returned 1 future + 150 options; pulled 75 five-minute candles each with OI for `SBIN25MARFUT` and `SBIN25MAR760CE`.

**Impact**: Enables research/backtesting on expired F&O history with safe, bounded requests and exact contract identity.

---

## 5. Watchlists + MCP Integration

External agent access to saved chart watchlists + expanded MCP toolset.

### Watchlist API Surface (Authenticated)
Implemented full CRUD + batch ops at `/api/v1/watchlist`:
- `list`, `get` (by exact name), `create`, `delete`, `rename`
- `add_symbols`, `remove_symbols`, `replace_symbols`

Features:
- Pasted comma/space/newline/semicolon symbol lists supported.
- Optional `EXCHANGE:` prefixes; bare symbols use default exchange.
- Duplicates skipped; missing entries reported as `not_present` (not errors).
- Explicit `replace` vs `append`; `create_if_missing` supported where applicable.
- Preserves order on replace/add as specified; owner-scoped access.

### MCP Tools Expanded
- **+8 Watchlist tools** added (list/get/create/delete/rename/add/remove/replace).
- **+3 Expired F&O tools** added (expiry-dates/contracts/history).
- **Registry**: Brought shared MCP tool registry to **60 tools** total.

### MCP Configuration & Verification
- **Local desktop entry**: Configured `~/.codex/config.toml` with stdio launcher using existing approved private key (no key rotation).
- **Live connectivity**: Verified HTTP 200 / live list read via MCP.
- **Scope**: Remote MCP remains disabled; local stdio for Codex/ChatGPT desktop only.
- **Client note**: Clients need reload/new session after config changes (desktop UI reload behavior unverified).

**Impact**: External agents (Codex/ChatGPT desktop) can safely read/update the same saved chart watchlists as the web/chart UI with batch operations and strict validation.

---

## 6. Performance, Latency & Stability Improvements

### Throttling & Race Risk Reduction
- Scanner pacing (~1.25s) + removed nested retries, preserving server Retry-After.
- Bounded listener readiness (proxy→scanner) and pooled/paced symbol-token calls.
- Cancellable cooldowns prevent retry amplification.

### Smarter Failure Handling
- Correct transient vs. invalid classification (especially FYERS symbol-token JSON/service failures).
- Retry-After honored, bounded backpressure, cleanup of stale retries.
- Batch flush improvements (HSM subscription) prevent dropping results incorrectly.

### Startup Robustness
- Fixed startup-order race (proxy integration before scanner init + bounded readiness wait).
- Improved HSM subscription batch flush and stale-session handling on restart.
- Startup stale-session recovery hardened.

### Resource Hygiene
- Real-timer 100-cycle thread/descriptor stability checks.
- Bounded history windows (expired F&O + export paths).
- Teardown cleanup (cancels pending retries on worker shutdown).
- FD/audit-aware behavior improvements (resource leak guardrails).

**Impact**: Lower latency variance, better resilience under provider throttling, fewer false negatives, cleaner restarts.

---

## 7. Backtesting, Scheduling & Validation

### Scheduled Backtests (8 Profiles)
- Restored and ran 8 saved scheduled profiles (1m + 5m HA variants).
- Generated artifacts with ledgers verified; tracked scanner/current-watchlist coverage.
- Results documented: [`backtesting/eight_scheduled_20261001/README.md`](../backtesting/eight_scheduled_20261001/README.md), [`backtesting/eight_scheduled_20260930/README.md`](../backtesting/eight_scheduled_20260930/README.md) (as applicable).
- Coverage: 73/73 scanner, 20/20 current, both modeled paths, 1,240 ledger rows verified (Oct 1 run).

### Regression Coverage
- Targeted cases added: entry timing/intrabar behavior, strict trailing, 5m HA variants.
- Large focused test passes across work batches: 19, 53, 61, 69, 79, 113, 136, 163, 173, 232, 403 tests passed at various validation checkpoints.

### Entry Timing Confirmation
- Qualifying intrabar signal-high crosses submit **without waiting for entry candle close** (verified and documented with regression tests).
- Scheduled warmup + exact-session history queries hardened (resolved FYERS duplicate/conflicting full-day responses).

**Impact**: Stronger regression safety net, reproducible scheduled runs, timing semantics locked in by tests.

---

## 8. Charting, Terminal & Order Flow

### Upstream Merge Preservation
- Integrated 43 upstream commits (agent module, chart ticket redesign, Shoonya/Kotak fixes) with conflict resolution preserving both behaviors.
- Kept One-Click armed/disarmed ticket system intact (`onOrderTicket` + PlaceOrderDialog + `buildOrderTicket/placeTicket`).

### Calculator-Confirm Path Extension
- Calculator confirm uses REST path with risk params (`stoploss/target/trailing_stoploss/gtt`) when `opts` present; never bounces to ticket.
- `ChartPane.handleCalcConfirm` passes `outcome.orderType` and `outcome.price` through cleanly.
- `_executeOrder(side, type, opts?)`: when `opts` present (calculator confirm) risk params sent via REST `placeorder`; otherwise normal feed path. Uses provided LIMIT price instead of snapping to chart context.
- `confirmOrder(side, type, opts?)` always places when called with opts (calculator path).

### Guards Preserved
- Replay lock, symbol/trade present, quote-only, freeze limit, stop-on-wrong-side-of-LTP remain enforced in `_executeOrder`.
- Armed One-Click clicks still place instantly (upstream behavior retained). One-Click OFF with no calculator callback falls back to ticket as designed.

### Frontend Build Hygiene
- Fresh `frontend/dist` rebuilds tracked with feature chunks: `brokerage-*.js`, `PositionCalculator-*.js` (include Market/Limit, leverage gating, 3D UI).
- Build verified clean (`tsc -b`, `vitest`, `biome lint`, `npm run build`).

**Impact**: Calculator integrates cleanly without breaking existing One-Click/ticket flows; LIMIT pricing flows correctly end-to-end.

---

## 9. Documentation, Planning & Repo Hygiene

### Canonical Planning
- **Six-task roadmap**: [`docs/plans/2026-09-11-six-task-roadmap.md`](plans/2026-09-11-six-task-roadmap.md) maintained as source of truth + restart memory.
- **Portfolio section plan**: [`docs/plans/2026-10-02-portfolio-section-plan.md`](plans/2026-10-02-portfolio-section-plan.md) added (Task 6 unfrozen, Phase 0 only; 4 open decisions documented).

### Guides Added
- [`strategies/FOUR_STRATEGIES_CHART_GUIDE.md`](../strategies/FOUR_STRATEGIES_CHART_GUIDE.md) — Four ₹10,000 Sandbox profiles with flow diagrams and linked offline interactive examples.
- Expired F&O API documentation ([`docs/api/market-data/expired-fno.md`](api/market-data/expired-fno.md) referenced).
- MCP guide ([`mcp/README.md`](../mcp/README.md)) for prompts/configuration.
- Mac local-fork/restore guidance ([`docs/installation-guidelines/macos-local-fork.md`](installation-guidelines/macos-local-fork.md)).

### Syncs, Remotes & Handoff
- Pushed to `jilimudiManvitha/OpenAlgo_MVP` (origin/main) as requested.
- Preserved LFS (228 objects), portable-backup snapshot maintained (`portable-backup/latest/` with restore key handled separately).
- Remote/origin tracking updated per requested destination; historical remotes preserved in context where relevant.
- [`context.md`](../context.md) maintained as the handoff log for clean resumption across sessions.

**Impact**: Deterministic restart memory, clear planning boundaries, comprehensive operational documentation.

---

## 10. Investment Portfolio (Planned, Not Implemented Yet)

### Task 6 (Unfrozen)
- **Scope**: Broader Investment Portfolio covering 10 asset classes (Stocks, Mutual Funds, ULIPs, Fixed Income, Bullion, Property, Loans, Other Assets, Other Borrowings) with full read/write, timestamped transaction ledger, 9 reports, portfolio scoring and charts.
- **Status**: **Phase 0 only (decisions + plan)** — documentation changed, **no implementation files exist yet**.
- **Namespace**: Uses `investment` namespace (separates from portfolio backtester). Only user-facing route reclaimed; `/portfolio-backtester` remains intact.
- **Locked decisions**: Weighted-average cost basis on holdings screens; manual price entry plus CSV import for non-stock assets (no AMFI/mfapi NAV provider in codebase).
- **Gating**: Implementation blocked until 4 open questions in [section 12](plans/2026-10-02-portfolio-section-plan.md#12-open-questions) are answered (first: whether paper trading wires into `database/sandbox_db.py` engine). Phase 3 will not begin before Phase 2 numbers reconcile.

---

## TL;DR — Biggest Practical Wins

1. **Intraday Position Calculator** (Leverage DB + Market/LIMIT + SL/TP/Trailing/GTT + 3D UI) — Correct sizing/risk with INTRADAY-only leverage, clean LIMIT semantics, consistent UX.
2. **Brokerage Charges Estimator** (Calculator chip + OrderBook Charges column) — Real per-broker breakdown for Fyers/Zerodha/Dhan/Groww with locked regression tests.
3. **Expired F&O Historical APIs** — Safe discovery of expiries/contracts + bounded intraday history (OHLCV+OI) with exact contract IDs.
4. **Scanner/Subscription Hardening + Startup Latency Fixes** — Much more stable under throttling, fewer false failures, correct failure classification, cleaner startup sequencing.
5. **MCP Watchlist Tools (+8)** — External agents (Codex/ChatGPT desktop) can read/update the same saved chart watchlists safely with full CRUD + batch ops.
