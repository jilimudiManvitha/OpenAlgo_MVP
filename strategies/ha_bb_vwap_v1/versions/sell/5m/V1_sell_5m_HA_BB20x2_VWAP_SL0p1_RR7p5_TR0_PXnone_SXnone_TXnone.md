# 1. Strategy name

`V1_sell_5m_HA_BB20x2_VWAP_SL0p1_RR7p5_TR0_PXnone_SXnone_TXnone`

## 2. Strategy description

V1 short/sell, 5-minute regular-session Indian equity candles.
Capital: Rs 100,000 per trade, integer shares, no assumed leverage. This is code
only: no backtest, forward test or broker order has been run. A separate engine
instance represents one symbol/version/timeframe. Different versions are research
alternatives; running them together does not create a shared capital constraint.

Indicators: HA-close Bollinger SMA(20), 2 population standard deviations; SMA(9),
EMA(9), EMA(21), RSI(14), MACD(12,26,9), HA-HLC Supertrend(14,2). Session VWAP
uses real HLC3 and real volume, reset each IST date. Other indicators and HA carry
across sessions. Use sufficient completed history for indicator warm-up; undefined
indicators cannot satisfy their conditions. `openalgo.ta` supplies indicators.

## 3. Entry conditions

The completed signal candle must have no upper wick (buy HA low equals HA open;
sell HA high equals HA open, within a tiny numerical tolerance). Its HA
low must be below BOTH its Bollinger lower band and
VWAP. Opening on the other side of VWAP is allowed. The opposite wick is optional.
The immediately next 5-minute candle, on the same IST date,
must also have no upper wick as observed so far. Emit a sell entry intent
on its first observed real price strictly below the signal
low, the current Bollinger lower band, and current VWAP.
Equality is not a breakout. Gaps beyond those levels qualify at the actual observed
price. Missing the immediate next interval expires the signal. One entry attempt
per signal; no simultaneous position in the same engine. A final-only CSV candle
cannot cause an intrabar entry. The adapter must provide forming updates and
acknowledge actual fills; the eventual candle cannot retroactively invalidate entry.

Entry window: 09:15 inclusive to 15:05 exclusive for F&O-member stocks, or 15:20
exclusive for non-F&O stocks. Membership is an explicit input, never inferred
from a name. Share quantity is floor(100000 / real entry reference price).

## 4. Exit conditions

Exit side: buy to cover. Fixed stop and fixed RR target always remain enabled.
Additional stop rule: `none`. Additional profit-taking rule:
`none` (requires positive current gross price profit).
Rules are alternatives, OR-connected: first applicable exit wins. Priority is
session square-off, existing hard/trailing stop, updated trailing stop, indicator
stop, fixed target, profitable indicator exit, then partial-exit milestones.
Stops/targets are compared with the current observed real price, with actual
execution price acknowledged separately; no perfect fills at crossed levels.

`tick` uses the current real price/current forming indicators. `full` requires a
completed candle and its entire HA OHLC range on the adverse side of a price line:
buy HA high below the line, sell HA low above it. Supertrend tick mode requires
red for buy / green for sell; full mode additionally requires the entire HA range
beyond the Supertrend line. RSI exits compare the RSI value itself: buy below 60,
sell above 40; full means evaluate on completion. MACD exits require a bearish
line/signal crossover for buy or bullish crossover for sell; full compares completed
snapshots, tick compares consecutive observed snapshots. No price-to-RSI/MACD comparison.

Partial preset: `none`. `none` keeps all shares until a full exit.
`half_1r_2r`: floor(50% of original shares) at +1R, remainder at +2R.
`quarter_1p5r_2p5r`: floor(25%) at +1.5R, remainder at +2.5R. At least one share
is retained for the final exit; a zero-sized first slice is skipped. Each slice
is requested once after fill acknowledgement. A jump beyond the final milestone
closes the full remaining quantity. A lower fixed RR target can close the trade
before the partial preset's final milestone; this overlap is intentional.

Square off all remaining shares at 15:05 / 15:20 IST. Call `on_clock` at that time
even without a tick; this package creates no timer. The synchronous reference
interface requires each pending intent to be fully acknowledged or rejected before
processing the next update. Partial broker fills, asynchronous cancellation and
broker connectivity require an execution adapter before live use.

## 5. Stop loss

Initial stop = signal HA high plus 0.10 points. Risk R is the positive distance
from ACTUAL entry fill to this stop and stays fixed for the life of the trade.
No trade is permitted if risk is nonpositive. Additional stop rule is
`none`, evaluated as described above regardless of current profitability.

Trailing fraction: 0%. Zero disables trailing. Otherwise
activate only after the best observed real price reaches +1R and configured RR
is at least 2. Trail distance = 0% of the configured target
profit distance (RR times initial R). Long stop follows best price minus distance;
short stop follows best price plus distance. Clamp to breakeven on activation,
never loosen, and do not reset R after partial exits. Breakeven is before costs.

## 6. Target profit

Fixed target = actual fill - 7.5 times initial R.
The gross reward:risk ratio is 1:7.5. Additional target rule:
`none`. It may take profit earlier, as may the partial preset,
trailing stop or square-off. Costs/slippage are not assumed zero returns: this
package calculates no performance and makes no profitability claim.

See [the full contract](../../../README.md) for wording corrections, integration,
data assumptions and the combination generator. The original brief is
`strategy_sell_doc.txt` in the repository root.
