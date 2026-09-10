# ATHERENERG: Astra HA / BB / VWAP report

**INSUFFICIENT HISTORY - full strategy not evaluated**

Input: `D:\Personal\historify_ATHERENERG_20260908_112029\ATHERENERG_NSE_5m.csv`. Data covers 2026-06-29 09:15:00+05:30 through 2026-06-29 15:25:00+05:30 (bar-open timestamps),
75 candles and 1 complete regular session(s). The export filename date is not the candle date.

The original strategy functions perform the Heikin Ashi conversion and all indicators.
HA close = (O+H+L+C)/4; first HA open = (O+C)/2; subsequent HA open =
(previous HA open + previous HA close)/2. HA high/low include the real high/low and HA open/close.
Volume is unchanged. HA is seeded at the beginning of this file; preceding history could change early candles.
BB uses 20 HA closes and population standard deviation; the first 19 bars are warmup.
VWAP uses real HLC3 and resets each session. Execution uses real OHLC with the original next-bar rules.
Synthetic HA prices are unsuitable as executable prices; see
[TradingView's explanation](https://www.tradingview.com/support/solutions/43000481029-strategy-produces-unrealistic-results-on-non-standard-chart-types-heikin-ashi-renko-etc/).

The default cumulative-volume filter requires 20 prior full sessions. Available RVOL bars: 0.
Minimum required input is 21 sessions (1,575 complete five-minute bars).
No missing history is filled, no filters are relaxed, and unavailable RVOL is not treated as zero.
Price-only markers are diagnostics and are not trade signals. Markers label the candle opening time;
their conditions become knowable five minutes later at candle close.

| Diagnostic | Count |
|---|---:|
| Valid BB bars | 56 |
| Fresh HA-close upper-BB crosses | 6 |
| Price-only signal candidates | 4 |
| Price-only confirmations | 1 |
| Qualified signals | 0 |
| Qualified confirmations | 0 |

| Comparison | Strategy | ATHERENERG raw price reference |
|---|---|---|
| Return | N/A: missing warmup | 9.3939% |
| Max drawdown | N/A | Not calculated as a portfolio |
| Sharpe / Sortino / win rate / profit factor | Not reported | Not applicable |

The reference is the first real open to final real close, before costs, without share sizing.
It is not a strategy profit or a NIFTY benchmark. NIFTY data was not supplied; a benchmark or
annualized risk statistic would not repair the missing strategy warmup.
Initial capital assumption: INR 10,000; risk 0.5% per trade;
fees 5.0 bps per side; adverse slippage 5.0 bps; no leverage.
These are the supplied script's illustrative defaults, not a verified broker charge schedule.

`ATHERENERG_visual_backtest.html` is interactive and self-contained, with real/HA candles,
BB/VWAP, volume, RVOL and performance panels. `ATHERENERG_chart.png` is the static preview.
`ATHERENERG_heikin_ashi_5m.csv` contains synthetic OHLC and must not be fed back into the strategy
as raw candles (that would convert twice). The normalized real OHLC CSV is the correct strategy input.
The trade CSV has headers even when no evaluable trades exist. See `summary.json` for status and hashes.

Engine output:
```
Backtest unavailable: 1 complete session(s); need at least 21.
```
