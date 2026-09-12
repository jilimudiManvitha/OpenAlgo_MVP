# HA + Bollinger + VWAP V1: buy and sell strategy code

Implements the code-only request in `strategy_buy_doc_.txt` and
`strategy_sell_doc.txt`, received on 12 September 2026. No market-data backtest,
forward test, broker connection, order or historical CSV conversion is performed
by this package. Existing trading application and earlier strategy code are untouched.

## Files and coverage

- `models.py`: settings, candle/snapshot contracts, position and order-intent types.
- `indicators.py`: causal real-candle to HA/indicator adapter using `openalgo.ta`.
- `engine.py`: common event-driven entry, exit and fill-accounting implementation.
- `versions/buy/1m`, `versions/buy/5m`, `versions/sell/1m`, `versions/sell/5m`:
  101 separately named Python strategies and 101 adjacent Markdown documents in
  each folder, 404 strategies total. Each document has the requested six sections.
- `versions/manifest_0_listed.csv`: complete index of these 404 files/configurations.
- `variants.py`: lazy enumeration of every full Cartesian configuration.
- `generate.py`: materialize any range of combinations as separate Python files
  and six-section documents; no strategy evaluation occurs during generation.
- `tests/test_strategy.py`: synthetic unit examples, not market-data backtests.

Every separate strategy module exports its immutable `CONFIG` and a
`create_strategy(symbol, is_fo)` factory. Implementations share the engine so a
bug fix applies consistently to all versions. They are importable Python modules,
not independent broker bots, and importing them does not start anything.

## Entry contract

Both signal and entry use Heikin Ashi candles at the selected 1/5-minute timeframe.
The signal is a **completed** candle. Buy: its HA high is strictly above BOTH
Bollinger upper band and VWAP, and HA low equals HA open (no lower wick). Sell:
HA low is strictly below BOTH Bollinger lower band and VWAP, and HA high equals
HA open (no upper wick). This implements the brief's “cross or close” by allowing
the high/low extension without requiring the close itself beyond the band.

The immediate next interval is the only entry candidate. Its current real traded
price must exceed the signal HA high for buy, or break the signal HA low for sell,
AND be beyond its current directional Bollinger band AND VWAP. Its HA candle as
observed so far must have no adverse wick. No entry-candle close is awaited.
A first observed price already beyond all thresholds qualifies, including a gap;
the reference price is that observed price, not the old signal high/low.

An opposite wick is optional; the open may lie across VWAP. A lower buy wick or
upper sell wick disqualifies the candle. “No lower wick” means HA low = HA open
on the bullish candle; “no upper wick” means HA high = HA open on the bearish
candle. Equality uses relative tolerance 1e-10, not a full tick of leeway.

There is no lookahead: a forming entry candle can acquire an adverse wick later.
That later change cannot invalidate an earlier decision. A completed 1/5-minute
CSV alone cannot establish the order of intrabar events. The engine consequently
does not invent an intrabar entry from a final-only candle. A future backtest must
provide suitable tick/sub-bar observations or separately declare an approximation.
Preconverted HA CSVs alone are also insufficient for real fills and raw-price VWAP.

## Corrections and interpretation choices

These choices are documented defaults, not confirmations received from the user:

| Brief wording / ambiguity | Implemented interpretation |
|---|---|
| Sell entry says “place buy order” | Open a sell/short position; buy closes it. |
| Sell SL says signal low + buffer | Default signal **high** + buffer, mirroring buy signal low − buffer. `short_stop_anchor="low"` retains the literal alternative. |
| Buy paragraph also says price below VWAP/lower band | Treat as a copied sell phrase; buy requires above upper band AND VWAP. |
| No opposite wick says “ignore” | Do not require an opposite wick; keep all directional filters. |
| Sell RSI stop says below 40, target says above 40 | Mirror long exits: long RSI <60, short RSI >40. Compare RSI, never rupee prices, to the threshold. |
| “Complete HA candle (OHLC) close” beyond a line | Entire completed HA range beyond that line; high below for buy, low above for sell. |
| Complete RSI/MACD candles | Evaluate those oscillators on the completed candle, not four price comparisons. |
| MACD below/above cross | Adverse MACD-line/signal crossover: bearish for buy, bullish for sell. |
| Supertrend colour | OpenAlgo direction +1 is red/down; −1 is green/up. Full mode also requires whole HA range beyond ST. |
| Trail percentage of target “price” | Percentage of target **profit distance**, not the stock's absolute price. `trail_basis="profit_reached"` supports the other queried interpretation. |
| Profit locking | Activate after best observed price reaches +1R; clamp to entry/breakeven and never loosen. |
| Target 1:2, 2.5, 3… up to 30 | 57 RR choices in steps of 0.5, including 30. |
| F&O stock square-off | Equity shares of a stock identified by explicit `is_fo`; no futures lots, leverage or expiry selection is implied. |
| Capital one lakh | Maximum reference-price share notional Rs 100,000 per trade; quantity floor(100000 / price), residual cash unused. Brokerage not included in sizing. |
| All combinations | Cartesian choices, one optional indicator stop and one optional indicator target, OR-connected with hard exits. Arbitrary powersets/Boolean formulas are not inferred. |

Only default interpretations are materialized in `versions/`. The two optional
config fields above are available for later adjustments, and not extra axes of
the 6,918,660-combination count. Their alternative settings are not included in
the generated six-section documents. No gainers/losers scanner-universe filter
has been inferred from earlier work; feed each selected symbol explicitly.

## Indicator settings and data

Use timezone-aware regular-session candles (09:15–15:30 Asia/Kolkata), aligned to
the timeframe. Raw OHLC must be valid and volume nonnegative. Candle timestamps
identify interval starts. Completed candles are observed at interval end; forming
candles carry the actual observation time and only cumulative data observed so far.
History must contain completed bars strictly before the current bar. Nonfinite,
duplicate, unordered and retracting inputs are rejected; source defects are not
silently repaired. Other sessions, exchange holidays and special sessions need
an explicit future calendar/data adapter.

HA close = (O+H+L+C)/4; HA open = (previous HA open + previous HA close)/2; first
HA open = (O+C)/2; HA high = max(raw H, HA O, HA C); HA low = min(raw L, HA O, HA C).
HA state carries across dates. Standard indicators use HA close, except Supertrend
uses HA HLC and VWAP uses raw HLC3/volume from the current IST session only.

- Bollinger: SMA 20, standard-deviation multiplier 2.
- SMA 9; EMA 9 and 21; RSI 14 with 60/40 directional exit thresholds.
- MACD 12/26/9; Supertrend 14, multiplier 2.
- VWAP resets by IST calendar/session date and is undefined with no traded volume.

Indicators are computed with installed `openalgo.ta`. Insufficient history returns
undefined values until each indicator is available; those values cannot trigger
their respective conditions. MACD is withheld until at least 35 observations.
Keep the same history prefix and sufficient warm-up for consistent EMA/RSI/ST
seeding. `build_snapshot` recomputes a supplied prefix as a clear reference adapter;
it is not designed to recompute millions of variants on every tick. Compute one
snapshot per symbol/timeframe/update and share it across the variants you select.

## Exits and accounting

The initial hard stop is never replaced by an indicator rule. Initial R is fixed
from actual acknowledged entry to that stop. Target = entry ± RR × R. Nonpositive
risk, a nonpositive fixed target, and zero share quantity disqualify an entry.
Stops are in unrounded mathematical points; a future broker adapter must apply
the instrument tick size consistently to broker orders and acknowledge real fills.

Stop buffers: 0.10, 0.15, 0.20, 0.25, 0.30 points. RR: 2 through 30 by 0.5.
Trailing: off, or 20/30/40/50/60/70% of RR × initial R, after +1R. The default
has trailing off so the fixed-stop/fixed-target baseline is represented.
Track best **observed real price**; never use a finished bar's later high/low to
move a stop earlier. Breakeven and targets are gross, before fees and slippage.

Partial alternatives are off; 50% of original quantity at +1R and remainder +2R;
or 25% at +1.5R and remainder +2.5R. Round the first slice down and retain at least
one share. A zero first slice is skipped. Partial risk remains based on original R.
The fixed target stays active: RR 2 exits before the 2.5R partial final milestone.
Some full-product configurations therefore behave identically; they remain named
separately so no explicitly requested parameter pairing is discarded.

Indicator alternatives are BB middle, VWAP, Supertrend, SMA9, EMA9, EMA21, RSI and
MACD, each in tick/full modes. Indicator stop rules may exit at either profit or
loss. Indicator target rules additionally require positive current gross price
profit. All applicable exits are OR-connected; the engine's deterministic order
is square-off, prior stop, updated trail, indicator stop, fixed target, profitable
indicator target, partial milestones. A gap beyond a partial final milestone
exits all remaining shares immediately.

Trade only from 09:15 to 15:05 for F&O stocks / 15:20 otherwise, with no new
entries at the cutoff. Square off remaining shares at cutoff. The adapter must
call `on_clock` even without a tick. If an open position reaches a later date
because the clock callback was missed, the first new event requests square-off.
There is no automatic scheduling, overnight strategy or portfolio-wide coordinator.

## Using a definition later

From the repository root, after implementing the chosen data/execution adapter:

```python
from strategies.ha_bb_vwap_v1 import Config, Strategy
from strategies.ha_bb_vwap_v1.indicators import build_snapshot

strategy = Strategy("PINELABS", is_fo=False, config=Config(side="buy", timeframe_minutes=1))
# history: completed real Candle objects; current: a forming/final Candle
snapshot = build_snapshot(history, current, timeframe_minutes=1)
for intent in strategy.on_snapshot(snapshot):
    # An external adapter decides how to execute this request.
    # Acknowledge the completed order's actual fill, or reject/cancel the intent.
    strategy.acknowledge_fill(intent.order_id, actual_average_fill, intent.quantity)
```

`OrderIntent` is not an order sent to a broker. The synchronous research contract
requires a completed fill acknowledgement or an unfilled rejection before the next
market event. It does not implement asynchronous broker partial fills, timeouts,
rejections after partial fills, exchange tick/lot validation or order persistence.
An adverse fill that violates the strict Rs 100,000/risk contract raises for adapter
reconciliation; raising does not undo any real order. Do not wire this directly
to a live account without that adapter and the deferred testing.

One signal has one entry attempt; rejecting it does not create repeated orders.
Stops can retry after an unfilled exit rejection. State remains open until a fill
is acknowledged. There is no `ta.exrem` array pass because signals are event-driven:
pending-order, open-position and consumed-signal state provide duplicate prevention.

## Generating combinations

Default materialization includes each listed variation with all other choices at
defaults: per side/timeframe, 1 baseline + 4 other buffers + 56 other RRs + 6 trails
+ 2 partial presets + 16 stop rules + 16 target rules = 101 definitions.

Full product: 2 sides × 2 timeframes × 5 buffers × 57 RRs × 7 trails × 3 partial
presets × 17 stop rules × 17 target rules = **6,918,660 configurations**. These
are lazily defined by `iter_all()`; millions of files are not pre-created by default.

```powershell
# Reproduce the 404 separate modules and their individual documentation:
& .venv/Scripts/python.exe -m strategies.ha_bb_vwap_v1.generate

# Materialize any slice of the full product (not a backtest):
& .venv/Scripts/python.exe -m strategies.ha_bb_vwap_v1.generate --all --offset 0 --limit 1000

# Explicitly materialize the entire product if desired (13,837,320 code/doc files):
& .venv/Scripts/python.exe -m strategies.ha_bb_vwap_v1.generate --all --limit 6918660
```

Each generation writes its own range manifest. Iterating configurations holds one
configuration at a time. The engine retains a fixed amount of per-symbol state;
it does not retain market arrays, open files, sessions, threads or network clients.

## Sources and validation scope

- User briefs: repository-root `strategy_buy_doc_.txt`, `strategy_sell_doc.txt`.
- [OpenAlgo Supertrend conventions](https://docs.openalgo.in/trading-platform/python/indicators/trend).
- [TradingView: synthetic HA prices and candle construction](https://www.tradingview.com/support/solutions/43000619436-understanding-heikin-ashi-charts/).

Run synthetic correctness checks without running a market-data backtest:

```powershell
& .venv/Scripts/python.exe -m pytest strategies/ha_bb_vwap_v1/tests -q --confcutdir=strategies/ha_bb_vwap_v1/tests -o addopts= -p no:cacheprovider
```
