# ATHERENERG: volume filter disabled

The supplied Heikin Ashi CSV supplies signal OHLC. Matching real OHLC supplies VWAP,
entry fills and stop/target checks. The HA file is validated against its real source.
Only RVOL eligibility is disabled. The first 19 candles still warm up BB(20, 2).

Entry: bullish HA candle with no lower wick makes a fresh close above the upper BB and VWAP;
the immediate next bullish, wickless HA candle must close above the signal high, upper BB and VWAP,
and its real close must exceed VWAP. Buy the following real candle's open plus slippage.
Stop: signal HA low rounded down. Target: entry + 2*(entry-stop), rounded up.
Exit at stop/target, or at the 15:20 real open; stop takes priority if both levels touch in one bar.
No trailing stop. Entry window ends at 15:00. At most three trades daily.

Assumptions: INR 10,000 capital, 0.5% risk budget (INR 50), integer shares, no leverage,
5 bps fees per side and 5 bps adverse slippage, tick rounding INR 0.01, all from the strategy defaults.
The planned 1:2 ratio excludes costs. Actual loss can exceed 1R after costs and stop slippage.

```
              signal_time         confirmation_time                entry_time   entry    stop  target  quantity                 exit_time    exit reason  gross_pnl   costs   net_pnl
2026-06-29 14:15:00+05:30 2026-06-29 14:20:00+05:30 2026-06-29 14:25:00+05:30 1068.64 1058.55 1088.82         4 2026-06-29 14:45:00+05:30 1058.02   stop     -42.48 4.25332 -46.73332
```

Net P&L: INR -46.73; final equity: INR 9953.27;
return: -0.4673%; sampled bar-close drawdown: 0.7586%.
Signal/confirmation labels identify bar opens: the 14:15 signal is known at 14:20;
the 14:20 confirmation is known at 14:25. Stop exit falls within 14:45-14:50;
five-minute OHLC does not identify the exact second. One trade does not establish strategy performance.

Open trade_chart.html for the interactive full-session chart or trade_chart.png for the trade close-up.
