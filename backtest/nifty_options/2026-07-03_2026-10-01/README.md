# NIFTY options: three-month backtest

**Period: July 3–October 1, 2026 · 64 trading sessions · 12 strategies · two modeled paths.**

[Open combined dashboard — all 12 strategies](results/combined_dashboard.html) · [Combined metrics CSV](results/combined_metrics.csv) · [Detailed original results](results/index.html) · [Summary CSV](results/summary.csv) · [Benchmark comparison](results/benchmark_comparison.csv) · [Ledger verification](results/ledger_verification.json) · [Run status](results/status.json)

Use `results/status.json` to confirm the current run finished. Results are local only; nothing is written to application Reports.

## Results

Net P&L includes illustrative fees, slippage and observed marks on positions still open at the end. Each strategy has ₹20 lakh allocated. OLHC and OHLC represent assumed price order inside each one-minute candle, not observed tick sequences or guaranteed performance bounds.

| Strategy | OLHC net ₹ | OHLC net ₹ | OLHC return | OLHC max drawdown | Open legs per path |
|---|---:|---:|---:|---:|---:|
| iron_condor_intraday_current_week | 16,236.78 | 15,897.93 | 0.812% | -9.618% | 0 |
| iron_condor_intraday_next_week | 46,175.54 | 46,192.39 | 2.309% | -3.136% | 0 |
| iron_condor_positional_current_week | 35,324.67 | 35,511.66 | 1.766% | -4.370% | 0 |
| iron_condor_positional_next_week | -36,830.03 | -36,734.12 | -1.842% | -2.412% | 0 |
| delta_intraday_current_week | 55,859.63 | 55,849.87 | 2.793% | -2.048% | 0 |
| delta_intraday_next_week | 14,155.50 | 14,145.74 | 0.708% | -1.625% | 0 |
| delta_positional_current_week | 50,506.29 | 50,506.28 | 2.525% | -2.010% | 0 |
| delta_positional_next_week | -18,057.40 | -18,060.65 | -0.903% | -1.543% | 0 |
| premium_intraday_current_week | 649.03 | 649.03 | 0.032% | -1.670% | 0 |
| premium_intraday_next_week | -7,254.44 | -7,254.44 | -0.363% | -1.284% | 0 |
| premium_positional_current_week | 31,506.33 | 31,506.33 | 1.575% | -0.386% | 1 |
| premium_positional_next_week | 22,455.44 | 22,455.44 | 1.123% | -0.266% | 1 |

Nine variants are positive and three negative under both paths. Delta intraday current-week has the highest ending profit (about ₹55,850); iron-condor positional next-week has the largest ending loss (about ₹36,800). Iron-condor intraday current-week has the largest peak-to-trough drawdown, about ₹2.15 lakh / 9.62%, despite ending profitable. Drawdown can accumulate over multiple trade cycles: the ₹20,000 stop is per cycle, not a trailing peak-equity stop.

The arithmetic sum across the twelve allocations is ₹2,10,727.34 OLHC / ₹2,10,665.46 OHLC, about 0.878% on ₹2.4 crore allocated. This sum is not a shared-account execution or cross-strategy margin simulation. NIFTY 50 gross return was −7.794%, with −10.312% minute-close drawdown; the index comparison has different exposure and excludes trading costs.

## Coverage and limitations

- 7,096 contract archive requests completed across 15 expiries, plus the NIFTY minute series. Explicit no-data contracts remain empty. Completion does not imply every option traded every minute.
- All 64 expected sessions are present. Both paths have 1,214 closed legs and two open legs: one in each premium positional variant. Those open positions are marked, not force-closed.
- Iron-condor positional next-week has three missing held-basket minutes per path. Monitoring waits for the next complete observed bar; no missing price or fill is invented. These gaps can delay stops and understate drawdown.
- Greek estimation is unavailable for six held minutes in iron-condor intraday current-week and two in iron-condor positional next-week, per path. Price stops continue; delta adjustments wait. Selection failures and gaps are saved in each variant’s `skipped_entries.json`; repeated failed re-entry minutes are not separate missed trading days.
- Historical deltas use Black-76 with a parity-implied forward and zero interest. Historical sizing uses the documented conservative margin model and a 10% reserve, not historical SPAN. Scheduled paper sizing uses broker basket margin.
- Costs are illustrative: ₹20 plus 0.1% turnover per fill, and ₹0.05 adverse slippage. Synchronized candle paths, prior-minute selection and next-open fills are modeling assumptions. Minute-end drawdowns omit unobserved intraminute lows.
- The ₹20,000 stop can be exceeded by gaps and closing costs. The worst completed OLHC cycle was −₹27,533.31 in iron-condor positional current-week. Live market-hour fills and restart behavior with real incoming ticks remain unverified.

## Verification and reproduction

The replay reconciles closed legs independently with VectorBT, then checks exported cash flow, fees, final observed marks, drawdowns, chronological whole-lot fills, frozen source hashes and local links. See the linked verification JSON for the completed run. Code and policy are copied under `results/source/`; raw data hashes are in `results/verification.json`. Forty-five focused implementation tests pass.

From the project root:

```sh
.venv/bin/python -m strategies.nifty_options.history --start 2026-07-03 --end 2026-10-01
.venv/bin/python -m strategies.nifty_options.replay --manifest backtest/nifty_options/2026-07-03_2026-10-01/manifest.json
.venv/bin/python -m strategies.nifty_options.verify_results backtest/nifty_options/2026-07-03_2026-10-01/results
```

The downloader resumes cached files. Replay recomputes this result folder; preserve a copy before changing assumptions if comparisons are needed. Future backtests also belong under `backtest/`, never application Reports.

[Strategy rules, defaults and scheduling](../../../strategies/nifty_options/README.md)

## Single combined dashboard

`results/combined_dashboard.html` is a self-contained offline report covering the
whole period. It has one row per strategy with closed trade counts, wins/losses,
win rate, profit factor, win/loss payoff, expectancy, fees, returns, drawdown,
Sharpe/Sortino and open positions. A trade means a full completed strategy cycle,
including adjustments; individual option-leg counts are shown separately.
Open cycles are excluded from trade win statistics, but their marked P&L remains
in total results. OLHC/OHLC are switchable alternative scenarios, never added.

Filters, numeric sorting, CSV export, six interactive charts and an embedded
trade-cycle table were checked in Chrome for all 24 scenarios. Desktop/mobile
layout checks pass, with no page errors or network requests. Monthly P&L sums
to each strategy's full-period result. Input and renderer hashes are saved in
`results/combined_dashboard_verification.json`; original simulation source and
results remain unchanged. Browser evidence and screenshots are beside it.

Rebuild the combined report from existing ledgers (no market-data requests):

```sh
.venv/bin/python -m strategies.nifty_options.dashboard backtest/nifty_options/2026-07-03_2026-10-01/results
```

Future replay reporting automatically generates the same combined dashboard.
