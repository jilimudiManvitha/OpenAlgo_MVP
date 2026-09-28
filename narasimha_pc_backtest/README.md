# Nifty 50 one-minute HA buy breakout — completed research run

Delivered September 25, 2026. Code, converted candles, audit files, ledgers and
interactive output are contained in this folder. Source: `../db/historify.duckdb`,
opened read-only. The original application, prior strategy engines and Crypto
trees were not edited. No data download, broker call or live trade occurred.

## Open the interactive report

The report is served at **http://127.0.0.1:8782** while its local server is running.
To start it again, run this from the project directory and leave the terminal open:

```powershell
& .\narasimha_pc_backtest\show_report.ps1
```

Alternatively:

```powershell
& .\.venv\Scripts\python.exe .\narasimha_pc_backtest\serve.py
```

Open the URL in your browser. Filter by stock, dates and modeled price path;
inspect cumulative P&L, daily-close drawdown, monthly/yearly P&L and stock
contributions. The ledger's **Chart** button opens the full trading session,
with HA/market candle toggle, Bollinger/VWAP, signal shading, buy/exit markers
and fixed stop/target lines. Drag to zoom and use the camera button to export.
The server serves only this generated output on localhost; stop with Ctrl+C.

`output/index.html` also opens directly for summary charts/ledger filtering;
individual session candles require the local server. Plotly is bundled locally:
no CDN or API keys are needed. The report data file is about 79 MB and can take
a few seconds to load. Session candle queries load one symbol/day at a time.

## Results

Requested range: **2021-09-25 through 2026-09-25 inclusive**.
Replay completed for the available eligible sessions, **2021-09-27 through
2026-09-24**. September 25 is only downloaded through approximately 12:27–12:40
IST, before square-off; all 50 stock-sessions on that date are excluded.

| Metric | Open-low-high-close (OLHC) | Open-high-low-close (OHLC) |
|---|---:|---:|
| Trades | 56,701 | 57,239 |
| Gross P&L, after modeled slippage | −₹51,24,372.21 | −₹56,20,915.39 |
| Assumed fees | ₹56,13,940.40 | ₹56,66,965.82 |
| **Net P&L** | **−₹1,07,38,312.61** | **−₹1,12,87,881.21** |
| Net win rate | 24.63% | 23.87% |
| Net profit factor | 0.523 | 0.507 |
| Maximum daily-close drawdown | ₹1,07,38,312.61 | ₹1,12,87,881.21 |
| Peak simultaneous entry notional | ₹43,59,274.45 | ₹43,59,282.35 |
| Peak simultaneous positions | 44 | 44 |

Both scenarios lost money under the configured costs. Every calendar-year
slice was negative; 2021 and 2026 are partial years. Do not add the scenarios
together. These are historical simulations of the specified rule, not live
results or a funded portfolio: fixed ₹1 lakh allocations continue after losses.

**Costs are research assumptions:** 5 bps adverse slippage on market orders,
adverse current-tick rounding, and flat 5 bps fees per fill. Target exits are
resting limits. Actual historical brokerage/taxes were not supplied. Gross
already includes slippage; net additionally deducts fees. The ledger includes
unslipped reference-price P&L for attribution, which is not a separate zero-cost
strategy backtest (entry fills also determine sizing and target distance).

## Data conversion and coverage

- All 50 exact symbols in `../nifty50_symbols_For_HistoricData.txt` are present;
  no company/alias substitutions. This is a fixed present-day basket, not
  reconstructed historical Nifty membership.
- Source rows examined: **22,977,386**. Valid regular-session minute candles
  converted to HA: **22,964,861**; raw and HA OHLCV plus BB/VWAP are stored in
  50 compressed Parquet files under `output/candles/`.
- **12,333** out-of-regular-session rows are outside this strategy's clock.
  **192** invalid regular-session candles are saved verbatim in `output/rejected/`.
  Their **188 stock-days** are excluded. Values were not repaired.
- **60,830** eligible stock-sessions; **363** incomplete-to-square-off sessions
  excluded, including September 25; **469** absent stock-sessions against the
  union of source dates. An authoritative exchange holiday/special-session
  calendar was not reconstructed.
- JIOFIN starts **2023-08-21 at 09:55 IST**, not in 2021. Its partial first day
  is excluded. Source symbol renaming and corporate-action adjustment policies
  are not independently validated.
- Current local master identifies all 50 as F&O, giving 15:05 square-off for
  this run. Historical F&O membership and tick sizes are assumptions. The code
  and tests support 15:20 for non-F&O classification.

Full definitions and the requested six-part documentation for both named
execution scenarios: **[STRATEGY.md](STRATEGY.md)**.

## Code and reproducibility

`engine.py` uses Numba-compiled CPU loops. `run.py` reads four symbols at a time
with independent read-only DuckDB connections, exports per-symbol data, and
builds the report. This complete run took **23.62 seconds** on this PC, including
conversion/export/report generation, excluding subsequent verification. GPU
was unnecessary. Source SHA-256 was checked before/after; `manifest.json`
records source identity, actual data audit, settings, current instrument metadata
and execution-code hashes. Entire generated output is about **1.40 GB**.

To rerun, use a **new empty output folder**; existing output is never overwritten:

```powershell
& .\narasimha_pc_backtest\run_backtest.ps1 --output .\narasimha_pc_backtest\output_new
# Explicit cost sensitivity, also in a separate folder:
& .\narasimha_pc_backtest\run_backtest.ps1 --fee-bps 0 --slippage-bps 0 --output .\narasimha_pc_backtest\output_zero_cost
# View another run:
& .\narasimha_pc_backtest\show_report.ps1 --output .\narasimha_pc_backtest\output_new --port 8783
```

Other CLI options: `--source`, `--start`, `--end`, `--symbols SBIN RELIANCE`,
`--workers`, `--steps`. Date endpoints are inclusive. Resume is intentionally
not implemented for this sub-minute run. Interrupted runs remain marked
`FAILED_OR_INTERRUPTED`; restart with a new output folder. No process is killed,
no source lock/WAL is removed, and source lock errors stop execution.

The named `buy_ha1m_bb20x2_vwap_sl010_tp3r_*.py` files expose each scenario
separately while sharing the same implementation. Use `run.py`/PowerShell for
the complete data-to-report workflow. `requirements.txt` lists dependencies;
the existing project `.venv` supplied them without installation.

## Verification and limitations

- Behavioral tests cover independent HA/Bollinger math, VWAP resets, HA carry,
  immediate-next-minute entry, no future wick rejection, one trade per day,
  stop/target ordering, gap stops, both cutoffs, costs, invalid input rejection,
  and actual DuckDB quarantine/Parquet export with byte-identical source.
- `output/verification.json`: **113,940 saved trades** independently checked
  for entry conditions, market path/time, capital cap, tick/SL/3R rules,
  accounting, eligible sessions, clock exits and unchanged source hash.
- `output/sampling-sensitivity.json`: 128 versus 32 entry samples/leg select
  the same trades/signals across all 100 symbol/path pairs. Tiny near-tick
  entry-fill differences affect three pairs: refined OLHC net changes by
  +₹2.90145, OHLC by +₹6.20310. This does not establish actual tick ordering.
- `artifacts/browser-verification.json`: actual Chrome tests of filters,
  summary charts, trade candle views, pagination, invalid-symbol handling and
  mobile layout; zero page errors. Desktop/mobile/trade screenshots saved.
- `artifacts/resource-and-mutation.json`: disabling the daily-trade guard
  makes the fixture produce two trades instead of one. Across 121 DuckDB
  success/exception cycles, post-warmup handle count stayed **600 → 600**;
  RSS plateaued around 189 MB. Executor/database/file lifecycles are scoped.
- Independent saved-ledger verification does not independently replay the
  earliest exit on every historical path; deterministic tests check that logic.
  Drawdown is daily-close, not full intraday MTM. No historical fee calendar,
  exchange calendar, corporate-action reconstruction or constrained cash model.

Run checks from the project root:

```powershell
& .\.venv\Scripts\python.exe -m pytest narasimha_pc_backtest/test_engine.py --confcutdir=narasimha_pc_backtest -o addopts= -p no:cacheprovider -q
& .\.venv\Scripts\python.exe narasimha_pc_backtest/verify_results.py
& .\.venv\Scripts\python.exe narasimha_pc_backtest/check_sensitivity.py
node narasimha_pc_backtest/verify_browser.cjs  # local report server must be running
```

`smoke_output/` is the earlier two-stock September check. `rejected_initial_run/`
records the initial full-run validation failure on malformed OHLC; it is not
the completed result. **Use `output/` for final results.**
