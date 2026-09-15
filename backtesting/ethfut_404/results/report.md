# ETHFUT 404-strategy backtest

Completed: 404/404 versions; 518,675 supplied ETHUSD trades.
Period: 2024-04-01T00:03:51.567431+00:00 to 2024-05-31T23:59:05.143982+00:00.

24/7 entries and exits; positions carry through midnight. No daily square-off.
USD model: $100,000 fixed notional per version, 0.01 ETH increments, 0.05% fee per fill and 0.05% adverse slippage.
Net results are after modeled trading fees and slippage, BEFORE funding and tax. Rates and contract sizing are research assumptions, not verified historical broker terms.
UTC is assumed for naive input timestamps; VWAP resets at UTC midnight. Prices are actual supplied trades, not an invented OHLC path.
Continuous HA; at most 600 prior nonempty bars initialize forming OpenAlgo indicators. No missing candles or trades are fabricated.
Completed-bar orders execute at the next source trade; forming orders at the triggering trade plus slippage. Final open positions are liquidated at the last source trade.
Same-trade fills omit latency, spread, depth and participation constraints. Gaps can delay exit fills.
Coverage: 223 gaps >5 minutes; largest 103.91 minutes. No supplied 2025/2026 files.
All versions are independent fixed-notional opportunity tests, without compounding or a shared portfolio. USD is not INR. Margin, leverage, liquidation and funding histories are unavailable.
Daily Sharpe/Sortino use fixed-capital daily P&L / $100,000, 365-day annualization and zero risk-free rate. Drawdown uses every replay observation.

| Group | Version | Net USD | Return | Max DD USD | Trades | Win rate |
|---|---|---:|---:|---:|---:|---:|
| buy 1m | S029 | -6,788.67 | -6.79% | 38,126.33 | 155 | 3.23% |
| buy 5m | S104 | 12,030.83 | 12.03% | 22,530.45 | 95 | 11.58% |
| sell 1m | S232 | -2,833.53 | -2.83% | 31,997.54 | 39 | 7.69% |
| sell 5m | S344 | 3,523.78 | 3.52% | 25,705.18 | 45 | 8.89% |

ETH buy-and-hold: net $3,069.48, return 3.07%, max drawdown $25,223.66.
Profitable versions after modeled costs: 25/404.
Ranks are retrospective across these two months; this is not an out-of-sample strategy selection test. Ties remain in rankings.csv.
See index.html for searchable rankings, all-version equity curves and individual fill/trade/daily CSVs.