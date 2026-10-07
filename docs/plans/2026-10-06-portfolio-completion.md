# Investment Portfolio — development completion, October 6

**October 7 update:** The user authorized combining the finished Portfolio with the scheduled strategies for local startup and a Git push. The normal frontend is now built and verified; the old deployment hold below is superseded. Production was not started by the agent. [Release readiness](2026-10-07-local-release-readiness.md).

The user resumed work with “complete that portifolio section remaing” and “limit reseted continue.” Phases 3–5 are implemented locally and verified in development lane D. **They have not been deployed to the user's running app.** The [standing order](2026-10-04-readiness-portfolio-handoff.md#0-standing-order--develop-in-parallel-never-affect-the-users-openalgo) still governs production. No commit or push was requested or performed.

## Available features

- `/portfolio`: account-scoped net worth, weighted-average cost, income and realized/unrealized gains, allocation and documented portfolio measures. Liabilities subtract from totals; allocation uses signed percentages of gross exposure when liabilities exist. Missing prices remain unavailable.
- `/portfolio/stocks`: Stocks and exchange-traded ETFs, transactions, history, manual prices and existing explicit broker-price refresh.
- `/portfolio/assets/MUTUAL_FUND`: class selector for Mutual Funds, Fixed Income, Bullion, ULIPs, Property, Other Assets, Loans and Other Borrowings. Each has relevant editable metadata. All use manual dated prices; CSV bulk pricing is available. The plan calls these ten classes while combining Stocks/ETFs in `STOCK`; the implementation has the nine enum values listed in the plan.
- Loan and borrowing transactions label BUY as principal borrowed, SELL as principal repaid and INTEREST as interest paid. Mutual-fund quantities retain six decimals, including consolidated reports. Separate SIP purchases can be recorded; no recurring order scheduler was added.
- `/portfolio/reports`: Transaction History, Dividends, Corporate Actions, Performance, Holdings, Capital Gains, Profit & Loss, Transaction Calendar and Consolidated Holdings, with account/date filters and CSV download. These investment reports are separate from scheduled-strategy `/reports`.
- `/portfolio/watchlists`: categorized watchlists, editable tracking thresholds and explicit paper GTT forms for stocks/ETFs in paper accounts. Watching does not create a purchase. Fund NAV thresholds are observations, not executable intraday stops.

## Valuations and reports

CSV requires `symbol,scheme_code,price,as_of`, at most 500 rows / 256 KB, and ISO timestamps containing a timezone. Every row must identify one owned asset in the selected account; one invalid or ambiguous row rolls back the whole import. Export neutralizes spreadsheet formula cells. Manual/stale prices remain labeled. A price preceding a recorded split is unavailable for post-split units until a new valuation is entered.

Holdings reports use the same current valuation service as the dashboard; date filters do not turn them into historical snapshots. Capital Gains shows FIFO lot allocations, dates, quantities, charges and realized gains alongside the weighted-average P&L report. It does **not** calculate tax rates, exemptions or indexation. Performance is a recorded net-worth curve with price dates, missing-valuation gaps and transaction cash flows; it is not a fabricated TWR/XIRR or historical market-return series.

Bounds: 100 assets per user, 10,000 transactions per asset, 50 watchlists and 1,000 paper-trigger links per user. Reports accept up to 367 days and 50,000 transactions; the performance curve accepts 5,000 transactions / 50,000 valuations for the selected account(s). Large accounts receive an explicit error rather than truncated results.

## Existing Sandbox integration

`services/investment_paper.py` calls the existing `sandbox.gtt_manager.GTTManager` directly. It has no live-order service. CNC limit GTTs use Sandbox funds, margin, instrument tick rules and its existing monitor. The monitor owns triggering and fills while the portfolio page is closed. The form requires explicit reference, trigger and limit prices; the examples from the user's request were not submitted or seeded.

Durable request keys and a committed intent prevent repeat submission following a timeout or crash. A unique strategy tag associates the trigger and complete Sandbox trade records with the chosen investment account. **Refresh triggers & import confirmed fills** reconciles them into the ledger once, with actual fill timestamp/price/quantity. It checks identity, quantity, ownership and duplicate order IDs, and rolls back mismatches. Confirmed imported transactions cannot be deleted independently. An ambiguous dispatch is retained for reconciliation, never silently resent. No historical crossing is inferred from a current price.

Long-lived exposure protection is intentionally conservative: while a portfolio GTT is active, or tagged history exists alongside CNC exposure, automatic funds resets are skipped and manual Sandbox reset returns HTTP 409 before changing configuration or balances. The message asks the operator to cancel resting triggers/orders and close delivery exposure explicitly before a destructive reset. It does not selectively reset intraday cash or create a second balance engine. Existing holdings and balances were not migrated or reset during development.

## Files and schema

Five additive tables extend the initial five investment tables: `investment_asset_details`, `investment_watchlists`, `investment_watch_items`, `investment_paper_orders`, `investment_paper_fills`. Existing table columns are unchanged. Startup's existing `investment_db.init_db()` creates missing tables on the eventual user-authorized deployment.

New services: `investment_reports.py`, `investment_watchlists.py`, `investment_paper.py`, `investment_sandbox_guard.py`. The ledger service, investments blueprint, React types/client/pages and page titles are extended. Narrow Sandbox changes only call the reset guard. The portfolio backtester, production scanner data and schedule definitions are unchanged by this work.

## Verification

- 59 focused portfolio backend tests: ledger, routes, all asset enums, fractional units, signed liabilities, atomic CSV, all reports, ownership/CSRF, concurrent idempotency, crash recovery and real isolated Sandbox GTT/fill/cancellation/reset paths.
- 113 existing Sandbox GTT tests pass; two existing SQLAlchemy delete-count warnings remain.
- Scheduler-isolation regression passed separately. Its atexit logger emitted closed-capture warnings after successful tests; saved production schedules were unchanged.
- 20 frontend tests matched by `portfolio` pass, including liability labels and missing-price chart gaps. TypeScript and scoped Biome/Ruff checks pass.
- Vite preview built to `.development/investment/dist` only. The normal `frontend/dist` was not rebuilt.
- Real Chrome browser verification uses the fixture server on **5011**, SQLite under **log/test/** and actual investment routes/CSRF. Desktop/mobile account/stock flows, ATHER partial sale, fund fractions, NAV CSV, a loan, nine report selections, FIFO CSV download, watchlist thresholds and reloads pass with zero page errors. No paper order is submitted by the browser fixture.
- Worked browser result: 90 ATHER shares, ₹90,000 cost, ₹99,000 value, ₹9,000 unrealized and ₹2,000 realized; add 1.123456 fund units at ₹110 and ₹500 debt → **₹98,623.58 net worth**.
- Fault-injection probes removed ownership, split-price and idempotency guards in memory. The actual regression tests failed as expected; source files were never reverted or replaced.
- Resource audit: 300 report/watch/dashboard/error cycles, descriptor counts **4 → 4 → 4**, no retained investment scoped session. Traced allocations after garbage collection were approximately 284 KB, 289 KB and 291 KB. Static review covers `transaction()` cleanup and Sandbox/symbol-session `finally` blocks; no new background thread or HTTP client was added.

Evidence is in `log/test/investment-completion.xml`, `log/test/investment-*-regression.log`, and `.development/investment/artifacts/` (browser JSON, CSV, screenshots, protected-file hashes, resource measurements). Fixture scripts are under `.development/investment/`. Re-run focused tests through `test/conftest.py`; never bypass its database/scheduler isolation.

Final cleanup: both preview processes started for this verification were stopped; no listener remained on 5011. The final local listener check also found no listener on 5000/8765; no production process was started or signaled. All 520 protected file hashes (production frontend files plus saved strategy configuration) matched the pre-verification snapshot, with no added production frontend files. Twenty saved strategies remain; configuration SHA-256 `da5150800eb92b1d6cc86f4e5bdfa38354a93bb5532b7508f03dec65776e905f`. This is a fresh October 6 observation, not a replacement configuration to restore over subsequent user changes.

## Deployment remains the user's decision

The user must say **“combine and launch”** before these changes are deployed. Preserve unrelated local changes and the preexisting generated-asset staging state. The user stops and restarts production; an agent must not signal it. At that point review the intended source diff, build the normal frontend while production is stopped, allow startup to create the five additional tables, and verify the new deep links and authenticated APIs. Recheck saved schedules and existing Sandbox balances against fresh pre-deployment observations rather than stale October 4 hashes. Do not seed example orders or holdings.

Market-hour broker execution and real user's balances were not exercised by this development verification. Remaining work is deployment and its operational checks, not another implementation phase.
