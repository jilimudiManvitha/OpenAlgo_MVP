"""Create separate code and six-section documentation for selected configurations.

Run from the repository root:
  python -m strategies.ha_bb_vwap_v1.generate
  python -m strategies.ha_bb_vwap_v1.generate --all --offset 0 --limit 1000
  python -m strategies.ha_bb_vwap_v1.generate --all --limit 6918660

Generation only writes definitions/docs. It never runs a strategy or backtest.
"""

import argparse
import csv
from dataclasses import asdict
from itertools import islice
from pathlib import Path

from .models import Config
from .variants import FULL_COUNT, iter_all, listed_variants

PACKAGE = Path(__file__).resolve().parent


def strategy_doc(cfg: Config) -> str:
    buy = cfg.side == "buy"
    side = "long/buy" if buy else "short/sell"
    level, relation, wick = ("upper", "above", "lower") if buy else ("lower", "below", "upper")
    anchor = "signal HA low minus" if buy else "signal HA high plus"
    opposite = "sell" if buy else "buy to cover"
    return f"""# 1. Strategy name

`{cfg.name}`

## 2. Strategy description

V1 {side}, {cfg.timeframe_minutes}-minute regular-session Indian equity candles.
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

The completed signal candle must have no {wick} wick (buy HA low equals HA open;
sell HA high equals HA open, within a tiny numerical tolerance). Its HA
{"high" if buy else "low"} must be {relation} BOTH its Bollinger {level} band and
VWAP. Opening on the other side of VWAP is allowed. The opposite wick is optional.
The immediately next {cfg.timeframe_minutes}-minute candle, on the same IST date,
must also have no {wick} wick as observed so far. Emit a {cfg.side} entry intent
on its first observed real price strictly {relation} the signal
{"high" if buy else "low"}, the current Bollinger {level} band, and current VWAP.
Equality is not a breakout. Gaps beyond those levels qualify at the actual observed
price. Missing the immediate next interval expires the signal. One entry attempt
per signal; no simultaneous position in the same engine. A final-only CSV candle
cannot cause an intrabar entry. The adapter must provide forming updates and
acknowledge actual fills; the eventual candle cannot retroactively invalidate entry.

Entry window: 09:15 inclusive to 15:05 exclusive for F&O-member stocks, or 15:20
exclusive for non-F&O stocks. Membership is an explicit input, never inferred
from a name. Share quantity is floor(100000 / real entry reference price).

## 4. Exit conditions

Exit side: {opposite}. Fixed stop and fixed RR target always remain enabled.
Additional stop rule: `{cfg.stop_rule}`. Additional profit-taking rule:
`{cfg.target_rule}` (requires positive current gross price profit).
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

Partial preset: `{cfg.partial}`. `none` keeps all shares until a full exit.
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

Initial stop = {anchor} {cfg.sl_buffer:.2f} points. Risk R is the positive distance
from ACTUAL entry fill to this stop and stays fixed for the life of the trade.
No trade is permitted if risk is nonpositive. Additional stop rule is
`{cfg.stop_rule}`, evaluated as described above regardless of current profitability.

Trailing fraction: {cfg.trail_fraction:.0%}. Zero disables trailing. Otherwise
activate only after the best observed real price reaches +1R and configured RR
is at least 2. Trail distance = {cfg.trail_fraction:.0%} of the configured target
profit distance (RR times initial R). Long stop follows best price minus distance;
short stop follows best price plus distance. Clamp to breakeven on activation,
never loosen, and do not reset R after partial exits. Breakeven is before costs.

## 6. Target profit

Fixed target = actual fill {"+" if buy else "-"} {cfg.reward_risk:g} times initial R.
The gross reward:risk ratio is 1:{cfg.reward_risk:g}. Additional target rule:
`{cfg.target_rule}`. It may take profit earlier, as may the partial preset,
trailing stop or square-off. Costs/slippage are not assumed zero returns: this
package calculates no performance and makes no profitability claim.

See [the full contract](../../../README.md) for wording corrections, integration,
data assumptions and the combination generator. The original brief is
`{"strategy_buy_doc_.txt" if buy else "strategy_sell_doc.txt"}` in the repository root.
"""


def write_variant(cfg, output):
    folder = output / cfg.side / f"{cfg.timeframe_minutes}m"
    folder.mkdir(parents=True, exist_ok=True)
    code = folder / f"{cfg.name}.py"
    doc = code.with_suffix(".md")
    code.write_text(
        f'"""{cfg.name}\n\nSee the adjacent Markdown document for the complete rules.\n"""\n\n'
        "from strategies.ha_bb_vwap_v1 import Config, Strategy\n\n"
        f"CONFIG = Config(**{asdict(cfg)!r})\n\n\n"
        "def create_strategy(symbol: str, is_fo: bool) -> Strategy:\n"
        "    return Strategy(symbol=symbol, is_fo=is_fo, config=CONFIG)\n",
        encoding="utf-8",
    )
    doc.write_text(strategy_doc(cfg), encoding="utf-8")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Enumerate full Cartesian product")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, help="Number to materialize; required for --all")
    args = parser.parse_args()
    if args.offset < 0 or (args.limit is not None and args.limit < 1):
        parser.error("offset must be nonnegative; limit must be positive")
    if args.all and args.limit is None:
        parser.error(f"--all has {FULL_COUNT:,} variants; specify --limit explicitly")
    configs = iter_all() if args.all else listed_variants()
    output = PACKAGE / ("combinations" if args.all else "versions")
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / f"manifest_{args.offset}_{args.limit or 'listed'}.csv"
    count = 0
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["name", "code", "documentation", *asdict(Config())]
        )
        writer.writeheader()
        end = None if args.limit is None else args.offset + args.limit
        for cfg in islice(configs, args.offset, end):
            path = write_variant(cfg, output)
            writer.writerow(
                {
                    "name": cfg.name,
                    "code": str(path.relative_to(PACKAGE)),
                    "documentation": str(path.with_suffix(".md").relative_to(PACKAGE)),
                    **asdict(cfg),
                }
            )
            count += 1
    print(f"Created {count:,} separate Python files and {count:,} documents. Manifest: {manifest}")
    print(f"Full Cartesian definition count: {FULL_COUNT:,}. No strategy or backtest was run.")


if __name__ == "__main__":
    main()
