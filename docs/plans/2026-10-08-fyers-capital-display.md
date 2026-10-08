# FYERS options capital and charges display — October 8, 2026

Implemented for the twelve scheduled Sandbox options variants, following the
[capital investigation](2026-10-08-options-capital-check.md). Included in the local
frontend build. The user starts production and signs into FYERS; no production
app was started, no broker orders were sent, and no account funds were changed.

## Where to find it

- **Dashboard → Analyze mode → Options capital & charges**.
- **Strategy Reports → Sandbox → Current options capital & charges**, expandable.
- Each variant shows its ₹20 lakh allocation, ₹18 lakh deployable budget, saved
  leg quantities/lots, entry sizing receipt when available, and estimated fees.
- **Get FYERS margin** submits the complete saved strategy basket to the existing
  FYERS multiorder margin API. **Get combined FYERS margin** nets identical NFO
  NRML contracts across all saved variants before making one basket request.
- **Reload positions** reads current saved strategy state and clears old quotes.
  A quote is a timestamped estimate, not a balance reservation or historical
  reconstruction. Pending intents prevent quotes; changing legs invalidate them.

## Meaning of the figures

Twelve ₹20 lakh strategy budgets total ₹2.4 crore; after the existing 10% reserve,
combined sizing budgets total ₹2.16 crore. Budgets do not themselves reserve cash.
The Dashboard's Analyze-mode funds card now says **Sandbox blocked funds**, since
that ledger still uses option premiums times quantity. It remains separate from
broker basket requirements.

The broker response fields are retained separately, following the existing FYERS
adapter mapping in `broker/fyers/mapping/margin_data.py`:

- `margin_total`: approximate basket/order requirement.
- `margin_new_order`: total including existing positions.
- `sizing_requirement`: maximum of those two, preserving the existing conservative
  sizing rule. The UI displays its percentage of the relevant allocation.

Do not sum account-inclusive per-strategy quotes: existing account positions may
appear in more than one quote. Combined net margin can differ from standalone
strategy totals. Full legs are sent together to reflect offsets and hedge benefits;
see [FYERS basket guidance](https://support.fyers.in/portal/en/kb/articles/how-can-i-check-the-margin-required-in-a-basket-order-on-fyers).

The runtime now retains one-lot and full-basket quotes, quote times, allocations,
lots and utilization in the opening intent. The first confirmed fill attaches the
receipt to persistent strategy state, surviving restart; daily reports also retain
it. Hedge recovery preserves the original receipt. A subsequent entry replaces it.
The twelve old entries have no receipt: the UI explicitly says **No saved entry
quote**. At verification, six saved positional baskets remained open.

Charges reuse the existing [FYERS tariff](https://fyers.in/charges-list) estimator
(`retail-2026-10-07-v1`), applying execution-date statutory rates to confirmed cycle
entries and exits. The expandable breakdown includes brokerage, STT, exchange,
SEBI, stamp duty, IPFT, clearing and GST. Open entry costs are included, future
exit costs excluded. These are estimates, not broker-billed fees and not values
returned by the margin API. No Sandbox funds or report ledger fees are rewritten.

## Implementation and boundaries

- `services/options_capital.py`: owner-filtered SQLite read-only snapshot, cycle
  charge aggregation, basket construction/netting and before/after quote checks.
- `blueprints/market_scanner.py`: authenticated GET overview and CSRF-protected
  POST quote, FYERS session required for quotes, 15 requests/minute limit.
- `strategies/nifty_options/runtime.py`, `execution.py`, `daily_reports.py`:
  persist margin evidence; reject missing, non-finite or negative broker amounts.
- `frontend/src/components/reports/OptionsCapital.tsx`: reusable panel, aborts
  requests on owner change/unmount, manual sequential quotes, explicit errors.

No schedules installed/changed; no automatic polling of FYERS. The user explicitly
requests quotes through buttons. Existing credential checks, symbol mapping,
shared HTTP client, 30-second HTTP timeout and inter-process margin lock are reused.
All source work and test fixtures are isolated from production data. Only the
user restarts OpenAlgo. A fresh authenticated FYERS quote still needs operational
verification after login; automated/browser tests use controlled broker responses.
No new backtest was run as part of this display change.

## Verification

- **173 backend tests passed** across capital display, execution/recovery, hedge
  rules, runtime, strategy logic, brokerage and scanner routes.
- **11 frontend tests passed** for capital display and Report Journal, including
  quote errors, changing owners, request cancellation and pending baskets.
- Owner-filter mutation deliberately made the owner-isolation test fail; source
  was not modified by that in-memory mutation.
- TypeScript, focused Ruff/Biome checks, and production frontend build passed.
  Vite retains its existing large-chunk warning.
- Isolated port-5011 browser checks passed: twelve baskets, single/combined quote
  rendering, quantities, fee breakdown, mobile page-width check and Reports mode
  separation. Desktop/mobile screenshots inspected; zero JavaScript page errors.
- Production state overview read successfully; twelve allocations, six open
  baskets, no missing fee estimates. This is not a fresh FYERS quote.
- 150 repeated read-only overview calls: descriptors stayed **4 → 4**, retained
  traced memory changed by **6,838 bytes** after collection. SQLite connections
  close on success/errors; no new caches, workers or subscriptions. Existing HTTP
  client is shared and sessions are cleaned in `finally`.
- Database/schedule SHA-256 hashes matched the starting snapshot. All **28 schedules**
  preserved (16 equity ending 15:15 IST, 12 options). No listeners on production
  ports 5000/8765 during the build. Only the agent's fixture is stopped on cleanup.

Local evidence: `log/test/options-margin/`; reproducible isolated preview and
mutation scripts: `.development/options-margin/`.
