# ATHERENERG: volume filter disabled

The supplied Heikin Ashi CSV supplies signal OHLC. Matching real OHLC supplies VWAP,
entry fills and stop/target checks. The HA file is validated against its real source.
Only RVOL eligibility is disabled. The first 19 candles still warm up BB(20, 2).

Entry: bullish HA candle with no lower wick makes a fresh HA high cross above the upper BB,
and its HA high exceeds VWAP. A fresh cross means the prior HA high was at or
below its upper BB. The immediate next bullish, wickless HA candle must close above the signal high;
its HA high must exceed the upper BB and VWAP, and its real close must exceed VWAP.
Buy the following real candle's open plus slippage. Conditions are evaluated on completed bars.
Stop: signal HA low rounded down. Target: entry + 2*(entry-stop), rounded up.
Exit at stop/target, or at the 15:20 real open; stop takes priority if both levels touch in one bar.
No trailing stop. Entry window ends at 15:00. At most three trades daily.

Assumptions: INR 10,000 capital, 0.5% risk budget (INR 50), integer shares, no leverage,
5 bps fees per side and 5 bps adverse slippage, tick rounding INR 0.01, all from the strategy defaults.
The planned 1:2 ratio excludes costs. Actual loss can exceed 1R after costs and stop slippage.

```
              signal_time         confirmation_time                entry_time   entry    stop  target  quantity                 exit_time    exit reason  gross_pnl   costs  net_pnl
2026-06-29 10:55:00+05:30 2026-06-29 11:00:00+05:30 2026-06-29 11:05:00+05:30 1029.27 1018.62 1050.57         4 2026-06-29 13:15:00+05:30 1050.57 target       85.2 4.15968 81.04032
```

Net P&L: INR 81.04; final equity: INR 10081.04;
return: 0.8104%; sampled bar-close drawdown: 0.1985%.
Signal/confirmation labels identify bar opens; their conditions are known five minutes later.
Intrabar exit timestamps identify the five-minute interval, not the exact second.
This single-session sample does not establish strategy performance.

Open trade_chart.html for the interactive full-session chart or trade_chart.png for the trade close-up.
