# BUY HA1m + BB20x2 + VWAP + no lower wick + SL0.10 + TP3R

User specification: `../strategy_buy_doc_.txt`. The final paragraph requests a
backtest and output now, superseding its opening “code only” sentence.
On September 25 the user explicitly confirmed the buy-breakout interpretation:
both candles have no lower wick; upper wicks are optional; the breakout price
must be above the upper Bollinger Band and VWAP. The conflicting “below VWAP
or lower band” sentence is not used as an entry or exit condition.

## 1. Strategy names and files

- **BUY_HA1m_BB20x2_VWAP_NoLowerWick_SLsignalLowMinus0.10_TP3R_OnePerDay_OLHC**:
  `buy_ha1m_bb20x2_vwap_sl010_tp3r_olhc.py`.
- **BUY_HA1m_BB20x2_VWAP_NoLowerWick_SLsignalLowMinus0.10_TP3R_OnePerDay_OHLC**:
  `buy_ha1m_bb20x2_vwap_sl010_tp3r_ohlc.py`.

These are two execution scenarios for **one fixed trading strategy**, not
different optimized parameter versions. Each named file exposes `backtest(...)`
and shares the compiled implementation in `engine.py`. `run.py` executes both
configurations and the report keeps their results separate. No additional
target, trailing-stop or indicator-exit versions were requested.

## 2. Description and indicators

Long-only breakout on the supplied 50-stock NSE list, one-minute candles.
The date request is September 25, 2021 through September 25, 2026 inclusive.
Times and trading-day boundaries are Asia/Kolkata.

For raw market O/H/L/C:

```text
HA close = (O + H + L + C) / 4
HA open  = (previous HA open + previous HA close) / 2
HA high  = max(H, HA open, HA close)
HA low   = min(L, HA open, HA close)
```

Seed the first available valid regular-session HA open with `(O+C)/2`.
Carry HA and Bollinger history across sessions; do not fabricate missing bars.
Read up to 30 calendar days before the requested start for warmup if available.
The supplied five-year source starts September 27, so no earlier warmup exists
for its first session. Wait for 20 valid HA candles before a signal is ready.
Bollinger is SMA of 20 HA closes ± 2 population standard deviations.
VWAP is the cumulative **raw** `(H+L+C)/3 × volume`, divided by volume,
reset at each IST date. HA volume is the original minute's market volume.

## 3. Entry conditions

1. Evaluate a **completed** signal candle: HA close > HA open; HA low equals
   HA open within numerical tolerance; HA high is strictly above that candle's
   upper Bollinger Band and VWAP. A high above the band qualifies without
   requiring a close above it, as requested. No separate fresh-cross-from-below
   requirement is imposed. Signal open may be below VWAP.
2. The candidate entry is **only the immediately following consecutive minute,
   within the same day**. At the modeled entry instant, its forming HA candle
   has no lower wick and HA close > HA open. The current **market price** is
   strictly above signal HA high, forming upper Bollinger Band and forming VWAP.
   Entry open may be below VWAP. An upper wick is not required.
3. Enter at the qualifying instant; do not wait for entry candle close. A lower
   wick appearing afterward does not cancel the trade. The ledger records
   `entry_final_has_lower_wick` for inspection. Requiring the entry's final
   wick state would use information unavailable at entry.
4. Up to ₹100,000 market-entry notional per trade. Whole-share quantity is
   `floor(100000 / modeled entry fill)`. No leverage or compounding. Fees are
   additional to that notional cap. Reject zero quantity/nonpositive risk.
5. Maximum **one filled trade per symbol per day per scenario**, whether it
   exits by stop, target or clock. Reset the trade allowance the following day.
   Different symbols may overlap; there is no shared cash or insolvency limit.
6. Trade from 09:15 until that stock's square-off. Zero-volume entry candles
   cannot open positions. No RVOL, turnover or other volume threshold is added.

## 4. Exit conditions

Exit the entire quantity at the first stop or target reached after entry along
the chosen modeled path. Otherwise square off at the **15:05 opening market
price for F&O stocks**, or **15:20 opening market price for non-F&O stocks**.
There is no trailing stop, partial exit, re-entry, VWAP exit or overnight carry.
A stop gap fills at the next available market open with adverse slippage;
it cannot fill at an unavailable old stop. A resting target limit fills at
its target, including favorable gaps, with no favorable gap-price improvement.

The current local `symtoken` master classifies all 50 supplied stocks as F&O
and supplies their current ticks. Those classifications/ticks are applied to
the full history as a **research assumption**, not verified historical facts.
The engine and tests also support the 15:20 non-F&O branch. No live orders are sent.

## 5. Stop loss

`signal HA low − ₹0.10`, rounded down to a valid current-master tick. ₹0.10
is a price-point offset, not a percentage. Risk is actual modeled entry fill
minus the rounded stop. Once entered, this stop is fixed.

## 6. Target profit

`entry fill + 3 × (entry fill − stop)`, rounded up to a valid tick. Thus the
gross price target is at least 3R; fees, stop slippage and gap losses change
realized net reward/risk. The target does not move.

## Intraminute reconstruction and assumptions shared by both named files

One-minute OHLCV has no tick order. OLHC traverses open→low→high→close and OHLC
traverses open→high→low→close. Each of three legs lasts 20 modeled seconds.
Volume accumulates uniformly over the minute. Forming HA, Bollinger and VWAP
are recalculated from the path seen so far. Final minute volume is used to
construct this assumed volume path; this is not a measured intrabar volume feed.
Entry checks sample 32 points per leg and bisect a qualifying bracket 32 times.
Stops/targets use exact line-segment barrier crossings after entry, not sampled
exit checks. Neither scenario is a guaranteed upper/lower bound on real trading.

Default market-fill slippage is 5 bps adverse plus adverse tick rounding.
The target is a resting limit, so it is not filled below its limit. Fee is a
flat illustrative 5 bps of every fill's turnover. This is **not a reconstructed
historical broker/tax schedule**. Gross P&L already includes slippage; net P&L
subtracts modeled fees. The ledger retains reference prices, slippage, fees and
both P&Ls. These cost parameters can be changed explicitly in a new run.

Every valid completed regular-session bar is exported to Parquet. Invalid
OHLC/volume/price rows are quarantined without repair; they do not enter HA
recursion. Their stock-day is excluded from replay, even if the invalid bar is
after square-off. Any missing minute from 09:15 **through the square-off minute
inclusive** also excludes that stock-day. Indicators continue through remaining
valid observed candles on excluded days; irregular/special sessions outside
09:15–15:29 are outside this model. Audit exclusions alongside performance.

This supplied present-day Nifty basket has survivorship bias. Historical index
membership, F&O changes, price adjustments/corporate actions, queues, circuit
limits, participation constraints and historical ticks are not reconstructed.
Daily-close drawdown omits intraday drawdown. The simulation keeps allocating
₹1 lakh after losses and therefore can lose more than the initial 50-stock
reference capital; it is not a funded account simulation.

Primary references: [TradingView HA formula](https://www.tradingview.com/support/solutions/43000619436-understanding-heikin-ashi-charts/),
[synthetic-price backtest limitations](https://www.tradingview.com/support/solutions/43000481029-strategy-produces-unrealistic-results-on-non-standard-chart-types-heikin-ashi-renko-etc/),
[DuckDB read-only connections](https://duckdb.org/docs/current/clients/python/dbapi).
