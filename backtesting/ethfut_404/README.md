# ETHFUT: all 404 HA/BB/VWAP versions, 24/7

**Completed 2026-09-13:** all 404 versions; 153,656 independent modeled trades,
308,920 fills, 5,211 overnight trades. Source/fill/CSV verification and offline
browser checks passed. These totals span independent strategies, not one portfolio.
Only 25 versions were profitable (14 buy-5m, 11 sell-5m); all 1m versions lost money
after modeled costs. Best net: **S104, buy 5m, RR 10.5**, USD 12,030.83, 95 trades,
11.58% win rate, USD 22,530.45 maximum drawdown. Its best trade earned USD 11,951.21;
the remaining trades together earned only USD 79.62. This concentration matters
when interpreting the retrospective winner. Funding and tax remain excluded.

This isolated experiment reads only
`D:/Personal/OpenAlgo_Crypto/historical_data/ethfut/**/*.zip`.
The supplied archives contain 518,675 ETHUSD trades from April and May 2024.
It does not change the Crypto tree, original strategy package, or the running
`backtesting.ha_bb_vwap_allstocks` job or its results.

From `D:/Personal/openalgo`, using PowerShell:

```powershell
$env:POLARS_MAX_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
& backtesting/.venv/Scripts/python.exe -u -m backtesting.ethfut_404.run
```

The command prepares causal snapshots then runs every version serially, verifies
every fill ledger with VectorBT, and writes the offline [HTML report](results/index.html),
[written report](results/report.md), rankings, per-version trades/fills/daily CSVs,
source audit and configuration manifest. `results/progress.json` records completed
versions. Do not launch a second ETH copy while one is active. The all-stocks job
is separate and can remain active.

The `--prepared` flag skips snapshot generation for the same verified source
archives. Use it only after a successful preparation with unchanged snapshot
code; it checks shapes, last timestamp and source hashes. Default full preparation
is the reproducible command after any code/data change. No source data is fetched.

## Interpretation

- All 404 materialized configs retain their original IDs, sides, 1m/5m timeframes,
  HA/BB/VWAP entries, stop buffers, reward/risk, trails, partials and indicator exits.
  The compiled execution core is checked against the original Python engine in an
  isolated namespace with session restrictions removed. No global monkey-patching.
- Entries are available 24/7. Signals and positions carry over midnight. Missing
  bars invalidate next-bar entries. Only final data termination forces liquidation.
- Naive source timestamps are assumed UTC. Daily raw-price typical-price VWAP resets
  at UTC midnight; this is an indicator anchor, not an entry/exit restriction.
  HA state is continuous. OpenAlgo indicators use at most 600 completed nonempty
  bars plus the causal forming bar. Startup has no external warmup.
- Actual source trades build cumulative candles. No OHLC path is invented. An
  order triggered by a forming trade fills at that trade plus adverse slippage;
  a completed-bar order fills at the next available source trade. This assumes
  instantaneous market reaction and sufficient liquidity. Gaps, spread, latency
  and order-book participation can materially change live execution.
- Research assumptions: USD 100,000 fixed entry notional per independent version,
  0.01 ETH sizing increments (integer internal units for partial exits), 0.05%
  trading fee per side, 0.05% adverse slippage. These are not verified historical
  contract specifications, broker tariffs or an INR account simulation. Original
  numerical stop buffers become USD price offsets. No leverage is assumed.
- Net means after modeled fees/slippage, **before funding and tax**. Funding,
  historical contract/tax terms, margin, liquidation and FX data are absent.
  USD 100,000 is the fixed return denominator; these independent opportunity
  tests are not one shared portfolio or compounded cash-constrained accounts.
- ETH buy-and-hold uses the same input trades, sizing, fees and slippage. No BTC,
  NIFTY or other price data is downloaded. Every-observation MTM determines maximum
  drawdown; the chart uses daily samples and can show a smaller drawdown. Daily
  Sharpe/Sortino annualize fixed-capital P&L returns by 365 at zero risk-free rate.
- The archive has 223 trade gaps longer than five minutes, largest ~104 minutes.
  No source completeness guarantee exists. The 2025 and 2026 folders are empty.
  Rankings across 404 versions over two months are retrospective, not an untouched
  holdout or evidence of stable future returns.

## Verification

```powershell
& backtesting/.venv/Scripts/python.exe -m pytest backtesting/ethfut_404/test_engine.py -q --confcutdir=backtesting/ethfut_404 -o addopts= -p no:cacheprovider
node backtesting/ethfut_404/verify_browser.cjs
& backtesting/.venv/Scripts/python.exe -m backtesting.ethfut_404.verify
```

Parity uses the first 12,000 actual trade/complete observations of each timeframe
for all 404 configs, plus synthetic midnight, stale-signal gap and final-liquidation
checks. Full-history fills and final P&L reconcile independently through VectorBT.
