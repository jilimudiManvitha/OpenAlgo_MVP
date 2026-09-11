# Six-task implementation plan and agent handoff

Updated: 2026-09-11, Asia/Kolkata. Status: Task 1 baseline validation in progress. Isolated scanner-selected partial-day replay now completed for September 11 through 12:26 IST, with 48 individual trade charts. Full-history validation and production scanner integration remain pending. See the current-stage summary and latest milestone below.

This is the canonical plan for the user's six tasks from 2026-09-11. The task numbers below belong to this request; similarly numbered historical tasks in `context.md` are different work. Read this plan before resuming implementation. All future progress belongs in the checklist and handoff section here.

## Current stage — after the scanner-based strategy update

We are at **Task 1 baseline validation**, before full-history backtesting or optimization. Completed evidence: inventory of 93 CSVs and metadata for 1,573 NSE stocks; four provisional unrestricted reports for ATHERENERG/RELIANCE at 1m/5m; and now a separate scanner-selected partial-day replay through September 11 12:26 IST. The latter reconstructs 191 minute-level snapshots, produces 48 trade charts, and has eight focused execution/gating tests plus ledger/data/browser verification. These remain research artifacts, not a deployed strategy.

The existing Fyers scanner produced a verified September 11 intraday snapshot and standalone top-50 report. This is partial Task 2 progress: the integrated automatic live UI, broker-neutral support, category filters and sparklines remain pending. Tasks 3–6 have not started. The original-code boundary remains unresolved, so implementation continues in the isolated development copy.

**Latest user change:** Task 1 should take trades only from Volume Shockers, Top Gainers or Top Losers; the user then requested today's scanner, a backtest and a plot of each trade, and asked to resume the interrupted work. The contract is in **T1.2a** below. That bounded replay is complete for its frozen 12:26 IST cutoff; it does not include the afternoon or a full-history comparison. No live order has been placed. The next milestone is broader execution/data validation and comparison against the unrestricted reference before scaling.

## Scope and repository boundaries

The user originally asked to plan first and save enough memory for a restarted or different agent. That planning session changed documentation only. Later authorized resumption added isolated research code/reports and ran the existing market-data scanner; those milestones are recorded below. Original application code and credentials remain unchanged, and no live orders have been placed.

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
2. T1: establish historical data coverage and reproduce the original baseline; bring forward T2's shared ranking/snapshot contract to implement T1.2a scanner-based selection, then produce the requested baseline reports before research variants. The full T2 UI is not a prerequisite for historical replay.
3. T3: implement account-aware calculator and simultaneous connection support in AlgoMirror.
4. T2: extend existing scanner and expose its live UI using the common theme foundation.
5. T6: add persistent sandbox investment watchlists and portfolio ledger.
6. T4: complete theme/component migration across the web route inventory; foundation starts at P0 so new pages already match.
7. T5: deliver mobile parity in batches against stable backend APIs, then integrated verification of all clients.

This is a dependency order, not a claim that implementation has been authorized to modify protected original code. No automatic live strategy deployment follows a good backtest.

## Task 1 — All-stock strategy, DuckDB, reports and automated research

“All-stock” now describes the universe scanned and historical data coverage. **The requested trading variant enters only eligible stocks from the scanner lists defined in T1.2a.** Keep the prior unrestricted variant as a clearly labeled reference for comparison, not as the updated requested strategy.

### T1.1 Data catalog and reusable ingestion

Inventory CSVs from `stock_symbols_CSVs`, `backtesting`, existing historical export folders including `D:\Personal\historify_ATHERENERG_20260908_112029`, and any further user-designated data folders. Read headers and classify OHLCV, universe/screener snapshots, charges/reference data, and generated outputs. Catalog every CSV and preserve its source; import useful data into the appropriate tables. Generated HA candles, trade reports and repeated normalized exports must not become independent raw-price history.

Use a dedicated research DuckDB with `source_files`, `instruments`, `universe_snapshots`, `raw_imports`/quarantine, normalized `ohlcv`, `coverage`, and `backtest_runs`. Historical timestamps should be unambiguous UTC instants with exchange timezone metadata. Unique candle identity: instrument/exchange + interval + bar-open timestamp + declared data version/source policy. File manifest stores path, hash, schema, imported row counts and errors. Imports are idempotent; conflicting duplicates are reported instead of silently overwritten. Snapshot datasets without a trustworthy as-of date must retain an unknown date, not an inferred historical one.

Validate OHLC ranges, positive prices, nonnegative volumes, timestamps, session calendars, duplicates, missing bars, incomplete sessions and corporate-action treatment. Resolve company display names to exchange symbols using instrument masters with unresolved mappings reported. Retain source/adjustment metadata; never mix adjusted and unadjusted series silently. Universe membership is point-in-time where available; label survivorship bias otherwise.

Use actual one-minute OHLCV for 1m tests; aggregate it into five-minute candles aligned to 09:15 IST for regular Indian sessions. Five-minute-only data supports 5m signal tests, not invented 1m data. Reuse Historify through supported readers or a consistent snapshot/export; separate ingestion writer from read-only research workers. Large imports and runs are chunked/resumable, with an immutable data version per run.

Deliver coverage per stock/timeframe: earliest/latest candle, rows, valid sessions, gaps, warmup eligibility, available years and exclusions. Request/backfill missing history only after coverage is known and broker availability is checked. The requested five/ten-year reports must say unavailable or partial when the stock/data lacks that history.

### T1.2 Preserve signal rules; change execution explicitly

Freeze a versioned copy/hash of the original strategy and reproduce its baseline first. Preserve HA recursion/seed across sessions; BB(20, 2) on HA close with population standard deviation; existing signal bullish/zero-lower-wick conditions; session real-HLC3 VWAP; existing volume filter by default (20 prior full sessions, RVOL >= 2). Short signals mirror the pattern with bearish/zero-upper-wick and lower BB. Keep configurable original breakout source, stop source and exit mode; default target remains 2R unless selected otherwise.

New execution state per symbol: `FLAT`, `ARMED_LONG`, `ARMED_SHORT`, `LONG`, `SHORT`.

1. At signal-bar close, require eligibility under T1.2a, then evaluate the unchanged completed HA/BB signal criteria and existing signal-time filters. Store signal time and HA high/low; also retain real OHLC for diagnostics and the original configurable real stop source.
2. Arm the immediately following bar only. Recheck scanner eligibility using the latest valid snapshot available before entry. A long enters on a real traded-price break strictly above signal high while price is above the causally available VWAP; short mirrors below signal low and below VWAP. Do not wait for the entry bar to close or defer to a third candle. Use instrument tick size to define strict crossing and adverse slippage for fills.
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

### T1.2a User update — scanner-based trade selection (2026-09-11)

**Requested:** take/place strategy trades in stocks from Volume Shockers, Top Gainers or Top Losers. Status: isolated minute-by-minute reconstruction and entry gating implemented and exercised on one partial day; broader acceptance and live integration remain pending. This changes stock eligibility for the planned strategy, not the HA/BB/VWAP entry pattern. It does not authorize placing live orders during research.

**Working defaults for implementation:**

| Rule | Contract |
|---|---|
| Candidate lists | Top 50 Volume Shockers, top 50 positive daily gainers, top 50 negative daily losers, each ranked across the entire configured eligible universe |
| Combined universe | Union of the three lists: membership in any one is sufficient; deduplicate by exchange/instrument identity, at most 150 unique candidates per snapshot |
| Trade direction | Preserve strategy signals: bullish setup can enter long; bearish setup can enter short. List membership alone does not force a direction. Restricting gainers to longs/losers to shorts would be a separately named policy, not an assumed user requirement |
| Entry gate | Require membership when arming the completed signal and immediately before an executable entry, using only a valid snapshot already available at each decision |
| Refresh | Historical working default: recompute rankings at each completed one-minute bar, available for the next execution bar; both 1m and 5m signals consume that same causal schedule. Live target uses shared streaming/cached data with an explicit snapshot availability time, not a new full history scan every minute |
| Stale/missing selection | Block new entries when the required snapshot is missing, from another session/account, or older than the configured freshness limit (initial working value: 60 seconds after availability). Record the reason; do not fall back silently to unrestricted trading |
| Membership changes | Newly selected stocks can arm qualifying signals once indicators are warmed. Removal invalidates an armed unfilled signal. Existing positions continue their normal SL/TP/square-off management; removal alone does not force an exit |
| Sizing and exits | Retain INR 100,000 fixed notional per trade, whole-share sizing, one position per stock, simultaneous positions across stocks, later re-entry, and the existing planned SL/TP/square-off contract |

These defaults make the requested update executable and reviewable; the user has not separately specified direction restrictions, a different list size, refresh interval or an intersection of the lists.

**Ranking and indicator preservation:** reuse T2's ranking mathematics and deterministic tie-breaking. Volume shockers initially require scanner RVOL > 1 against the previous five completed full-session volume totals; rank by RVOL descending. Gainers/losers use change from the verified previous trading-session close, with positive descending/negative ascending ranking. Apply category and instrument eligibility before top-50 selection, and report fewer than 50 when appropriate. A selected category is versioned in the run; initial historical scope is the available validated NSE stock universe, with coverage exclusions disclosed.

The scanner's five-session RVOL and the strategy's existing **20-session RVOL >= 2** are separate gates. Keep both and record both values/definitions. Do not disable the strategy volume filter merely because a stock was selected as a gainer or loser; any relaxation is a named research comparison. Calculate/warm indicators over each stock's available history even while it is outside the lists, so entering a list does not reset HA or VWAP.

**Historical selection must be reconstructed at the time of each decision:**

- Use prices, cumulative volume and completed daily baselines known by that snapshot's cutoff. The current execution bar's eventual high/low/close/volume and final day rankings cannot qualify an earlier entry. The September 11 11:36 snapshot is usable only from its actual availability time; it cannot choose stocks for that morning or prior years.
- Reconstruct rankings jointly across all eligible instruments at a common historical cutoff, before stock-level execution. Independently backtesting each stock and filtering its completed trades by today's list is not a valid implementation. A symbol with unavailable/stale bars is excluded with its reason; do not fabricate a current price by unlimited forward filling.
- Store `scanner_snapshots` and `scanner_memberships` (or equivalent versioned tables) with snapshot ID, market cutoff, availability time, session, source/account scope where applicable, universe/data version, ranking config, list/rank, instrument, quote/baseline timestamps, price change, cumulative/average volume, RVOL, coverage and exclusions. Preserve the actual refresh/availability delay for recorded live snapshots. Declare the assumed availability delay for historical bar reconstruction.
- Existing 1,573-stock history does not reproduce the full 2,642-instrument live scanner universe automatically. Mark historical results as rankings within the validated available-history universe; measure missing members and survivorship limitations. Separate equities from broker-classified ETFs for stock-only runs, using verified instrument metadata. Do not label missing-universe or unverified-previous-close periods as full-market rankings.
- The current terminal scanner is a slow one-off snapshot producer. Its successful run does not establish a continuously fresh live trade-selection service. Historical ranking can be implemented now; live strategy integration depends on T2's shared updates, freshness/coverage controls and existing order lifecycle integration. If live entry orders are later supported, reconcile fills and cancellation acknowledgements before treating an order as cancelled after membership removal.

**Reports and acceptance:** every entered trade records signal/entry snapshot IDs, source-list tags, ranks, scanner RVOL/price change, strategy RVOL and eligibility decisions. Record rejected signals separately. Compare unrestricted reference versus scanner-selected strategy on identical dates, validated universe, data version, costs and execution settings; display trade count, P&L, drawdown and peak funding differences. Breakdowns by list must disclose overlapping membership and must not double-count trades in portfolio totals.

Required tests: inclusion through each list; union versus intersection; top 50 after full-universe ranking; overlap producing one order/trade; long/short direction remaining signal-driven; candidate arrival/removal before entry; open-position management after removal; stale/missing snapshots blocking entries; future price/volume changes leaving earlier selections unchanged; 1m/5m timing; indicator continuity across membership changes; both volume filters retained; partial historical universe labeling; and ledger/snapshot attribution reconciliation. Run a bounded multi-stock replay that exercises competing ranks before attempting the full history or optimization. The existing two-stock smoke tests do not satisfy this acceptance.

### T1.3 Capital and metric contract

Interpret INR 100,000 per trade as a fixed notional allocation, not stop-risk or total portfolio capital: whole-share quantity is `floor(100000 / executable_entry_price)`, with entry costs recorded separately. Keep allocation fixed after wins/losses. Respect lot size where applicable. Model equity intraday shorts as intraday positions with square-off. Broker margin/leverage is a separate optional model, not an assumed funding benefit.

Provide two clearly labeled views: all valid opportunities with sufficient simulated funding, and optional constrained-capital replay. The first must disclose the funding it required; it cannot imply all concurrent trades fit inside one lakh. Use a fixed, disclosed starting-capital denominator for portfolio returns, daily marked-to-market equity/drawdown, and Sharpe. External top-ups, if modeled, are cash flows rather than profits. Daily Sharpe uses daily portfolio returns, a stated annualization convention/risk-free input and no trade-level annualization; zero variance/insufficient observations return N/A. Per-stock reference capital starts at the declared allocation plus any explicitly modeled fee reserve, and depletion is flagged.

Reports per stock AND timeframe include gross P&L, itemized costs, net P&L, return denominator, maximum marked-to-market drawdown in INR and %, win rate, Sharpe, trades, long/short breakdown, average win/loss, profit factor, expectancy, holding duration, exclusions and ambiguous fills. Record actual entry/exit, SL/TP, quantity, signals, strategy/data hashes, cost assumptions and research variant.

Daily capital table: trade count, sum of entry notionals/turnover, peak simultaneous notional, peak margin if available, peak concurrent positions, cumulative P&L, cash/funding requirement including fees/losses, and end-of-day equity. Turnover is not required capital. Reconcile daily trades and P&L to ledger and portfolio totals.

Aggregate per stock/timeframe for calendar month, quarter, half-year (Jan–Jun/Jul–Dec), year, five-year and ten-year windows. Use calendar-aligned multi-year blocks with documented anchor, plus trailing five/ten-year summaries when complete history exists. Flag partial windows. Trade counts/wins belong to exit period; period equity P&L and drawdown come from marked-to-market equity, including boundary positions. Never add percentage drawdowns or average monthly Sharpes to produce annual statistics.

Deliver an offline interactive HTML report, machine-readable CSV/Parquet/JSON tables, equity/drawdown charts, ranked stock summary, drill-down trade ledger, daily capital use, period tables, source coverage and assumptions. Include stock buy-and-hold and NIFTY benchmarks only where authentic aligned history is available; otherwise label unavailable. Rankings distinguish insufficient history/no trades from poor results. The user chooses stocks afterward.

### T1.4 Automated research with the entry pattern frozen

Version the scanner-selected baseline above; run a bounded experiment registry varying only additional filters/exits: EMA trend/slope, ADX strength, ATR regime, RSI momentum, relative-volume variations, VWAP distance/slope, time windows and stop/target/trailing alternatives. Scanner selection, VWAP and the requested candle/BB trigger remain mandatory in this baseline; do not quietly replace them. Preserve baseline RVOL and compare alterations as named experiments. Use causal OpenAlgo TA where new indicators are needed, validated against fixtures.

Use chronological train/validation/test splits with warmup outside scored periods, walk-forward evaluation, untouched final holdout, predeclared search budget/objective, minimum trade counts, cost/slippage stress and parameter-neighborhood stability. Select on training/validation only; record all trials, failed trials, seeds, data hashes and drawdown/capital tradeoffs. Do not optimize separately on each stock's entire history and present it as out-of-sample performance. Research produces a comparison report, never automatic deployment.

Acceptance: hand-checked long/short rollover examples; next-bar intrabar entry; VWAP rejection; multiple later re-entries; concurrent stocks; 1m/5m alignment; no future indicator access; gap and ambiguous-fill rules; whole-share one-lakh sizing; deterministic resumable imports; period/ledger/capital reconciliation; and explicit missing-history outcomes. Complete baseline all-stock reporting before optimizing.

## Task 2 — Built-in live scanner for all supported brokers

Extend the existing scanner provider/manager/DB/routes/tests rather than creating a second scanner engine. Replace Fyers-only routing with a broker-capability adapter using common quote/history/instrument services. Preserve ranking/filter semantics and cached baseline history.

### User additions recorded 2026-09-11 — volume changes, categories and sparklines

These additions extend Task 2; they are saved requirements, not implemented behavior.

- **Volume Shockers: show 50 stocks**, ranked by volume increase/RVOL descending. Scan the full selected universe before taking the top 50; do not scan only 50 symbols. If fewer than 50 qualify, show the actual count and coverage instead of padding results.
- Each row shows stock name/symbol, a very small intraday price line chart (sparkline), LTP, **today's price change %**, today's cumulative traded volume, **volume change %**, and RVOL. Keep price change and volume change in separately labeled columns. Price change % = `(LTP / previous trading session close - 1) * 100`; do not use today's open or yesterday's calendar date as the default reference.
- Volume change % = `(today's cumulative volume / selected baseline volume - 1) * 100`; RVOL uses the same baseline, so 2.5x means +150% volume change. Initially retain the existing configurable average of the prior five completed trading sessions, excluding today. Label it “Volume change vs 5-session average” (or the selected lookback), not an unlabeled daily percentage. This compares today's partial cumulative volume to historical full-day volume; expose that basis in the tooltip. An explicit “vs previous session” baseline may also be selected. Add a separately labeled same-time historical-volume baseline only when intraday history exists; never silently mix the modes. Missing/zero baseline produces N/A, not infinity or 0%.
- **Top Gainers and Top Losers: category/index filters** for All stocks, Nifty 50, Nifty 100, Nifty Next 50, Midcap and Smallcap. Midcap supports the available Nifty Midcap 50/100/150 constituent sets; Smallcap supports Nifty Smallcap 100/250. Default broad category mappings are Midcap 150 and Smallcap 250, with the exact index name visible. Also expose Nifty 200/500 where the supplied constituent lists are imported. Start with a single-select category filter, persist it, and apply it before ranking/limiting. Make the same filter usable on Volume Shockers for consistent navigation.
- Use the local `stock_symbols_CSVs/ind_nifty*list.csv` constituent files as import sources, including `ind_nifty50list.csv`, `ind_nifty100list.csv`, `ind_niftynext50list.csv`, `ind_niftymidcap150list.csv`, and `ind_niftysmallcap250list.csv`. Store normalized instrument membership, source, import time and effective/as-of date where known. Do not assume a snapshot is current without checking its provenance; show membership date or “date unknown” and provide a refresh path. Support legitimate overlap between index sets without duplicate rows within one result list. Match exchange symbols rather than fuzzy company-name text.
- Rank gainers by positive daily price change % descending and losers by negative daily price change % ascending **within the selected category**. Display daily price change % for every stock. Use a 50-row default for these tables too, with actual available counts; this extends the user's explicit 50-stock requirement for Volume Shockers consistently to the other tabs.
- **Sparkline in all three result tables:** put a compact line chart beside the stock name and daily change %. Use real timestamped intraday prices/minute closes from today's session, rendered in a small responsive SVG or equivalent lightweight component. Color by the sign of daily price change, include a neutral state, accessible text and an optional hover price/time. Keep numeric percentages legible without relying on color. Label the chart as price, not volume; it complements the volume columns.
- Seed sparklines from cached/batched intraday history where available, then append shared live-feed observations. Bound/downsample points for a small chart; avoid a heavyweight chart instance or separate polling/WebSocket connection per row. With only live observations, show the observed period as “since connected”; never fabricate the earlier session path. Preserve gaps and show stale/no-data states. Category switches reuse cached series, respect provider limits and reset series at the new trading session.

Illustrative row layout: `Stock name / symbol | small price line | LTP | Day change % | Today's volume | Volume change % | RVOL`. The gainers/losers views may keep volume fields secondary but must retain name, sparkline, LTP and day change %.

### Service and lifecycle

Add a Scanner navigation item/page: Volume Shockers, Top Gainers, Top Losers, universe/exchange filters, volume/RVOL/price filters, live status, update time, coverage and partial/error states. Persist preferences and auto-start setting; default the new feature to automatic startup once enabled/installed per the requested behavior. Running `app.py` initializes orchestration; scanning waits for valid broker login and automatically attaches after login/reconnection. No separate terminal command is required.

Seed quotes in batches, then reuse the existing shared WebSocket feed. Use throttled updates to the browser and rate-limited polling when a broker lacks streaming/batching. Implement subscription limits, reconnect/resubscribe, backoff, token refresh, market-open scheduling and stale-data labels. Missing volume/history must show unavailable RVOL, not zero. Crypto universes, if exposed, use their own 24/7 schedule and explicit rolling/session volume definition.

Use a single elected scanner worker/lease per instance/account across Flask reloads and production workers. Persist control state; stop/release resources on logout/shutdown. Avoid a new broker socket per tab or full-universe historical download every refresh. Broad broker support means each adapter declares capabilities and falls back honestly; keep an explicit verified-broker matrix, not a claim that untested brokers passed.

Acceptance: app startup + broker login alone produces updates; two browser tabs share work; broker switch isolates data; non-Fyers supported adapter works; unsupported volume degrades clearly; 429/disconnect/token expiry recovers; duplicate workers are prevented; ranking tests remain valid; DB sessions/subscriptions/threads close correctly. Run applicable resource/FD audit on implementation.

Additional acceptance for the user additions: top 50 is selected from the entire filtered universe; fewer matches remain truthful; a stock with LTP 110 and previous close 100 displays +10% regardless of today's open; cumulative volume 250,000 against baseline 100,000 displays +150% and 2.5x; zero/missing baseline gives N/A; each index filter excludes nonmembers before ranking; overlapping membership does not duplicate rows; gainers/losers use the correct sort direction; all three tabs show real small price charts with timestamps and missing-data states; category changes and 50 visible rows do not multiply broker connections or cause unbounded history requests.

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
| P0 | Resolve code-freeze boundary; safe development workspace; API/data inventory | In progress: isolated research copy created; original-tree boundary still unresolved; API inventory pending |
| T1.1 | CSV catalog, DuckDB ingestion, coverage and missing-history report | In progress: 93-file inventory and 1,573-stock catalog exported; full candle validation/ingestion acceptance pending |
| T1.2 | Baseline reproduction and approved enhanced execution contract | In progress: original selftest and indicator parity pass; isolated fresh-cross default corrected; original historical execution baseline and final contract pending |
| T1.2a | Scanner-based trade eligibility: union of volume shockers/gainers/losers, historical snapshots and entry gate | In progress: isolated 191-minute reconstruction/gated replay verified; full acceptance, latency/coverage studies and live integration pending |
| T1.3 | Full-universe scanner-selected 1m/5m reports and daily capital reconciliation | In progress: September 11 through 12:26 replay with 48 trade charts reconciles; afternoon/full-history reports and unrestricted comparison pending |
| T1.4 | Bounded filter/exit research and holdout comparison | Pending |
| T2 | Broker-neutral automatic live scanner; 50 volume shockers, price/volume %, index filters and row sparklines | Existing Fyers snapshot and standalone top-50 report verified; shared strategy-selection contract brought forward for T1.2a; integrated live UI/broker-neutral extensions pending |
| T3 | AlgoMirror shared calculator, Delta adapter, simultaneous accounts | Pending |
| T4 | Theme foundation and full route-by-route UI migration | Pending |
| T5 | Flutter parity matrix, implementation and Android artifact | Pending |
| T6 | Sandbox style portfolios, ledger, valuations and watch thresholds | Pending |

Resume by reading root `AGENTS.md`, this file, then `context.md` for prior implementation history and `docs/INDEX.md` for canonical references. Check current Git status in every target repo and applicable nested instructions before editing. Do not redo the planning pass or treat older task numbers as these tasks.

Next concrete work: use `.development/market-scanner-report/` for the partial-day scanner replay and the isolated original research copy for baseline comparison. Read the latest milestone and final report location below; do not restart the completed 2,642-instrument download. Reproduce the original historical execution baseline, add the unrestricted comparison on identical inputs, and address data/latency/ambiguity gaps before longer runs. A full-day extension requires a new cutoff and versioned inputs; the saved run ends at 12:26 IST. Continue API capability inventory independently. The original-tree boundary remains unresolved; preserve both original application trees. Full-history reports, broker capability verification, mobile builds and screenshot interaction tests remain pending.

At each milestone update this file with date, completed checklist rows, changed files, commands/results, data/run IDs, remaining decisions and next command. Keep credentials and account payloads out. Do not mark implementation complete merely because a plan or test scaffold exists.

## Restart milestone — 2026-09-11

The user requested resumption. Inspection found an existing untracked `backtesting/all_stock_ha/` implementation and outputs which were not recorded in the planning checklist. Treat these as inherited work, not as evidence that the six tasks were complete. Its original `smoke_v1` selects ATHERENERG/RELIANCE with research enabled, but has only partial ATHERENERG 1m outputs, zero `done.json` markers and a research DB status of `running`. This session did not overwrite those files or change that DB status.

### Safe development location

- New isolated **research copy**, not a Git checkout: `.development/six-task-research/`. It contains the research Python files and a frozen copy of `backtesting/stratagies/ha_bb_vwap_strategy_astra.py`; it does not contain application databases or credentials. Use the original backtesting virtual environment to run it.
- The original code-freeze question was sent again during resumption; no answer was received at this milestone. The separate-copy fallback in this plan was used. No permission to edit original Indian/Crypto application code is inferred.
- Original `data.py`, `engine.py`, `report.py`, and `run.py` still match all four hashes in the inherited smoke manifest. The original strategy copy matches its recorded hash. Original application code and both source databases were only read.
- Sibling AlgoMirror, Crypto and mobile Git status were clean at inspection, using command-local `git -c safe.directory=<exact path> -C <path> status --short`; no persistent Git configuration changed. Existing `task.txt`, scanner-plan additions and untracked original research files were preserved.

### Data evidence

Artifacts: [audit summary](artifacts/2026-09-11-resume-audit/summary.json), [CSV inventory](artifacts/2026-09-11-resume-audit/csv_inventory.csv), [Historify catalog](artifacts/2026-09-11-resume-audit/historify_catalog.csv).

- Inventoried 93 CSV files across stock lists, backtesting, data, `D:/Personal/CSVs` and the ATHERENERG Historify export. This includes seven generated research outputs. All 86 previously catalogued files still exist and match their stored SHA-256 hashes.
- Existing research catalog: 85 imported files and one quarantined reference file. `D:/Personal/CSVs/broker_charges_comparison.csv` has extra fields at data row 119. Keep it quarantined; no source repair or tariff assumption was made.
- Historify opened successfully in read-only mode without touching its lock file. `data_catalog` reports 1,573 NSE 1m instruments and 859,377,449 rows. Date spans are at least five years for 999 instruments and at least ten years for zero. These are **metadata date spans**, not proof of complete or valid history. Ten-year reports cannot be represented as complete from this source.
- Only the two smoke stocks received row/session validation in this milestone: ATHERENERG 126,419 source rows, 336 retained full sessions, 2 excluded sessions; RELIANCE 851,008 source rows, 2,207 retained full sessions, 72 excluded sessions. Exclusions remain in each report's `sessions.csv`. This validation assumes normal 09:15–15:30 sessions; exchange-calendar verification is outstanding.

### Isolated corrections and verification

Changed only isolated `engine.py`, `run.py`, and `test_engine.py`: fresh-cross signal mode is now the default; continuation mode is a separate `rolling_continuation` experiment excluded from filter/exit selection; the manifest accurately names the selected signal policy. Added a fixture where two consecutive outside-band candles produce one fresh signal versus two continuation signals.

Commands, from `D:/Personal/openalgo`:

```powershell
& backtesting/.venv/Scripts/python.exe -m pytest .development/six-task-research/backtesting/all_stock_ha/test_engine.py -q --confcutdir=.development/six-task-research/backtesting/all_stock_ha -o addopts= -p no:cacheprovider
& backtesting/.venv/Scripts/python.exe .development/six-task-research/backtesting/stratagies/ha_bb_vwap_strategy_astra.py selftest
& backtesting/.venv/Scripts/python.exe .development/six-task-research/backtesting/all_stock_ha/run.py run --historify D:/Personal/openalgo/db/historify.duckdb --symbols ATHERENERG RELIANCE --rollover fresh --out .development/six-task-research/backtesting/all_stock_ha/smoke_fresh_v1
```

Results: **11 pytest tests passed**; original strategy selftest passed (NumPy timedelta deprecation warning). Initial sandbox pytest access to its existing temporary directory was denied; the approved escalated rerun passed. Smoke run completed all four stock/timeframe results, with 42/12 ATHERENERG and 66/21 RELIANCE trades for 1m/5m respectively. No research sweep or live operation ran.

Run ID: `1669d7de00814c6b777ad18eb0bc4380a62517a3dd738ba963c93245d1fcd3b8`.

Report: `.development/six-task-research/backtesting/all_stock_ha/smoke_fresh_v1/index.html`. [Reconciliation evidence](artifacts/2026-09-11-resume-audit/smoke_verification.json) confirms trade counts, ledger P&L/costs, daily totals, six calendar-period groupings, per-trade notional <= INR 100,000 and both aggregate portfolio totals. Four completion markers exist. This is an enhanced-execution pipeline smoke test, **not** reproduction of the original confirmation/next-open historical strategy or a completed all-stock baseline.

Resource audit scoped to this copy: DuckDB connections use context managers; CSV/file reads and NumPy archives use context managers/finally cleanup. The command completed and exited, releasing resources. No service, socket, thread or cache lifecycle was introduced by the correction. Full-universe memory/scaling behavior remains unverified; aggregation retains per-stock trade frames and a calendar-minute timeline and should be bounded before scaling.

### Remaining gates before larger runs

1. Reproduce the original historical execution baseline; preserve configurable original breakout source and exit modes in the enhanced model. Existing parity tests cover indicators/default long signals, not original historical P&L.
2. Validate per-symbol ticks, calendar exceptions, adjustment/source policies, missing whole sessions and cross-file conflicts. Current strict session exclusion changes retained HA history and the set of prior volume sessions; determine/report the correct continuity policy.
3. Replace the metadata-only run fingerprint with immutable candle-content versions for trustworthy resume after source changes. Existing catalog hashes and file size cannot detect every price correction.
4. Review all entry/exit ambiguity cases: entry-bar stop/target ordering requires more than the current target-first sensitivity, and rejected entries need recorded reasons. Final execution choices remain those listed in T1.2.
5. Current costs are illustrative 5 bps per side plus 5 bps slippage; itemized broker charges, real tick metadata, authentic benchmark coverage and a constrained-capital replay are absent. Do not present the smoke results as investment recommendations or verified net broker returns.
6. Improve report missing/research-not-run states and bounded aggregation; complete baseline reporting before enabling research. Existing research selection needs short-history/empty-fold validation before any sweep.

Resume with the isolated source and these artifacts; do not rerun or overwrite the inherited `smoke_v1` as if it were an approved baseline. Use a new output directory whenever inputs or code change.

### Today's scanner request — 2026-09-11, 10:48 IST

The user requested today's volume shockers and top gainers/losers. Ran the existing scanner with `uv run --no-sync python scripts/market_scanner.py --limit 50 --output tmp/market-scanner-2026-09-11.json`. The first quote batch returned HTTP 401 and the scanner stopped with `Fyers authentication failed. Log in again.` No current quotes were obtained (0/2,643); empty result lists mean authentication failure, not absence of market movers. User must renew the Fyers login in OpenAlgo before rerunning that command. The prior `tmp/market-scanner-today.json` snapshot is dated September 10 and must not be shown as September 11 data. No application code changed for this request.

**Retry succeeded after the user requested “RETRY NOW”.** The same command ran from 11:18:56 to 11:36:24 IST on September 11. Scan ID `ab28f03978f848aa8caec970879b3b76`: 2,642 instruments scanned, 2,625 valid current-day quotes, 2,622 usable five-session baselines; 233 volume shockers (>1x RVOL), 736 gainers and 1,855 losers. Top 50 per list saved in `tmp/market-scanner-2026-09-11.json`. Partial coverage: 17 stale/invalid quotes, two insufficient histories and one unavailable history. No rate-limit retries; normal history pacing accounted for the approximately 17.5-minute first scan. Quotes refreshed after baseline loading. These are intraday snapshots, not closing results.

Added standalone presentation/verification utilities in `.development/market-scanner-report/`, preserving original application code. `verify.py` independently checked all 150 ranked rows against current-day timestamps, sort order, previous-close percentage change and the read-only cached historical volume baselines. Evidence: `tmp/market-scanner-2026-09-11-verified.json`. `render.py` generated the searchable three-tab report at `tmp/market-scanner-2026-09-11/index.html` with separate price/volume percentages, RVOL, timestamps, coverage notes and three CSV downloads. This standalone snapshot report does not implement T2's integrated live UI, categories or sparklines. The utilities perform no broker calls; all file/SQLite handles close explicitly or via context managers. Python compilation and report structure/link checks passed.

Re-render without a new broker scan:

```powershell
& .venv/Scripts/python.exe .development/market-scanner-report/verify.py tmp/market-scanner-2026-09-11.json
& .venv/Scripts/python.exe .development/market-scanner-report/render.py tmp/market-scanner-2026-09-11.json tmp/market-scanner-2026-09-11/index.html
```

## Latest milestone — today's scanner-selected backtest and every trade plot

The user requested today's scanner, a backtest on its candidates, and each trade plotted, then requested resumption. The initial download completed while work was interrupted. Resumption reused the saved inputs and did not restart the completed download. No answer was received to the optional period question; the stated default, today's session so far, was retained with its original frozen cutoff.

**Run directory:** `.development/market-scanner-report/runs/2026-09-11-1226/`.

**Final backtest:** [backtest-v4/index.html](../../.development/market-scanner-report/runs/2026-09-11-1226/backtest-v4/index.html).
**Current-list snapshot:** [scanner/index.html](../../.development/market-scanner-report/runs/2026-09-11-1226/scanner/index.html).
Use `backtest-v4`; earlier `backtest`, `backtest-v2` and `backtest-v3` folders are superseded intermediate artifacts. Do not use the first version's chart count: a duplicate filename defect was corrected before final delivery. The final version has 48 unique trade IDs and 48 distinct chart pages, all verified.

### Inputs and selection

- Scanner `871316bcfe544ddbbb68bbf80072fe60` completed September 11 at 12:26:48 IST: 2,642 configured instruments, 2,628 valid quotes, 2,626 volume baselines, 319 volume shockers, 778 gainers, 1,812 losers; top 50 each, 127 unique current candidates. Fourteen stale/invalid quotes and two insufficient histories make coverage partial.
- Fetched one-minute history for all 2,642 instruments with no request errors. The frozen execution window is **09:15–12:26 IST**, containing 191 completed minutes; no afternoon data enters this run. The first 127 current candidates received 50 calendar days of warmup; an additional 25 historical candidates were fetched after reconstruction. Inputs live under `inputs/today` and `inputs/warmup`; hashes are in `input_hashes.json` and the final report manifest.
- Reconstructed the three top-50 lists at each completed minute using the same full configured universe, with price change against Fyers previous close and scanner RVOL against five prior daily volumes. No final midday list is applied backward to choose morning entries. Existing candidates retain indicator warmup even when outside a list.
- **Partial historical coverage:** 2,078 instruments have usable continuous minute history through the cutoff. Missing bars are not fabricated; input problems/continuous-prefix exclusions are in `reconstructed_coverage.csv`. The reconstructed rankings are within this available coverage, not an assertion of exact full-exchange rankings. The broker's EQ universe can include ETFs, which remain explicitly disclosed.
- 376 instruments entered at least one reconstructed list. Of these, 73 could also satisfy the preserved strategy volume gate (20 prior full daily sessions, RVOL >= 2); 72 were evaluated at 1m and 5m, while INFRA was excluded for insufficient warmup history. Others have explicit no-trade/coverage statuses. Trades occurred in 31 instruments. This avoids selecting history solely from the final 127-stock snapshot. `scanner_snapshots.csv`, `scanner_memberships.csv` and `rankings.npz` retain selection attribution.
- A BSOFT candle revision was found when comparing the later warmup response with the original today download. `read_candles()` now always preserves the original today bars for both ranking and execution; later warmup contributes prior days only. All 25 overlapping downloads were checked against this rule. Original raw files remain available and hashed.

### Results at the saved cutoff

Each timeframe is an independent simulation with INR 100,000 notional per entry and concurrent stocks. Costs/slippage remain illustrative, as below. Open trades are marked at the last completed candle, with entry costs deducted; they are not forced into synthetic exits.

| Timeframe | Trades | Closed / open | Closed net P&L | Open marked P&L after entry cost | Combined net / marked P&L |
|---|---:|---|---:|---:|---:|
| 1m | 43 | 29 / 14 | -14,667.52 | -3,591.46 | -18,258.98 |
| 5m | 5 | 1 / 4 | -1,563.05 | +1,628.82 | +65.77 |

The report contains every trade's real 1m candlestick chart, a separate signal-timeframe HA/BB/VWAP panel, signal marker, entry, exit or open mark, SL/TP levels, quantity, source-list ranks and costs. It includes searchable trade links, per-stock no-trade reasons, rejected signals, CSV ledgers, portfolio timelines and a price-only NIFTY reference (+0.2879% over this window). Return denominators and capital requirements are stated; Sharpe is N/A for a single partial day. Reference capital is INR 100,000 per ever-selected instrument (INR 37.6 million), not an assertion that a single lakh funded every concurrent position.

### Verification and limitations

- Eight focused tests passed in `test_intraday.py`: full-universe top-50/overlap behavior, previous-close math, missing-minute exclusion, signal/entry gating, continued position management after removal, open marks, ambiguity/ledger reconciliation, future-price independence of earlier entries, signal-driven direction and 5m entry rechecking.
- `verify_backtest.py` passed all 48 trade rows: causal times, signal/entry rank attribution, 20-session volume threshold, lot/quantity/notional constraints, closed/open cutoff behavior, fees/P&L reconciliation, local chart links, all source hashes and original-today precedence for the 25 overlaps. Evidence: final `verification.json`.
- Playwright with installed Chrome rendered all 48 chart pages, verified trade markers/search and recorded no page errors. Evidence: `browser-verification.json`, `overview.png`, `example-trade.png`. The initial missing bundled Playwright browser was resolved using installed Chrome; no browser download was needed. Visual inspection led to clearer spacing/time labels between chart panels.
- Resource audit: SQLite connections close in `finally`, gzip/files and NumPy archives use context managers, provider calls use the existing limiter, and the headless browser closes in `finally`. No app-level worker/cache/socket lifecycle was introduced. Original application trees were unchanged. No live orders were placed.
- Still provisional: zero modeled processing delay at historical minute close, incomplete universe/history coverage, current master metadata, 50-day HA initialization rather than full-history identity, unverified corporate-action adjustments, and 5 bps fees per side plus 5 bps slippage. Three 1m trades have ambiguous OHLC ordering and use stop-first treatment. A richer ordering sensitivity analysis and itemized broker charges remain pending. Existing daily-session volume cache is used explicitly; complete source/calendar validation is outstanding.
- This run demonstrates isolated selection/execution/report plumbing on a partial day. It does not complete all T1.2a acceptance tests, establish full-history performance, implement T2's continuous live service, or authorize strategy deployment.

### Reproduction and next command

From repository root; all commands use existing inputs unless a new fetch is explicitly chosen:

```powershell
& backtesting/.venv/Scripts/python.exe -m pytest .development/market-scanner-report/test_intraday.py -q --confcutdir=.development/market-scanner-report -o addopts= -p no:cacheprovider
& backtesting/.venv/Scripts/python.exe .development/market-scanner-report/verify_backtest.py .development/market-scanner-report/runs/2026-09-11-1226/backtest-v4
node .development/market-scanner-report/verify_browser.cjs .development/market-scanner-report/runs/2026-09-11-1226/backtest-v4
```

The pipeline is `fetch_backtest.py` -> `reconstruct.py` -> additional warmup fetch listed in `warmup_needed.json` -> `backtest_today.py` -> verification. `backtest_today.py` refuses a completed output directory; use a new `--report-name` after any code/input change. Its code is confined to `.development/market-scanner-report/`, with the preserved indicator implementation imported from the isolated `six-task-research` copy. Next work is an unrestricted comparison on the same frozen data and outstanding execution/data tests, or a separately versioned full-day extension if requested. Never silently relabel this 12:26 report as closing-day results.
