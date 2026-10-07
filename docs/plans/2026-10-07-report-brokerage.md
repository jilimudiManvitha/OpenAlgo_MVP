# Broker-aware report estimates — October 7, 2026

**Evening integration:** Combined into the normal local build with user authorization. [Current release and restart checklist](2026-10-07-evening-combine.md) supersedes the staged-only status below.

**October 7 mode follow-up:** [Live/Sandbox implementation and current limits](2026-10-07-live-sandbox-features.md) adds mode-separated Portfolio, real order/GTT tickets and confirmed Strategy Builder fill reports in both modes. Still isolated and not deployed.


User requested broker-dependent brokerage in Sandbox and live reports and explicitly
selected **standard retail rates**. This supersedes the earlier journal's
recorded-fees-only limitation. Implementation remains isolated and **not deployed**.

## Behavior

- Journal API takes the authenticated session broker; no client-supplied broker override.
- Saved `brokerage_context` takes precedence over later logins. It snapshots the
  broker, retail tariff, version and capture time. Existing reports without this
  context explicitly say the current login broker is assumed; historical broker
  identity cannot be recovered from their original payloads.
- Eight verified standard profiles: FYERS, Zerodha, Dhan (`dhan_sandbox` alias),
  Groww, Angel One Plus, Upstox Basic, Shoonya and Flattrade.
- NSE equities (MIS/CNC) and NFO futures/options have estimated trading charges:
  brokerage, STT, exchange, SEBI, stamp duty, IPFT, clearing where listed, and GST.
  The report must identify instrument/product and entry side. Known existing
  stock/option producer formats are recognized without changing their code.
- Both PAPER and LIVE stored-report paths use the same estimator. This does **not**
  start live trading or create/import live reports from a broker tradebook.
- Charges update net P&L, winning/losing trades, daily/strategy/stock summaries and
  calendar streaks. Brokerage has its own metric and the components are expandable.
- Order IDs share a brokerage cap across split rows within a report/scenario;
  component amounts are allocated pro rata with rounded residual on the final row.
- Only executed entry/exit sides are estimated. Open entry costs are disclosed
  separately; full round-trip realized costs are recognized when the trade closes.
- Explicit `fees_actual=true` preserves confirmed actual fees and any supplied
  breakdown. Estimates replace assumed recorded fees; they are never added twice.
  Unmarked fees retain their originals in `recorded_fees` / `recorded_net_pnl` and
  are recoverable with **Original recorded fees**. No saved ledger is rewritten.
- Individual detail and CSV use the same basis as the annual journal. CSV contains
  provenance and the component estimates; owner checks and formula neutralization apply.
- Unknown brokers, missing execution metadata and unsupported exchanges show
  unavailable estimated totals, rather than zero fees or another broker's tariff.

## Source rates checked October 7

| Broker | Intraday brokerage, per executed order | Options brokerage | Official source |
|---|---|---|---|
| FYERS | Lower of 0.03% and ₹20 | ₹20 | [Tariff](https://fyers.in/charges-list) |
| Zerodha | Lower of 0.03% and ₹20 | ₹20 | [Tariff](https://zerodha.com/charges) |
| Dhan | Lower of 0.03% and ₹20 | ₹20 | [Tariff](https://dhan.co/pricing/) |
| Groww | Lower of 0.1% and ₹20; ₹5 minimum subject to cash-market ceiling | ₹20 | [Equity](https://groww.in/pricing), [F&O](https://groww.in/pricing/futures-and-options) |
| Angel One Plus | Lower of 0.1% and ₹20; ₹5 minimum subject to cash-market ceiling | ₹20 | [Tariff](https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges) |
| Upstox Basic | Lower of 0.1% and ₹20 | ₹20 | [Tariff](https://upstox.com/brokerage-charges/) |
| Shoonya | Lower of 0.03% and ₹5 | ₹5 | [Tariff](https://shoonya.com/pricing) |
| Flattrade | Zero brokerage | Zero brokerage | [Tariff](https://flattrade.in/support/knowledge-base/which-segments-have-zero-brokerage/) |

Futures and delivery profiles also differ (e.g. FYERS delivery is capped 0.3%,
Zerodha/Dhan delivery zero; Dhan/Groww futures flat ₹20).
NSE transaction/IPFT changes follow the [March 1, 2026 circular](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf).
F&O STT changes follow the [April 1, 2026 schedule](https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax).
The estimator versions published brokerage rates as `retail-2026-10-07-v1`, not a
live website lookup. Historical untagged reports use this retail snapshot with
execution-date statutory rates; they are not reconstructed contract notes.

## Limits

This is **not universal coverage of every OpenAlgo broker or every instrument**.
No guessed rate is used for the other broker plugins. Add a verified profile to
`PROFILES` before claiming coverage. Unsupported exchanges include BSE/BFO, MCX,
currency and crypto; unknown products are unavailable. ETFs/tax-exempt instruments
require explicit separate rules before use. Known scheduled strategies here are
NSE stocks and NFO NIFTY options; the read-only compatibility probe found no closed
paper trades with unavailable estimates across the existing 20 strategies.

DP, physical delivery, exercise/assignment, auto-square-off, call-and-trade,
financing/MTF interest, subscriptions and account fees are excluded. Per-order
paise rounding can differ from a broker's day-level STT/stamp rounding. Custom,
promotional, NRI, corporate and negotiated plans are outside the selected retail
scope. Cash-market brokerage is capped at 2.5% for small-ticket minima. Multi-day
partial-close allocation across different report payloads is not a full orderbook
reconciliation; current scheduled producers emit complete trade/leg rows.

## Isolation and future integration

The running `services/scanner_strategy_reports.py` and all scheduled strategy
source files are **unchanged**. The writer hook is implemented and tested in:

- `.development/report-journal/overlays/services/scanner_strategy_reports.py`
- `.development/report-journal/report-writer.patch`

This is deliberate: scheduled subprocesses could import a changed ReportStore
while production continues running. At a later user-approved combine, after the
user stops production, review/apply this small patch along with the journal code,
then build the normal frontend. **Do not simply deploy the frontend without the
writer hook**, or new reports will keep relying on inferred broker identity.
Metadata capture errors are best effort and cannot block saving trade/intent data.
The hook is report metadata only; it never changes fees, funds, risk or execution.
No production DB migration is required (metadata lives inside the report JSON).

## Verification

- 106 focused backend tests passed (31 fee tests, 9 journal, 66 existing scheduled
  stock/options checks). Includes all eight brokers, per-order caps, long/short
  sides, historical statutory boundaries, actual-fee precedence, session broker,
  metadata persistence/failure isolation, owner-scoped detail/CSV, missing data,
  LIVE/PAPER parity and net-profit-to-loss conversion.
- 7 frontend tests passed; no-emit TypeScript, focused Biome/Ruff and isolated build pass.
- Desktop/mobile browser flow on 5011 passed with synthetic reports, brokerage
  provenance, estimated/recorded selection, grouped reports, calendar and charts.
- Five in-memory mutations caught: account scoping, peak capital, GST omission,
  actual-fee precedence, broker snapshot precedence. The first snapshot test used
  too-small orders to distinguish capped brokers; increasing its turnover exposed
  the deliberately disabled snapshot logic. The strengthened test then failed as intended.
- Resource audit: 150 repeated reads retained FDs at 3 → 3 and about 26 KB traced
  allocations after GC. SQLite read paths use `closing`; auth metadata sessions
  remove on success/failure. No persistent rate/network cache or new worker.
- Protected source/frontend baseline: 556 paths inspected. Only the live scheduler
  config hash changed during this market-hours session; it still contains all 20
  schedules and was never edited by this task. ReportStore, strategies and serving
  frontend assets match their baselines. No production orders, process signals,
  database writes, build, commit or push.
