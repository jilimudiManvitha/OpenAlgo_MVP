# Eight scheduled strategies — October 1, 2026

Completed all eight saved profiles for 09:15–15:00 IST, with ₹10,000 per entry.

[Interactive report](index.html) · [Summary CSV](summary.csv) · [Summary JSON](summary.json)

| Strategy | Minutes | OLHC trades / net ₹ | OHLC trades / net ₹ |
|---|---:|---:|---:|
| Nifty500 Scanner · Fixed 3R · 10K | 1 | 174 / 536.55 | 194 / -631.85 |
| Weekday Watchlist · Fixed 3R · 10K | 1 | 33 / -1,958.80 | 35 / -2,155.62 |
| Nifty500 Scanner · Trail after 3R · 10K | 1 | 169 / -1,537.56 | 184 / -1,586.85 |
| Weekday Watchlist · Trail after 3R · 10K | 1 | 27 / -1,413.07 | 28 / -1,494.30 |
| Nifty500 Scanner · Fixed 3R · 10K · 5m HA | 5 | 104 / -1,998.04 | 104 / -2,005.70 |
| Weekday Watchlist · Fixed 3R · 10K · 5m HA | 5 | 14 / -1,214.15 | 14 / -1,198.44 |
| Nifty500 Scanner · Trail after 3R · 10K · 5m HA | 5 | 73 / -2,121.34 | 73 / -2,116.46 |
| Weekday Watchlist · Trail after 3R · 10K · 5m HA | 5 | 7 / -456.73 | 7 / -460.33 |

## Inputs and interpretation

- Full coverage: 73/73 scanner stocks and 20/20 Thursday-watchlist stocks, 91 distinct symbols. Every symbol has all 375 regular-session minute bars and prior-session indicator warmup. No exclusions.
- Uses the saved October 1 scanner snapshot at 15:36:30 IST and the current Thu list, applied retrospectively. Historical intraday membership is unknown. Clearing Wed did not affect this Thursday replay.
- OLHC means open→low→high→close; OHLC means open→high→low→close. These are alternative modeled paths, with eight samples per leg and uniform modeled volume. They are not observed ticks or guaranteed best/worst bounds. Do not add scenarios.
- Net includes 5 bps adverse slippage per side and illustrative 5 bps charges per fill. Actual taxes, spread and Sandbox fill delays are not reproduced.
- ₹10,000 is a per-entry notional cap; there is no total portfolio capital cap. Strategies run independently; these are not combined portfolio results.
- Drawdown uses realized trade equity, not intratrade mark-to-market. One session does not establish future performance; Sharpe and Sortino are not estimated.
- NIFTY 50 gross benchmark: 22,543.70 at 09:15 → 22,399.25 at 15:00 (-0.6408%). Strategy returns use peak concurrent notional, a different capital basis.

Only the 1m scanner fixed-3R profile was profitable under OLHC, and it lost under OHLC. All other profiles lost under both paths; no profile was profitable under both.

## Verification and reproduction

The replay exited successfully and verified all eight ledgers. Export checks independently recomputed metrics, checked selections/timeframes, source hashes, whole-share sizing, signal timing, and all exits by 15:00. All 69 focused strategy tests passed. Data verification is in `input_verification.json`; saved schedule metadata is in `schedule_snapshot.json`. HTML table and download links were checked; browser rendering was not verified because no browser surface was available.

Reports are saved as `backtest-2026-10-01-<profile>` in the OpenAlgo report database. Source cache: `db/scanner_backtest_cache/2026-10-01-four-strategies/`. No strategy execution, order submission, schedule edit or application restart was performed.

```sh
.venv/bin/python -m strategies.top_gain_volumes.replay_four --day 2026-10-01
.venv/bin/python backtesting/eight_scheduled_20261001/export_report.py
```

The replay reads the then-current saved scanner/watchlist inputs; compare them against this directory’s frozen `selection.json` before reproducing. Export reads the saved backtest reports. Add `--fetch-missing --retry-invalid` only if source history needs downloading.
