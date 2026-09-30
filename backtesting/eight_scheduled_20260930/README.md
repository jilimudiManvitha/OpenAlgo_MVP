# Eight scheduled strategies — September 30, 2026

Completed historical simulations for all eight scheduled profiles, 09:15–15:00
IST, using the current 0.03%-below-HA-low stop and ₹10,000 per entry.

[Interactive offline report](index.html) · [Summary CSV](summary.csv) ·
[Summary JSON](summary.json)

| Strategy | Timeframe | OLHC trades / net | OHLC trades / net |
|---|---:|---:|---:|
| Nifty500 fixed 3R | 1m | 160 / ₹8,013.60 | 165 / ₹6,599.20 |
| Weekday fixed 3R | 1m | 27 / −₹815.42 | 31 / −₹838.37 |
| Nifty500 trailing | 1m | 184 / ₹1,232.77 | 202 / ₹434.20 |
| Weekday trailing | 1m | 29 / −₹1,180.47 | 33 / −₹1,279.52 |
| Nifty500 fixed 3R | 5m | 93 / ₹3,785.33 | 94 / ₹3,472.24 |
| Weekday fixed 3R | 5m | 12 / −₹358.05 | 12 / −₹313.36 |
| Nifty500 trailing | 5m | 64 / ₹2,081.62 | 64 / ₹1,862.88 |
| Weekday trailing | 5m | 6 / ₹85.53 | 6 / ₹81.91 |

## Coverage and interpretation

- Nifty500 scanner: 76/76 selected stocks. Wednesday watchlist: 16/18 stocks;
  GANESHBE and STLTECH are BE-series and excluded by the scheduled EQ-only universe.
  All 90 distinct eligible stocks have validated source history.
- OLHC is open→low→high→close; OHLC is open→high→low→close. Each minute uses
  eight samples per leg and uniform modeled volume. These are alternative
  simulated paths, not observed ticks or guaranteed best/worst bounds. Do not
  add the scenarios. Five-minute OHLCV aggregation precedes HA/BB/VWAP.
- Net includes 5 bps adverse slippage on each side and illustrative 5 bps fees
  per fill. This is not an actual broker tax/charge calculation.
- The scanner basket comes from the final 15:30:46 snapshot; the saved Wednesday
  watchlist is applied retrospectively. Intraday membership changes are unknown,
  so selection bias remains. Simulations do not reproduce actual bid/ask or
  delayed Sandbox fills. Today's interrupted forward reports remain unchanged.
- ₹10,000 is per trade, not a portfolio capital limit. Fixed Nifty500 peak
  simultaneous notional was about ₹5.90–5.99 lakh (1m) and ₹6.05–6.15 lakh (5m).
  Strategies were simulated independently; results are not a combined portfolio.
- Drawdown uses realized trade equity, not intratrade mark-to-market. One-session
  Sharpe/Sortino are not reported. NIFTY 50 gross benchmark was −0.1224%, from
  09:15 open 22,665 to 15:00 open 22,637.25; its return basis differs from strategy
  net return on peak notional.

## Data and verification

FYERS calendar-day requests initially returned 750 rows with duplicated and
conflicting timestamps. Those inputs were rejected and preserved as
`*.retry-invalid.json`. Exact 09:15–15:29:59 epoch requests returned valid unique
session candles; no conflicting values were silently deduplicated or fabricated.
The scheduled history loader now uses the same session boundaries, with a
regression test. Warmup needs at least 20 aggregated bars.

Report IDs are `backtest-2026-09-30-<profile>` in
`db/scanner_strategy_reports.db`. Sources and selection manifest are under
`db/scanner_backtest_cache/2026-09-30-four-strategies/`.
Each `<profile>_trades.csv` here contains both scenarios. Benchmark source data
and hashes are saved in `nifty_session_source.json` and `nifty_benchmark.json`.

All eight trade ledgers passed verification. The exporter independently checks
profile/timeframe/selection coverage, source hashes, recomputed metrics, expected
BE exclusions, and that all simulated positions close by 15:00. All 61 focused
strategy tests passed. The offline HTML rendered its tables, charts and CSV links
in Chrome. No broker orders or schedule changes were made by this backtest.

Reproduce from the repository root (cached replay does not need a network call):

```sh
.venv/bin/python -m strategies.top_gain_volumes.replay_four --day 2026-09-30
.venv/bin/python backtesting/eight_scheduled_20260930/export_report.py
.venv/bin/python -m pytest test/test_eight_sandbox_strategies.py test/test_four_sandbox_strategies.py test/test_top_gain_volumes.py
```

To download missing/invalid data, append `--fetch-missing --retry-invalid` to the
replay command; this requires a valid FYERS login and network access.
