# Six-task implementation plan and agent handoff

Updated: 2026-09-11, Asia/Kolkata. Status: planning complete; implementation not started by this session.

This is the canonical plan for the user's six tasks from 2026-09-11. The task numbers below belong to this request; similarly numbered historical tasks in `context.md` are different work. Read this plan before resuming implementation. All future progress belongs in the checklist and handoff section here.

## Scope and repository boundaries

The user asked to plan first and save enough memory for a restarted or different agent. This session only writes planning/agent documentation. No application code, configuration, databases, trading sessions, or credentials are changed. No backtests or live orders are run.

| Repository | Intended responsibility | Boundary |
|---|---|---|
| `D:\Personal\openalgo` | Existing Indian-market backend; source for strategy, scanner, web UI, sandbox behavior | Preserve existing code during planning; Task 3 must integrate without modifying it |
| `D:\Personal\openalgo_Crypto` | Existing crypto backend, Delta Exchange broker | Preserve existing code during planning and Task 3 |
| `D:\Personal\Algomirror` | Shared account interface and calculator for Indian and crypto brokers | Main Task 3 implementation target |
| `D:\Personal\openalgo-mobile` | Flutter client with web functionality parity | Main Task 5 implementation target |

The instruction “don't change any code” for the two OpenAlgo directories conflicts with Tasks 2, 4, and 6 explicitly requesting OpenAlgo changes. An optional clarification was sent during planning, with no answer recorded at save time. **Until clarified, keep both original code trees unchanged and prepare future OpenAlgo changes in a separate development checkout/copy.** Do not assume silence authorizes edits to either original tree. If the user clarifies that the freeze only applies to Task 3, implement other requested tasks in their designated development branches. Record that answer here.

Only `D:\Personal\openalgo` is a writable project root in this session. Later edits in sibling repositories require a workspace granting access or the normal tool escalation; task intent does not bypass filesystem restrictions. No such write is needed to finish planning.

Preserve pre-existing changes: `task.txt` was modified, and `delta-exchange-api-docs.md` plus `stock_symbols_CSVs/` were untracked at inspection. Do not overwrite, stage indiscriminately, reset, or delete them. Existing `context.md` documents the private remote and older work; do not replace its history or reset Git remotes.

## Evidence inspected

- `backtesting/stratagies/ATHERENERG_ha_bb_vwap_backtest.py`: single-symbol CSV/report adapter importing `ha_bb_vwap_strategy_astra.py`; several output filenames are hardcoded to ATHERENERG.
- `backtesting/stratagies/ha_bb_vwap_strategy_astra.py`: actual strategy. Existing baseline is long-only, five-minute, completed confirmation then next real bar open, one portfolio-wide position, maximum three daily entries, risk-based sizing, and configurable filters/exits.
- `scripts/market_scanner.py`, `services/market_scanner_service.py`, `services/market_scanner_provider.py`, `blueprints/market_scanner.py`, scanner DB and tests: useful backend already exists, but CLI selection, route authentication gate, and provider are Fyers-specific. Blueprint is already registered by `app.py`. No scanner page route was found in `frontend/src/App.tsx`.
- `db/historify.duckdb` exists, with a lock file. Its content and coverage were **not** audited during planning. Do not delete the lock or interrupt a writer to inspect it.
- `stock_symbols_CSVs/` contains 31 CSV files. A sampled Dhan Nifty Bank file has company names, screener URLs, LTP, volume, ratios, etc.; it is a screener snapshot, not timestamped historical OHLCV. `D:\Personal\CSVs` contains a charges CSV and spreadsheets in the inspected listing. Classify every file during Task 1; do not treat filenames or snapshot prices as history.
- `database/watchlist_db.py` already stores server-side named watchlists. `database/sandbox_db.py` stores sandbox orders/positions and uses integer order quantities; fractional mutual-fund units need a dedicated compatible model.
- OpenAlgo `frontend/package.json`: React, Vite, Tailwind v4, Radix components; MUI is not currently listed. Inspect actual installed/locked dependencies before migration.
- Local AlgoMirror README, `app/models.py`, calculator paths, and `package.json`: existing `TradingAccount` has broker name, HTTP host and WebSocket URL. UI uses server templates, Tailwind v3 and DaisyUI. Do not assume it is a React app.
- Local mobile README and `lib/`: Flutter, Provider, REST/WebSocket services, Material Design 3; existing trading screens and placeholder chart screens. README is an inventory lead, not proof that every feature is working.
- Local `delta-exchange-api-docs.md`: generated 2026-09-08; reviewed product metadata, contract values, margin/fee fields, orders, stop triggers, bracket parameters, leverage and wallet sections. Crypto broker `api/order_api.py` already contains leverage and bracket handling; verify public API field passthrough before promising those capabilities to AlgoMirror.
- `CLAUDE.md`, `docs/INDEX.md`, existing `context.md`, OpenAlgo and VectorBT skills were consulted. Preserve the supplied indicator mathematics even where a generic skill would normally select a different implementation.

External primary references checked during planning: [AlgoMirror repository](https://github.com/marketcalls/Algomirror), [Delta API documentation](https://docs.delta.exchange/), and [Material UI with Tailwind v4](https://mui.com/material-ui/integrations/tailwindcss/tailwindcss-v4/). Recheck current product constraints, fees and compatibility when implementing; examples are not live account settings.

### Screenshot reference map

All eight files were viewed. Directory: `C:\Users\nikhi\OneDrive\Pictures\Screenshots\`; each filename starts `Screenshot 2026-09-10 ` and ends `.png`.

| Suffix | Relevant content |
|---|---|
| `232438` | Delta API setup, account, IP whitelist, read/trading permissions |
| `232607` | Credential creation result; contains a key and secret. Never transcribe them into notes, code, logs, fixtures or commits. User was advised to rotate them. |
| `232820` | Long order panel, leverage, Limit/Market, quantity in lots, allocation presets, contract units, TP/SL, funds, flags, fees |
| `232832` | Maker Only, Stop Limit, Stop Market, Trailing Stop, Take Profit Market/Limit menu |
| `232847` | Bracket editor; trigger source, TP market/limit, SL market/limit/trail, percentage presets, exit/stop P&L |
| `232902` | Corresponding Short order panel |
| `232929` | ETH example with leverage choices up to 200x, maximum position and contract size |
| `232945` | Different product with maximum 20x and different unit size; limits must be product-specific |

Screenshots specify interaction requirements, not universal leverage, prices, contract sizes or fee rates. No need to copy credential screenshots into the repository.

## Shared design and execution order

Keep Indian and crypto engines separate. Run both simultaneously with distinct HTTP/WebSocket/internal messaging ports, database paths, process state, logs and credentials. Audit cookie names/domains as well: browser cookies are not isolated by port. Use separate hostnames or supported per-instance session-cookie configuration. Do not mutate a running setup during planning.

AlgoMirror should maintain a client and market-data subscription group per connection/account. Key instruments, quotes, orders, caches and events by connection ID + broker + exchange + instrument; never use a global “current broker” to route background work. A shared visual calculator delegates calculation rules to an asset/broker adapter. Keep native-currency balances separate; only aggregate with an explicit conversion source and timestamp. Crypto schedules must not inherit Indian daily square-off or session boundaries.

Recommended sequence (preserving the user's task numbers):

1. P0: confirm edit boundary; inventory data and API capabilities; create isolated implementation workspace and shared theme/API contracts.
2. T1: establish historical data coverage, exact execution contract, and baseline reports before research variants.
3. T3: implement account-aware calculator and simultaneous connection support in AlgoMirror.
4. T2: extend existing scanner and expose its live UI using the common theme foundation.
5. T6: add persistent sandbox investment watchlists and portfolio ledger.
6. T4: complete theme/component migration across the web route inventory; foundation starts at P0 so new pages already match.
7. T5: deliver mobile parity in batches against stable backend APIs, then integrated verification of all clients.

This is a dependency order, not a claim that implementation has been authorized to modify protected original code. No automatic live strategy deployment follows a good backtest.

## Task 1 — All-stock strategy, DuckDB, reports and automated research

### T1.1 Data catalog and reusable ingestion

Inventory CSVs from `stock_symbols_CSVs`, `backtesting`, existing historical export folders including `D:\Personal\historify_ATHERENERG_20260908_112029`, and any further user-designated data folders. Read headers and classify OHLCV, universe/screener snapshots, charges/reference data, and generated outputs. Catalog every CSV and preserve its source; import useful data into the appropriate tables. Generated HA candles, trade reports and repeated normalized exports must not become independent raw-price history.

Use a dedicated research DuckDB with `source_files`, `instruments`, `universe_snapshots`, `raw_imports`/quarantine, normalized `ohlcv`, `coverage`, and `backtest_runs`. Historical timestamps should be unambiguous UTC instants with exchange timezone metadata. Unique candle identity: instrument/exchange + interval + bar-open timestamp + declared data version/source policy. File manifest stores path, hash, schema, imported row counts and errors. Imports are idempotent; conflicting duplicates are reported instead of silently overwritten. Snapshot datasets without a trustworthy as-of date must retain an unknown date, not an inferred historical one.

Validate OHLC ranges, positive prices, nonnegative volumes, timestamps, session calendars, duplicates, missing bars, incomplete sessions and corporate-action treatment. Resolve company display names to exchange symbols using instrument masters with unresolved mappings reported. Retain source/adjustment metadata; never mix adjusted and unadjusted series silently. Universe membership is point-in-time where available; label survivorship bias otherwise.

Use actual one-minute OHLCV for 1m tests; aggregate it into five-minute candles aligned to 09:15 IST for regular Indian sessions. Five-minute-only data supports 5m signal tests, not invented 1m data. Reuse Historify through supported readers or a consistent snapshot/export; separate ingestion writer from read-only research workers. Large imports and runs are chunked/resumable, with an immutable data version per run.

Deliver coverage per stock/timeframe: earliest/latest candle, rows, valid sessions, gaps, warmup eligibility, available years and exclusions. Request/backfill missing history only after coverage is known and broker availability is checked. The requested five/ten-year reports must say unavailable or partial when the stock/data lacks that history.

### T1.2 Preserve signal rules; change execution explicitly

Freeze a versioned copy/hash of the original strategy and reproduce its baseline first. Preserve HA recursion/seed across sessions; BB(20, 2) on HA close with population standard deviation; existing signal bullish/zero-lower-wick conditions; session real-HLC3 VWAP; existing volume filter by default (20 prior full sessions, RVOL >= 2). Short signals mirror the pattern with bearish/zero-upper-wick and lower BB. Keep configurable original breakout source, stop source and exit mode; default target remains 2R unless selected otherwise.

New execution state per symbol: `FLAT`, `ARMED_LONG`, `ARMED_SHORT`, `LONG`, `SHORT`.

1. At signal-bar close, evaluate the unchanged completed HA/BB signal criteria and existing signal-time filters. Store signal time and HA high/low; also retain real OHLC for diagnostics and the original configurable real stop source.
2. Arm the immediately following bar only. A long enters on a real traded-price break strictly above signal high while price is above the causally available VWAP; short mirrors below signal low and below VWAP. Do not wait for the entry bar to close or defer to a third candle. Use instrument tick size to define strict crossing and adverse slippage for fills.
3. If that bar produces no valid entry, expire the old signal at its close. Evaluate that completed bar as a replacement signal and arm its successor when eligible. Repeat within the session. No signal is carried overnight.
4. After SL/TP closes a trade, resume signal evaluation and allow later long or short entries that day. Remove the three-trades/day limit and the single portfolio-wide position restriction.
5. Track simultaneous positions across stocks. Proposed default is one open position per stock, with unlimited sequential re-entry. Pyramiding multiple overlapping entries in the same stock is a separate policy to clarify, because “as many trades as come” does not specify it.

**Execution decisions to settle before calling results final:**

- The current original signal requires a fresh crossing from inside to outside the band. The user's replacement example may instead mean any qualifying candle still outside the band. Keep fresh-cross behavior as the primary preservation interpretation; expose a separately named continuation variant and obtain clarification before presenting it as the requested baseline.
- Existing completed confirmation-bar HA color/wick/close filters cannot be known at an intrabar entry. Preserve completed **signal** candle rules, replace the close-confirmation stage with the requested price/VWAP trigger, and label the change. Do not accidentally use future final HA values to claim those confirmation filters were met.
- Proposed trigger threshold retains the original signal HA high/low; offer real signal high/low as an explicit comparison if the user intended normal-candle extremes. Never fill at an unreachable synthetic HA price; real market data must cross the threshold.
- Original entry end is 15:00 and square-off is 15:20. The new request says traverse until day end. Proposed enhanced behavior permits entries until immediately before configured square-off, retaining 15:20 square-off initially; confirm whether the user wants a later market-close policy. Label timing in every report.
- VWAP at an actual tick can be computed from contemporaneous trades. Historical OHLCV cannot recover exact trade sequence or tick VWAP. Primary reproducible bar test uses the latest fully completed execution sub-bar's session HLC3 VWAP at the crossing opportunity; label this approximation and optionally compare a causal tick replay when data exists. Never use the entry bar's eventual HLC3/volume to qualify an earlier crossing.

For five-minute signals, replay available one-minute execution bars; for one-minute signals use ticks/sub-minute data if available, otherwise an explicitly approximate OHLC execution model. Gap through entry fills at real open plus adverse slippage when filters are valid. A bar touching both stop and target requires an ambiguity flag and conservative stop-first convention. When entry/exit ordering itself is unknown, report conservative and alternate sensitivity rather than invent timestamps; do not count an unknowable same-bar re-entry. Store event time precision. Reject invalid stop distance, zero affordable quantity and missing required data with reasons.

### T1.3 Capital and metric contract

Interpret INR 100,000 per trade as a fixed notional allocation, not stop-risk or total portfolio capital: whole-share quantity is `floor(100000 / executable_entry_price)`, with entry costs recorded separately. Keep allocation fixed after wins/losses. Respect lot size where applicable. Model equity intraday shorts as intraday positions with square-off. Broker margin/leverage is a separate optional model, not an assumed funding benefit.

Provide two clearly labeled views: all valid opportunities with sufficient simulated funding, and optional constrained-capital replay. The first must disclose the funding it required; it cannot imply all concurrent trades fit inside one lakh. Use a fixed, disclosed starting-capital denominator for portfolio returns, daily marked-to-market equity/drawdown, and Sharpe. External top-ups, if modeled, are cash flows rather than profits. Daily Sharpe uses daily portfolio returns, a stated annualization convention/risk-free input and no trade-level annualization; zero variance/insufficient observations return N/A. Per-stock reference capital starts at the declared allocation plus any explicitly modeled fee reserve, and depletion is flagged.

Reports per stock AND timeframe include gross P&L, itemized costs, net P&L, return denominator, maximum marked-to-market drawdown in INR and %, win rate, Sharpe, trades, long/short breakdown, average win/loss, profit factor, expectancy, holding duration, exclusions and ambiguous fills. Record actual entry/exit, SL/TP, quantity, signals, strategy/data hashes, cost assumptions and research variant.

Daily capital table: trade count, sum of entry notionals/turnover, peak simultaneous notional, peak margin if available, peak concurrent positions, cumulative P&L, cash/funding requirement including fees/losses, and end-of-day equity. Turnover is not required capital. Reconcile daily trades and P&L to ledger and portfolio totals.

Aggregate per stock/timeframe for calendar month, quarter, half-year (Jan–Jun/Jul–Dec), year, five-year and ten-year windows. Use calendar-aligned multi-year blocks with documented anchor, plus trailing five/ten-year summaries when complete history exists. Flag partial windows. Trade counts/wins belong to exit period; period equity P&L and drawdown come from marked-to-market equity, including boundary positions. Never add percentage drawdowns or average monthly Sharpes to produce annual statistics.

Deliver an offline interactive HTML report, machine-readable CSV/Parquet/JSON tables, equity/drawdown charts, ranked stock summary, drill-down trade ledger, daily capital use, period tables, source coverage and assumptions. Include stock buy-and-hold and NIFTY benchmarks only where authentic aligned history is available; otherwise label unavailable. Rankings distinguish insufficient history/no trades from poor results. The user chooses stocks afterward.

### T1.4 Automated research with the entry pattern frozen

Version the baseline above; run a bounded experiment registry varying only additional filters/exits: EMA trend/slope, ADX strength, ATR regime, RSI momentum, relative-volume variations, VWAP distance/slope, time windows and stop/target/trailing alternatives. VWAP and the requested candle/BB trigger remain mandatory; do not quietly replace them. Preserve baseline RVOL and compare alterations as named experiments. Use causal OpenAlgo TA where new indicators are needed, validated against fixtures.

Use chronological train/validation/test splits with warmup outside scored periods, walk-forward evaluation, untouched final holdout, predeclared search budget/objective, minimum trade counts, cost/slippage stress and parameter-neighborhood stability. Select on training/validation only; record all trials, failed trials, seeds, data hashes and drawdown/capital tradeoffs. Do not optimize separately on each stock's entire history and present it as out-of-sample performance. Research produces a comparison report, never automatic deployment.

Acceptance: hand-checked long/short rollover examples; next-bar intrabar entry; VWAP rejection; multiple later re-entries; concurrent stocks; 1m/5m alignment; no future indicator access; gap and ambiguous-fill rules; whole-share one-lakh sizing; deterministic resumable imports; period/ledger/capital reconciliation; and explicit missing-history outcomes. Complete baseline all-stock reporting before optimizing.

## Task 2 — Built-in live scanner for all supported brokers

Extend the existing scanner provider/manager/DB/routes/tests rather than creating a second scanner engine. Replace Fyers-only routing with a broker-capability adapter using common quote/history/instrument services. Preserve ranking/filter semantics and cached baseline history.

Add a Scanner navigation item/page: Volume Shockers, Top Gainers, Top Losers, universe/exchange filters, volume/RVOL/price filters, live status, update time, coverage and partial/error states. Persist preferences and auto-start setting; default the new feature to automatic startup once enabled/installed per the requested behavior. Running `app.py` initializes orchestration; scanning waits for valid broker login and automatically attaches after login/reconnection. No separate terminal command is required.

Seed quotes in batches, then reuse the existing shared WebSocket feed. Use throttled updates to the browser and rate-limited polling when a broker lacks streaming/batching. Implement subscription limits, reconnect/resubscribe, backoff, token refresh, market-open scheduling and stale-data labels. Missing volume/history must show unavailable RVOL, not zero. Crypto universes, if exposed, use their own 24/7 schedule and explicit rolling/session volume definition.

Use a single elected scanner worker/lease per instance/account across Flask reloads and production workers. Persist control state; stop/release resources on logout/shutdown. Avoid a new broker socket per tab or full-universe historical download every refresh. Broad broker support means each adapter declares capabilities and falls back honestly; keep an explicit verified-broker matrix, not a claim that untested brokers passed.

Acceptance: app startup + broker login alone produces updates; two browser tabs share work; broker switch isolates data; non-Fyers supported adapter works; unsupported volume degrades clearly; 429/disconnect/token expiry recovers; duplicate workers are prevented; ranking tests remain valid; DB sessions/subscriptions/threads close correctly. Run applicable resource/FD audit on implementation.

## Task 3 — Crypto calculator in AlgoMirror and concurrent Indian/crypto use

Implement in AlgoMirror using the two existing OpenAlgo hosts, with no code changes to either protected backend for this task. Audit existing account model, `app/utils/margin_calculator.py`, `app/templates/margin/calculator.html`, connection clients and risk-monitor assumptions first.

Persist per-connection broker/market identity, API/WS hosts, account label and capabilities. Resolve calculator behavior from the selected account's verified broker (`deltaexchange`), not a global browser login flag. Provide Indian, Crypto and Both account views. Simultaneous background quotes, balances and positions must remain connected while the user changes foreground account.

Use a common calculator view model and separate equity/Indian-derivatives/Delta adapters. Inputs: instrument, long/short, capital or quantity, entry mode/price, product-specific leverage, TP/SL, trigger source and supported order flags. Outputs: integer contracts/lots, underlying units, notional, required/available margin, fee breakdown, SL/TP P&L and risk/reward with labeled currencies. Preserve existing Indian sizing and fee behavior with regression fixtures.

Delta inputs follow screenshots: Market, Limit, Maker Only/post-only, stop market/limit, trailing stop, TP market/limit; allocation presets 10/25/50/75/100%; TP/SL percentage presets; mark/last/index trigger source; reduce-only and supported time-in-force. Support these progressively only when the complete server/API route supports them. A calculator estimate must not change leverage or submit an order; explicit order submission is a separate existing user action.

Read paginated `/v2/products` metadata and appropriate ticker data through supported adapters. Use product contract value/type, tick/size constraints, quote/settlement/underlying assets, initial/maintenance margin scaling and fee fields. Obtain account balances/leverage through existing authenticated backend APIs; keep Delta secrets server-side. The local API notes describe `POST /v2/products/{product_id}/orders/leverage`, order bracket fields, `post_only`, `reduce_only`, and mark/last/spot trigger enums. Audit that OpenAlgo request validation/SDK/mapping preserves them end to end; existence of broker functions alone is insufficient.

For a supported linear contract, indicative notional is contracts × base-unit contract value × price; initial leverage-only margin estimate is notional/leverage; long/short gross P&L is signed contracts × contract value × price change. Use Decimal arithmetic, correct rounding, currency conversion and fees. Actual tiered/cross/portfolio margin can differ: use broker-provided requirements where exposed and label estimates otherwise. Reject unsupported inverse/option formulas until dedicated adapters exist. Never hardcode screenshot ETH lot size, 200x/20x, USD/INR conversion or a retail fee tier. Account-specific maker/taker rates, applicable tax, funding assumptions and data timestamp must be visible in estimates; estimate liquidation only with a validated margin-mode model.

Where an unchanged OpenAlgo backend lacks metadata, AlgoMirror may fetch public Delta metadata server-side. Where it lacks a required authenticated operation, record the gap and expose estimate-only/unavailable behavior for that operation; do not silently add a second credential store or direct order route. Deliver a precise capability-gap report for any separately authorized follow-up.

Acceptance: deterministic sizing/rounding/fee examples; differing ETH/VVV-style contract sizes and leverage caps; long/short P&L; insufficient funds and stale metadata; maker-only restrictions; partial-fill/TP-SL lifecycle for supported submission paths; Indian calculator regression; two simultaneous hosts without session/cache/stream crossover; Indian logout does not stop crypto. Unsupported product/order capabilities are visible and truthful.

## Task 4 — Complete web UI refresh with dynamic themes

Build a route/component inventory covering every existing OpenAlgo user surface: auth/dashboard, charting/order calculator, books/positions/holdings/funds, watchlists, scanner, sandbox, Historify, tools, strategy/RMS, Flow, Python host, logs/settings and other registered routes. Define migration status per route so “all UI” does not stop after a dashboard mockup.

Create central design tokens for semantic colors, typography, spacing, radii, borders, shadows, chart palettes, density and motion. Provide light/dark/system themes plus selectable accent palettes, font and density preferences. Persist preferences and apply before first paint. Maintain distinct gain/loss/warning/live/sandbox meanings across themes, accessible contrast/focus and reduced motion.

Use MUI components for the React UI and Tailwind/CSS for layout and styling, backed by the same CSS variables. Follow official CSS layer integration (`theme, base, mui, components, utilities`) so resets/overrides remain predictable. Verify installed React/MUI compatibility; migrate shared components in stages rather than loading conflicting resets throughout every page at once. Preserve chart interactivity, keyboard shortcuts, dense financial tables and numeric precision.

AlgoMirror is Jinja/Tailwind v3/DaisyUI: apply matching CSS tokens there, and decide explicitly whether its calculator merits an isolated React/MUI component. A whole-app React rewrite is not an implied dependency. Flutter uses native Material 3 equivalents with shared token values, not CSS/Tailwind binaries.

Acceptance: complete route checklist; responsive desktop/tablet/phone layouts; theme persistence; keyboard/screen-reader flows; chart/table colors; loading/error/empty states; visual review and targeted interaction regression; frontend typecheck/lint/build and relevant tests.

## Task 5 — Mobile app matching OpenAlgo functionality

Extend the existing Flutter app in `D:\Personal\openalgo-mobile`. Build a parity matrix from the actual OpenAlgo route/API inventory, including every surface listed in T4 and new T1 reports, T2 scanner, T3 calculators/account selection, and T6 portfolios. Classify existing, incomplete, missing, and backend-API-needed features. Do not call the app a full mirror while screens are placeholders or browser-session-only features cannot be used.

Retain native Material 3 and adapt navigation/tables/chart controls for touch. Provide multiple saved Indian/crypto server profiles and concurrent account overview with unmistakable server, broker, currency and live/sandbox badges. Backend calculations remain the source of truth. Implement shared API contracts, typed models, capability discovery, errors, idempotent submission handling and contract tests. Native mobile cannot simply invoke CSRF/browser-session endpoints with an API key: add scoped supported APIs in the permitted development backend where required.

Use platform secure storage for credentials; review actual current storage behavior instead of trusting README security claims. Stream through existing WebSocket services, handle app pause/resume/token expiry/reconnect, and mark cached quotes stale/offline. Never queue trading orders for an automatic send after reconnection. Mobile is a client; persistent scanner/strategy/sandbox monitoring runs on the server.

Deliver incrementally: (a) connection/auth/account state and themes; (b) trading, charts, calculators, books/funds/positions; (c) scanner/watchlists/sandbox portfolios and backtest reports; (d) strategy/tools/Historify/Flow/Python/settings/logs parity. For complex editors, explicitly specify a functional responsive editor or authenticated embedded server view and track its limitations; do not replace required functionality with a “coming soon” page. Android is the initial existing platform target; preserve Flutter Web and record additional platform work separately.

Acceptance: end-to-end parity checklist against web; Android device/emulator and Flutter Web smoke tests; secure credential lifecycle; two-profile isolation; live updates and background recovery; sandbox actions never invoke live trading; `flutter analyze`, meaningful unit/widget/integration tests and a reproducible APK build. Report unsupported capabilities explicitly until implemented.

## Task 6 — Sandbox investment watchlists and portfolio tracking

Add a sandbox Investment Portfolio section with named watchlists categorized as Swing, Positional, Long-term and Mutual Funds. Reuse existing server watchlist identity/persistence where appropriate, while separating a symbol-to-watch from an actual recorded purchase. Entries support instrument, exchange/scheme ID, entry price, quantity/units, purchase date/time, optional SL/TP, notes and current quote/NAV with valuation timestamp.

Use a transaction ledger for recorded buys/sells, partial exits, fees, adjustments and optional dividends/cash flows. Derive open lots, remaining quantity, weighted cost, realized/unrealized P&L, invested amount, market value, return and days held. Preserve original purchase timestamps and an audit history of corrections. A symbol can exist in several styles without merging ownership accidentally. Scope all data by instance/user, sandbox portfolio and instrument identity; include connection identity where multiple hosts are aggregated.

Suggested additive tables: `investment_portfolios`, `investment_watch_items`, `investment_transactions`, `investment_lots` (or derived lot views), `investment_valuations`, `investment_events`. Use Decimal monetary values and fractional units for mutual funds. Document FIFO or weighted-cost realization policy and keep it consistent. Keep fees/cash and corporate-action adjustments visible; do not overwrite entry price with current quote.

For the user's ATHER ENERGY example: buy 100 at INR 1,000 -> invested INR 100,000; SL 900, TP 1,200. At price 1,100, unrealized gain is INR 10,000 (+10%) before fees; at 950 it is a INR 5,000 loss (-5%). Display purchase date, days held, current price/as-of time, SL/TP distance, quantity and style totals. Display risk to SL and gain to TP separately from realized results.

Default behavior is tracking/alert-only for SL/TP. A recorded historical purchase does not place a broker order, spend live cash or reset the intraday sandbox balance. If desired later, an explicitly selected simulated auto-exit policy can create paper ledger exits with a documented fill model. Do not attach swing/long-term entries to MIS daily square-off. Restart/offline monitoring cannot prove a missed threshold event from current LTP alone; show unknown/history-derived events with their source.

Mutual funds use scheme identifiers, fractional units and dated NAV, rather than exchange tick quotes unless the instrument is actually an ETF. NAV source/update frequency must be verified during implementation; stale or unavailable NAV is labeled. Record SL/TP if requested, but treat them as NAV-based watch thresholds, not intraday executable stops. Support multiple purchases/SIP transactions and redemptions without rewriting history.

Expose sandbox-only authenticated CRUD/ledger/valuation endpoints and common mobile contracts. Add style lists, detail timeline, transactions, portfolio summary, P&L charts and CSV export. The existing sandbox reset action must explicitly describe whether it affects these longer-lived portfolios; default preserve them unless the user chooses to reset/archive them.

Acceptance: exact ATHER example; multi-lot purchases, partial sale and fees; style isolation; fractional MF units/NAV staleness; persistence/restart; no daily square-off; no live endpoint calls; identical web/mobile valuation; schema migration preserving existing watchlists/sandbox history.

## Task checklist and next-agent procedure

| ID | Deliverable | Status |
|---|---|---|
| PLAN | Repository/source review, six-task plan, durable handoff | Complete |
| P0 | Resolve code-freeze boundary; safe development workspace; API/data inventory | Pending |
| T1.1 | CSV catalog, DuckDB ingestion, coverage and missing-history report | Pending |
| T1.2 | Baseline reproduction and approved enhanced execution contract | Pending |
| T1.3 | All-stock 1m/5m reports and daily capital reconciliation | Pending |
| T1.4 | Bounded filter/exit research and holdout comparison | Pending |
| T2 | Broker-neutral scanner service and automatic live UI | Pending |
| T3 | AlgoMirror shared calculator, Delta adapter, simultaneous accounts | Pending |
| T4 | Theme foundation and full route-by-route UI migration | Pending |
| T5 | Flutter parity matrix, implementation and Android artifact | Pending |
| T6 | Sandbox style portfolios, ledger, valuations and watch thresholds | Pending |

Resume by reading root `AGENTS.md`, this file, then `context.md` for prior implementation history and `docs/INDEX.md` for canonical references. Check current Git status in every target repo and applicable nested instructions before editing. Do not redo the planning pass or treat older task numbers as these tasks.

Next concrete work: settle the original-tree boundary and T1 execution ambiguities when implementation is requested; meanwhile perform read-only CSV schema/coverage and account API capability inventory. Default to preserving original trees. Full all-stock coverage, exact backtest metrics, broker capability verification, installed runtime behavior, mobile builds and screenshot interaction tests are not yet performed.

At each milestone update this file with date, completed checklist rows, changed files, commands/results, data/run IDs, remaining decisions and next command. Keep credentials and account payloads out. Do not mark implementation complete merely because a plan or test scaffold exists.
