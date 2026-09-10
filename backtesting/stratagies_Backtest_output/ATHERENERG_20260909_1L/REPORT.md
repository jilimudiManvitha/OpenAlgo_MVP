# ATHERENERG P&L

2025-05-07 to 2026-09-08 | 334 complete sessions | 25,050 bars

| Metric                                | Result                 |
|:--------------------------------------|:-----------------------|
| Starting capital                      | INR 100,000.00         |
| Gross P&L (slippage already in fills) | INR -3,203.43          |
| Modeled fees                          | INR 3,059.29           |
| Net P&L                               | INR -6,262.72          |
| Ending capital                        | INR 93,737.28          |
| Return                                | -6.26%                 |
| Trades / wins / losses                | 73 / 21 / 52           |
| Trade win rate                        | 28.77%                 |
| Trade profit factor                   | 0.587                  |
| Maximum sampled drawdown              | 8.68% / INR 8,904.37   |
| Average net P&L per trade             | INR -85.79             |
| Best / worst trade                    | INR 1,435.57 / -512.21 |
| Daily Sharpe / Sortino (rf=0)         | -1.498 / -2.327        |

- Latest saved strategy: HA high breakout, BB(20,2), real-price VWAP; RVOL disabled.
- Confirmation on the next completed HA bar; buy the following real bar open.
- Initial signal HA-low stop; exit below prior completed BB middle; square off at 15:20.
- Whole shares, no leverage, 0.5% of current equity risk per trade (initially INR 500); max 3/day.
- Fees: 0.05% per side; adverse slippage: 0.05%; tick assumption INR 0.01.
- These are existing illustrative cost assumptions, not a verified brokerage/tax schedule.
- Only complete regular sessions used. No missing bars filled and no parameter optimization.
- Excluded: 2025-05-06 (71 bars), 2025-10-21 (13 bars), 2026-09-09 (19 bars).
- Latest CSV ends 2026-09-09 10:45; today's unfinished session is excluded.
- OpenStatz win rate/profit factor use daily returns; P&L report uses individual trades.
- OpenStatz drawdown uses day-end equity; main report samples every 5-minute close.
- Reference: same CSV ATHERENERG buy-and-hold before costs; NIFTY data not supplied.
- Corporate-action adjustment status is unverified. Results use the supplied prices as-is.