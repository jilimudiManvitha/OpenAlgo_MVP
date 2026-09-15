# Strategy comparison: 11 September 2026

Completed 404 existing versions on 22 supplied stocks, using two assumed intraminute paths: 8,888 strategy-stock-path runs, 20,783 round trips, and 20,783 individual full-session red/green candlestick charts. Buy versions use the 11 gainers; sell versions use the 11 losers. All positions were closed at their configured square-off.

## Best observed in each group

Net figures include 0.05% adverse slippage per fill, adverse tick rounding and estimated Zerodha NSE intraday fees. Each stock has Rs 100,000 per-trade allocation; basket return uses Rs 1,100,000. Rank is highest lower-path net P&L, not a mathematical worst case.

| Group | Version | RR | Net range Rs | Trades L/H | Win rate on lower-profit path | Largest bar-close drawdown Rs | Lower-path basket return |
|---|---|---:|---:|---:|---:|---:|---:|
| buy 1m | [S092](strategies/S092.html) | 6.5 | 57,718.69–58,489.59 | 27/27 | 44.4% | 12,908.60 | 5.25% |
| buy 5m | [S109](strategies/S109.html) | 13 | 43,439.56–43,559.62 | 9/9 | 77.8% | 4,660.67 | 3.95% |
| sell 1m | [S299](strategies/S299.html) | 9 | 14,272.30–14,491.07 | 18/17 | 58.8% | 5,650.60 | 1.30% |
| sell 5m | [S305](strategies/S305.html) | 10 | 7,181.03–7,182.24 | 13/13 | 69.2% | 7,223.04 | 0.65% |

All four displayed leaders use a Rs 0.10 price-unit stop buffer, no trailing stop, no partial exits, and no additional indicator exit. Their existing entry rules are HA + Bollinger + VWAP. These are independently tested portfolios; do not sum their profits as if the same capital funded all versions simultaneously.

## Which performed best, and why

**Highest observed net profit: buy 1m S092, RR 6.5.** It retained larger winners instead of repeatedly taking 2R exits. On its lower-profit OHLC path, eight fixed-target trades contributed Rs 64,053.22 and six square-off trades Rs 11,347.82; thirteen stop-loss trades cost Rs 17,682.35. Net was Rs 57,718.69 versus Rs 23,583.30 for the default 2R version's lower path. It made 27 trades per path versus the default's 55/58, reducing repeat turnover. Its 44.4% win rate shows that payoff size, rather than a high hit rate, drove the result. Eight stocks were profitable; FILATEX and PINELABS contributed Rs 32,577.03, or 56.4% of net profit. This is substantial concentration.

**Lower observed drawdown among the group leaders: buy 5m S109, RR 13.** Nine trades yielded Rs 43,439.56 on its lower path, with a largest bar-close drawdown of Rs 4,660.67 across paths, versus Rs 12,908.60 for S092. The net-to-drawdown ratio was about 9.32 versus 4.47, but this is only a descriptive one-day ratio. Seven trades exited at square-off, one hit its fixed target and one hit its stop. The single target winner was QUADFUTURE; QUADFUTURE and PINELABS supplied about 64.5% of net profit. Thus 13R mostly allowed positions to remain open; it did not deliver nine 13R winners. It beat the default 5m 2R lower-path result of Rs 35,076.37, while having a higher drawdown than that default (Rs 3,918.83).

**Best observed sell result: sell 1m S299, RR 9.** Net was Rs 14,272.30–14,491.07 with 17/18 trades, compared with the default's lower-path Rs 8,530.53. On the lower path, two targets and ten square-offs outweighed five stops. Nine stocks were profitable; COCHINSHIP and AFCONS provided about 63.6% of net. Its drawdown of Rs 5,650.60 was higher than the default's Rs 5,233.38: the profit improvement was not free of additional observed risk.

**Sell 5m has a tie, not a unique optimum.** S305 (RR 10) is just the first report ID among 26 tied fixed-RR variants, RR 8–20.5 in 0.5 steps. All produced the same Rs 7,181.03–7,182.24 net and 13 trades per path. No fixed target was hit: eleven trades square-off and two stop-loss exits made the RR values indistinguishable on this day. COCHINSHIP alone contributed about 68.3% of lower-path net. Drawdown of Rs 7,223.04 slightly exceeded the lower-path net profit, making this a weaker observed trade-off than the leading buy results.

The comparison supports S092 for the highest profit on this sample and S109 for a lower-drawdown alternative among the group winners. It does not establish either as a deployable or generally best strategy. Only 9–27 trades on a single session underpin these examples; performance on unseen days and a universe selected without hindsight remains untested.

## Benchmark and selection effects

The same-direction open-to-cutoff basket reference earned Rs 92,411.65 for the gainers and Rs 28,294.71 for the losers, after the same modeled cost rates. **None of the four group leaders beat its own basket reference.** This comparison uses a hindsight-selected universe and a slightly different cutoff reference convention, so it is a descriptive reference, not a tradable selection system or exact alpha estimate. NIFTY data was unavailable.

Profitable under both tested paths: buy 1m 96/101, buy 5m 101/101, sell 1m 85/101 and sell 5m 93/101. These high counts on preselected gainers/losers cannot establish an edge. Picking the best of 101 versions per group on the same test day adds parameter-selection bias.

## Data and execution limits

OHLC minute bars do not reveal tick order. The two scenarios traverse O-L-H-C and O-H-L-C in three linear steps per leg, with uniform volume accrual. They are synthetic observations, not actual ticks or exhaustive bounds. Actual fills, different paths or step sizes, spreads, circuit limits and market impact can materially change these profits.

The 44 CSVs contain 4,107 buy 1m, 822 buy 5m, 4,125 sell 1m and 825 sell 5m target-day rows. ASHOKAMET has 358/72 bars, KIRLOSIND has 374 one-minute bars. Five-minute reaggregations matched all overlapping supplied 5m candles. ASHOKAMET, DIGJAMLMTD and LADDERUP have no earlier warmup history. Their indicator initialization is less comparable to seasoned symbols. LADDERUP generated no trades in any version/path.

There are many flat/zero-volume bars, including ASHOKAMET (136 one-minute bars) and LADDERUP (296). The model prevents new entries on zero-volume minutes but does not constrain participation or prove that exits could execute. Many source prices remain flat for extended periods; price-circuit or liquidity constraints are not reconstructed. Treat the ASHOKAMET result and other thin-stock trades especially cautiously. Master tick sizes and F&O membership are the adjacent-date local snapshot.

Annualized Sharpe, Sortino and CAGR are not reported for one session. Full-session plots use completed HA bars as context and real prices for fills; exact modeled fill timestamps are in the tables. Candle-start times end at 15:29/15:25, with the chart axis extending through 15:30. Missing candles stay gaps.

## Files and verification

[Open all 404 reports and every trade chart](index.html). [All trades CSV](all_trades.csv), [all fill CSV](all_fills.csv), [comparison CSV](strategy_summary.csv), [per-path metrics](strategy_path_metrics.csv), [per-stock metrics](strategy_stock_metrics.csv), [methodology](methodology.md), [input audit](data_audit.json).

All 8,888 fill ledgers were independently reconciled in VectorBT. The strategy/replay suite passed 63 synthetic tests. Additional file-level and browser validation are recorded in verification.json and browser-verification.json. Browser checks sample both directions/timeframes/paths and partial/indicator exits; file checks cover every trade page.
