# Portable crypto backtester: S029 / S104 / S232 / S344

Copy this folder (or extract `crypto_four_portable.zip`) and your historical data
to the new Windows PC. The main program is **crypto_backtest.py**: it is standalone
and does not need OpenAlgo, API keys, the application, or the old computer.
Dependencies require internet access during installation. Backtesting is offline.

The repository also includes saved four-coin reports and CSV exports under
`results_full/`; open `results_full/index.html` to view the saved comparison.
Large one-minute candle CSVs are stored with Git LFS. After cloning, install
Git LFS and run `git lfs pull` from the repository root to download those files.
The ZIP is the standalone code package; it does not bundle `results_full/`.
Local virtual environments, temporary validation files and rebuildable DuckDB
tick caches are excluded from Git.
`results/` contains an earlier partial run and is preserved separately; use
`results_full/index.html` for the saved four-coin comparison.

## 1. Install once

Install **64-bit Python 3.13** with the Python launcher enabled. Open PowerShell
in the extracted code folder and run:

```powershell
.\INSTALL.cmd
```

This creates a local `.venv`, installs the pinned dependencies, and runs small
synthetic tests. It does not access your market files.

## 2. Copy data and run

Keep the following folder names; the year subfolders can contain CSVs, ZIPs,
or both. Archive detection uses file contents, so the XAUT ZIPs named `.csv`
are supported. You do **not** have to extract archives.

```text
D:\Personal\OpenAlgo_Crypto\historical_data\
  btcfut\2024\...      -> BTCUSD
  ethfut\2024\...      -> ETHUSD
  solusd\2024\...      -> SOLUSD
  xautusdfut\2026\...  -> XAUTUSD
```

Run all available years, all four coins and all four strategies:

```powershell
.\RUN.cmd "D:\Personal\OpenAlgo_Crypto\historical_data"
```

Equivalent direct command (change `--data` to your new location):

```powershell
.\.venv\Scripts\python.exe -u crypto_backtest.py --data "D:\Personal\OpenAlgo_Crypto\historical_data" --output results --workers 4
```

Open **results/index.html** after completion. Console progress and each coin's
`progress.json` show processed trades and a moving replay-time estimate.
Keep Windows awake. No broker connection or live orders are involved.

## 3. What is tested

| ID | Direction | Candle | Reward/risk |
|---|---|---|---|
| S029 | Buy | 1 minute | 23.5R |
| S104 | Buy | 5 minutes | 10.5R |
| S232 | Sell | 1 minute | 24R |
| S344 | Sell | 5 minutes | 29.5R |

All use the original HA / BB(20,2) / VWAP signal and next-candle breakout rules,
a **0.10 USD absolute stop buffer**, no trailing stop, no partial exits, and no
indicator exits. They run 24/7, carry positions over UTC midnight and between
files/years, reject stale next-bar signals across gaps, and liquidate only when
the supplied data ends. Each of the 16 strategy/coin tests is independent.

These IDs were selected from the old ETH April-May 2024 experiment. That experiment
reported **S029 -$6,788.67**, S104 +$12,030.83, **S232 -$2,833.53**, and
S344 +$3,523.78. The minus signs matter. Those are prior results, not predictions
or the output of this new package. S104's old result was concentrated in one trade.

## Candle conversion

Your sampled CSV has complete timestamps such as
`2024-04-08 14:15:04.980299`. A spreadsheet may display only `15:05.0`.
Actual time-only strings cannot identify a date/hour; the importer rejects them.
Naive timestamps are interpreted as UTC; explicit timezone offsets are normalized
to UTC. No timezone is inferred from the Windows locale or year-folder name.

Trades are sorted chronologically, preserving source file/row order for ties.
Within each UTC 1-minute or 5-minute interval:

- Raw open = first trade; high/low = highest/lowest price; close = last trade.
- Volume = sum of the supplied `size` values (source units).
- HA close = `(open + high + low + close) / 4`.
- HA open = `(previous HA open + previous HA close) / 2`.
- First HA open = `(first raw open + first raw close) / 2`.
- HA high/low = maximum/minimum of raw high/low, HA open and HA close.

Each timeframe is built **directly from source trades**; 5m HA is not an
aggregation of 1m HA. BB uses the latest 20 HA closes, population standard
deviation. VWAP uses raw candle typical price `(H+L+C)/3` weighted by source
size, anchored at UTC midnight, matching the earlier experiment.

Forming candles use only trades already observed. Completed candles are confirmed
by the next available trade. Orders fill at source trade prices plus adverse
slippage, never at HA prices. No OHLC price path is invented. Empty intervals
are not filled with synthetic trades. The final source candle is exported with
`complete=0` and cannot create a new completed-bar signal.

## Files produced for every coin

- `candles_1m.csv`, `candles_5m.csv`: raw OHLCV and HA OHLC, BB upper and VWAP.
- Four `Sxxx_trades.csv` files: entry/exit times, quantities, fees and P&L.
- Four `Sxxx_fills.csv` files: every execution and its reason/stop/target.
- Four `Sxxx_daily.csv` files: daily P&L and reference equity.
- `input_audit.json`: uncompressed SHA-256 hashes, imported and duplicate files.
- `complete.json`: coverage, settings, timing and per-strategy metrics.
- `ticks.duckdb`: reusable parsed-data cache; never modifies the source files.

The top-level report/CSV compares net profit, fees, trade count, win rate,
profit factor, largest win/loss, and **every-observation MTM drawdown**.
Independent signed-fill cashflows reconcile against closed-trade P&L and strategy
cash. These are independent fixed-notional experiments, not a shared portfolio.

## Data safeguards and resume

Exact duplicate file contents are imported once, including extracted CSV copies
and the duplicate ETH 2026 archives under the 2024 folder. Individual identical
trade rows are retained: no trade IDs exist to prove they are duplicates.
Non-identical files with overlapping time ranges are rejected for manual review.
Missing periods and ties are counted; source coverage is not certified complete.

Run the same command again after interruption. Successful file imports are cached;
completed coins are skipped if code, settings and source file metadata match.
An interrupted coin's **strategy replay restarts from its beginning**, preserving
indicator/position continuity; this is not a tick-level resume checkpoint.
An output lock prevents concurrent writers. Changed code/settings/input sets
require a new `--output` directory. Keep original input files unchanged during a run.

## Hardware and estimated duration

For the i9-14900F / 32 GB RAM computer, the default is four CPU workers (one coin
per worker) and a 2 GB DuckDB budget **per worker**, plus bounded NumPy batches
and interpreter memory. The RTX 4070 Ti Super is not used; no CUDA installation
is needed. Use `--workers 2` if other applications need memory or disk bandwidth.
Use a local SSD, preferably NVMe. Plan for roughly **60 GB of additional free
space** for parsed data, sorting spill and output, beyond the original archives;
actual space depends on row counts and compression.

Local header/archive inspection found approximately **19.4 GB of uncompressed
file content including duplicate copies**, across BTC, ETH, SOL and XAUT. Initial
planning estimate on the new PC with an SSD: **30-90 minutes for all four coins**,
excluding Python installation and file transfer. This is an unverified range,
not a promise; sorting, decompression, antivirus and storage can dominate.

A bounded synthetic kernel test here processed 100,000 ticks through both candle
timeframes and all four strategy loops in about 0.045 seconds after compilation.
That excludes CSV import, sorting, output and the new computer: it is **not** an
end-to-end runtime estimate. Full historical data has not been replayed here.

For a measured estimate on the destination, use a separate benchmark output:

```powershell
.\.venv\Scripts\python.exe -u crypto_backtest.py --data "D:\Personal\OpenAlgo_Crypto\historical_data" --output benchmark_results --workers 4 --benchmark-ticks 1000000
```

This imports the complete source to measure import cost, then replays the first
million sorted trades per coin. It prints import duration and extrapolated full
replay duration separately. Reports are prominently marked **BENCHMARK SAMPLE**.
The full run must use a different output folder and will import its own cache.
The benchmark estimate includes sorting/JIT overhead and early-period sampling,
so it can differ from full-run time. You can simply start the full run and use
its moving progress estimate instead of running the benchmark first.

## Research assumptions

Default independent entry cap: USD 100,000. Quantity increment: 0.01 base asset
for every coin; fee: 0.05% per fill; adverse slippage: 0.05% per fill. These retain
the prior ETH sizing/cost model and are **research inputs**, not verified broker
contract specifications. `buyer_role` does not change the modeled strategy fee.
Use `--capital`, `--unit`, `--fee`, `--slippage` to change assumptions with a new
output folder. To use a different quantity step for one coin, run that coin with
`--symbols BTCUSD` (or another symbol) in a separate output folder.

P&L models linear USD-settled price exposure. Funding, margin, liquidation,
exchange contract multipliers, changing historical tariffs, tax and FX are absent.
Capital is a per-entry fixed cap; profits are not compounded and a negative
reference equity does not halt further opportunity simulation. Volume does not
limit fills. Results require separate validation before any live strategy use.

## Validation and implementation references

`INSTALL.cmd` runs the included synthetic tests for raw/HA bars, timeframes,
chunk continuity, UTC VWAP reset, long/short sizing, stale signals, actual-price
fills, duplicate ZIP/CSV import, timestamp validation, full reports and resume.
Repository-only verification also matched all **56 fills** and every MTM mark
against the prior compiled engine on 12,000 stored ETH events per timeframe.
HA/BB/VWAP matched the original Maker on 1,200 synthetic ticks including midnight.
See `reference_validation.json`; the original repository is not needed to run.

The importer uses [DuckDB CSV ingestion](https://duckdb.org/docs/current/data/csv/overview)
and [bounded DataFrame result chunks](https://www.duckdb.org/docs/current/clients/python/conversion).
The strategy loop uses CPU Numba compilation, with independent processes across
coins; this does not automatically invoke a GPU.
