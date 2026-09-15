# All-stock HA / Bollinger / VWAP backtest and interactive reports

Configured range: **3 July 2017 through 10 September 2026, inclusive**. Source: `D:\Personal\openalgo\db\historify.duckdb`, OpenAlgo Historify `market_data` with NSE 1-minute epoch-second candles. The 5-minute series is aggregated from the same 1-minute source. All 404 existing version files are selected by default, with separate OLHC and OHLC approximations. Each buy and sell strategy runs on every available NSE source symbol; the September 11 gainers/losers lists are not used.

The initial implementation was prepared and tested with synthetic data only. The later request authorizes the historical run; check `output/results.sqlite` or the live dashboard for actual completed sessions. Synthetic demo figures are clearly labeled and must never be quoted as historical performance.

## Commands — PowerShell, from the repository root

```powershell
Set-Location D:\Personal\openalgo

# Inspect the configured task; this does not open the market-data database.
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks plan

# Run ALL available source stocks and ALL 404 versions, both modeled paths.
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks run

# Resume an interrupted identical run. Earlier committed days are retained.
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks run --resume

# In a SECOND terminal, open the read-only report dashboard.
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks serve
```

Visit **http://127.0.0.1:8777**. There is no dashboard button/API that starts a backtest. Before results exist, it says the backtest has not run. During a run it shows committed days as a partial run. Refresh the page to see newly committed sessions. Do not launch a second writer against the same output.

To generate the final comparison automatically after every planned session is committed, run this in another terminal (it only reads results):

```powershell
& backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks.comparison --watch
```

Without `--watch`, this command generates the report immediately if complete, or exits with the current progress and refuses to name a full-history winner. Output: `output/comparison/index.html`, `findings.md`, `ranking.csv`, `path_metrics.csv`, `year_metrics.csv` and `comparison.json`. It compares all versions overall and within buy/sell x 1m/5m groups. Highest-profit ranking uses the lower net P&L across OLHC/OHLC. Profit-to-drawdown ranking uses that lower P&L divided by the larger path drawdown. Only strategies profitable on both paths are eligible; ties remain ties. Annual consistency, costs, capital, worst year and latest year are reported alongside the leaders. This is retrospective selection over the whole sample, not independent out-of-sample validation.

The 2026-09-13 production startup processed its first 25 stock-sessions in roughly eight minutes. A separate bounded profile is saved in `artifacts/throughput-profile.{json,txt}`; repeated Python engine snapshot validation dominates the measured replay. The profile includes instrumentation and constructs accumulators more often than the production loop, so its absolute duration is not a full-run ETA. The source catalog contains 859,377,449 minute rows. This baseline needs substantial runtime/throughput work for a practical full-history completion; launching it does not establish that the experiment has completed.

For a bounded first execution later, `run --max-days 1` commits at most one source session; subsequent `run --resume --max-days 1` advances one more. `--max-days` counts newly completed days, not calendar days. Ctrl+C rolls back the current day; previous days remain committed. Stopping in the middle of a large day means replaying that day on resume.

**This full experiment is computationally large.** The default runs 404 independent variants × two paths × all available stock sessions. Indicator observations are shared within stock/timeframe/path; the source is read a stock-session at a time, and portfolio accumulation is bounded to one day. This is a correctness baseline, not a promise of fast full-universe throughput. Full-history runtime/storage have not been benchmarked. Use an initial bounded day to measure actual cost before letting the entire experiment continue. Retained fills and full-session chart candles can require substantial disk space; compressed daily portfolio series avoid a dense all-stock/all-year matrix in RAM.

## Source access and repeatability

- Reads the source using `duckdb.connect(..., read_only=True)` and the repository's known Historify schema. It does not import the app database service, migrate tables, fetch data, load API keys, or place orders. The production source was not needed for synthetic validation.
- DuckDB must be available for read-only access. An active writer can block opening it. Use a clean, checkpointed immutable snapshot when the app also needs the database. A nonempty WAL is rejected; **never delete the WAL to bypass this check**. Connection/lock errors stop the command rather than altering the source or killing another application.
- A full file SHA-256 is computed while the read-only connection is held; day input digests include warmup and target candles. Source, strategy/engine code, selected symbols, parameters, metadata snapshot and fee schedules are recorded in `manifest.json` and the results store. Resume rejects changed identities. Use a different output directory for a changed experiment.
- Output is a separate indexed SQLite database in WAL mode. Entire trading days commit atomically. The dashboard uses read-only connections and sees only committed results. It serves only on localhost.
- The global source-symbol catalog is the universe, not today's watchlist. This avoids explicitly discarding old symbols just because they are missing from today's master, but it does not prove delisted-stock or historical exchange-universe completeness. Source gaps and adjustments still matter.

## Configuration and historical assumptions

Edit/copy `config.json` and pass `--config path/to/custom.json`. Relative paths resolve from `D:\Personal\openalgo`; absolute paths are accepted. Empty `symbols` and `strategy_ids` lists mean all. A nonempty list limits the experiment deliberately. `--output` overrides the output location. `allow_missing_minutes: true` preserves observed gaps; set false to skip incomplete regular sessions. Invalid OHLC, duplicates and invalid warmup/metadata skip the stock-session and are recorded in coverage. Missing whole-market sessions cannot be inferred from this source alone; an exchange calendar is not reconstructed. Special shorter/extended sessions are outside the 09:15–15:30 engine contract.

The adapter uses the unchanged existing strategy factories. Source HA/BB/VWAP, indicator exits, immediate-next-bar entry, partial exits, trailing logic and whole-share sizing remain in that engine. Up to 600 earlier bars initialize each timeframe daily; this finite warmup is not full-history HA identity. No prior history means delayed indicator readiness, not fabricated bars. Forming prices traverse O-L-H-C or O-H-L-C in three steps per leg, with uniform volume accumulation. These are two sensitivity scenarios, not actual ticks or exhaustive bounds. Entry/exit fills use observed modeled real prices, adverse slippage and tick rounding, never synthetic HA fills.

Default allocation is the engine's Rs 100,000 per stock/trade. Different stocks can overlap; the fixed return denominator is source-universe size × Rs 100,000. This is a reference allocation, not required broker margin. Position quantity may reduce to fit the cap after adverse fill rounding. Zero-volume observations cannot open trades, but exits can use the last modeled reference; queue, participation, circuit limits and exit liquidity are not modeled. Scheduled exits remain 15:05 for identified F&O underlyings and 15:20 for others, including a stale last-known-price clock exit if afternoon candles are missing.

**Historical fees and instrument metadata are assumptions until supplied.** By default, the previous September 11 research rates are applied across the whole date range, with 5 bps adverse slippage per fill. These are not claimed to be historically correct 2017–2026 contract-note costs. The current local `symtoken` snapshot supplies tick sizes/F&O status where available; unknown symbols use the explicit configured tick/FO fallback and are flagged. This avoids silently filtering unknown old symbols, but can change risk and square-off relative to historical reality.

For historically correct overrides, provide:

```text
metadata_csv columns:
symbol,effective_from,effective_to,tick_size,is_fo

fees_csv columns:
effective_from,effective_to,brokerage_rate,brokerage_cap,exchange_rate,sebi_rate,sell_stt_rate,buy_stamp_rate,gst_rate
```

Dates are ISO, inclusive. Each requested symbol/day must match exactly one metadata row; each trading day must match exactly one fee row. Missing/overlapping fee dates fail the run; missing/ambiguous instrument dates skip the stock-session with an explanation. A metadata CSV replaces the local snapshot rather than silently mixing it with current metadata. Research rates are brokerage min(Rs 20, 0.03%), exchange 0.00307%, SEBI 0.0001%, sell STT 0.025%, buy stamp 0.003%, GST 18% on brokerage/exchange/SEBI. Tax rounding and broker-specific square-off surcharges are omitted. Reference: [Zerodha charges](https://zerodha.com/charges).

## Dashboard reports

Filters select strategy, modeled path, date range and grouping. Strategies/paths remain independent; profits across all variants must not be added as if funded by the same capital.

- Day, Monday–Sunday week, calendar month, quarter, Jan–Jun/Jul–Dec half-year, year, five-year windows, and whole selected history.
- Five-year anchor defaults to 2017: calendar 2017–2021 and 2022–2026, clipped to the requested range. Partial periods and incomplete run coverage are labeled.
- Net/gross P&L, brokerage, total charges, modeled slippage, entry notional/turnover, reference capital, peak simultaneous capital and timestamp, time-weighted average capital, largest net win/loss, average P&L/win/loss, win rate, profit factor, trade/order counts, rejected entries, drawdown and peak/trough times, and maximum/average simultaneous trades.
- Period drawdown correctly carries the portfolio high-water mark across days; it is **not** `max(daily drawdown)`. The reducer combines each day's internal bar-close drawdown with the prior cumulative peak and the day's equity trough. This preserves within-day and cross-day ordering without loading years of minute data into the browser.
- Capital/concurrency peaks are derived from exact modeled fill times; the chart uses minute snapshots. The date/time lookup uses indexed entries/exits and partial fills to return exact modeled open stocks, quantities, remaining entry notional, entries/closures so far and realized P&L less paid fees. Positions ending at the selected time are closed; entries at that time are open. At identical timestamps, exits precede new entries.
- Paginated trade ledger with stock filter, full-session red/green HA candle charts, raw-candle toggle, Bollinger/VWAP, entry/exit/partial markers, initial stop/target/trailing path, and brokerage/tax breakdown for every fill. Missing candles remain gaps; no artificial 15:30 starting candle is created. Camera exports PNG.
- CSV downloads of period metrics, all selected trades and all selected fills/costs stream in batches. No full-year ledger is loaded into browser memory.
- NIFTY session open-to-close price-only comparison is used only when complete 1m index sessions exist in the same DuckDB for every selected session. No index data is fetched automatically. Benchmark coverage failures display “unavailable.” This intraday reference is not a traded buy-and-hold portfolio.

MTM uses completed-bar observations. Equity chart points across long periods are daily closing values; maximum drawdown also includes the retained intraday bar-close extrema. Finer true intrabar losses are unknown. Fees are included in net trade metrics. Positive-profit/no-loss profit factor displays infinity; no-trade metrics display N/A. Average capital/open trades use 22,500 regular-session seconds per recorded source day. No claimed broker cash/margin/financing model or dividend/corporate-action reconstruction is added.

## Synthetic preview and validation

```powershell
# Create clearly labeled, invented dashboard data only; refuses to overwrite an existing demo.
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks demo
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks serve --output backtesting/ha_bb_vwap_allstocks/demo_output

# Synthetic unit/integration tests (do not use the production DuckDB).
& backtesting/.venv/Scripts/python.exe -m pytest backtesting/ha_bb_vwap_allstocks/test_pipeline.py -q --confcutdir=backtesting/ha_bb_vwap_allstocks -o addopts= -p no:cacheprovider
node backtesting/ha_bb_vwap_allstocks/verify_browser.cjs
```

The tests exercise an invented DuckDB through the actual strategy engine and VectorBT accounting, byte-for-byte source preservation, chunk/resume behavior, changed-run rejection, atomic rollback, warmup/date boundaries, effective fee coverage, no-result state, partial-exit time lookups and all eight calendar groupings. Browser verification covers the demo and honest empty state, period controls, open trades, CSV export and candle colors/session span. Screenshots are under `artifacts/` and explicitly depict synthetic data. Full historical execution/performance and long-run scaling are separate operational checks.

Implementation: `source.py` (DuckDB), `execution.py` (generic dated fill adapter), `statistics.py` (daily/cross-day capital and risk), `storage.py` (transactional results), `runner.py` (day orchestration), `dashboard.py` + `web/` (read-only UI). Existing September 11 indicator/event generation is imported rather than changing that report. Official API references: [DuckDB Python connection/read-only API](https://duckdb.org/docs/stable/clients/python/reference/) and [SQLite window semantics](https://www.sqlite.org/windowfunctions.html).
