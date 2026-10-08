# NIFTY options: July 8–October 7, 2026

[Open the single offline HTML report](../../options_3months_2026-10-07.html)

All 12 current strategies, including 200-point same-expiry protection, were replayed over 64 trading sessions. The prior July 3–October 1 unhedged report is preserved separately.

## Overall results

| Metric | OLHC | OHLC |
|---|---:|---:|
| Allocated capital ₹ | 24,000,000.00 | 24,000,000.00 |
| Gross P&L ₹ | 1,169,743.25 | 1,172,912.00 |
| Estimated charges ₹ | 381,220.59 | 381,156.51 |
| Net P&L ₹ | 788,522.66 | 791,755.49 |
| Realized P&L ₹ | 743,675.91 | 746,908.74 |
| Open-position P&L ₹ | 44,846.75 | 44,846.75 |
| Winning-cycle profit ₹ | 3,861,575.33 | 3,864,484.66 |
| Losing-cycle loss ₹ | 3,098,486.71 | 3,098,065.90 |
| Closed strategy cycles | 434.00 | 434.00 |
| Winning cycles | 252.00 | 252.00 |
| Losing cycles | 182.00 | 182.00 |
| Open cycles | 4.00 | 4.00 |
| Combined observed-minute max drawdown ₹ | -545,928.08 | -545,377.29 |

## Per strategy

| Strategy | Net OLHC ₹ | Net OHLC ₹ | OLHC charges ₹ | Closed cycles | Wins / losses |
|---|---:|---:|---:|---:|---:|
| iron condor intraday current week | 15,462.84 | 15,587.90 | 51,405.91 | 61 | 32 / 29 |
| iron condor intraday next week | 36,622.85 | 36,539.70 | 59,944.40 | 64 | 44 / 20 |
| iron condor positional current week | 3,364.26 | 3,359.11 | 4,562.49 | 13 | 7 / 6 |
| iron condor positional next week | 27,057.98 | 27,155.29 | 2,240.77 | 7 | 5 / 2 |
| delta intraday current week | 108,280.11 | 108,480.41 | 48,197.64 | 58 | 33 / 25 |
| delta intraday next week | 28,352.48 | 28,716.43 | 85,264.27 | 63 | 44 / 19 |
| delta positional current week | 136,087.82 | 135,998.64 | 6,674.93 | 12 | 5 / 7 |
| delta positional next week | 36,337.38 | 36,159.32 | 3,891.12 | 7 | 3 / 4 |
| premium intraday current week | 213,037.73 | 213,029.51 | 50,465.77 | 64 | 31 / 33 |
| premium intraday next week | -35,470.93 | -35,840.43 | 56,472.43 | 64 | 33 / 31 |
| premium positional current week | 103,338.85 | 106,434.01 | 8,607.40 | 15 | 10 / 5 |
| premium positional next week | 116,051.29 | 116,135.60 | 3,493.46 | 6 | 5 / 1 |

## Method and limits

- ₹20 lakh is allocated independently to each strategy: ₹2.4 crore total. Aggregate P&L is the sum of separate simulations; this is not a shared-account margin/netting test.
- OLHC and OHLC are alternative one-minute price paths, not observed tick sequences or guaranteed performance bounds. Never sum their results. Both include ₹0.05 adverse slippage before tick rounding.
- FYERS standard retail brokerage and execution-date statutory charges are applied on each modeled leg order. The report separates brokerage, STT, exchange, SEBI, stamp duty, IPFT, clearing and GST. Per-order rounding can differ from a broker contract note.
- Net P&L includes ₹44,846.75 marked open-position P&L in each path. Four strategy cycles (12 legs) remain open at the end; no artificial final liquidation is used.
- Cycle counts treat an entire basket, including adjustments, as one trade. Each path has 434 closed cycles, 252 wins and 182 losses; 1,760 closed option legs. Contract tables group those legs by symbol.
- Margin and Black-76 deltas are historical estimates; historical broker SPAN, queue position, partial fills and actual exchange latency are unavailable. Peak margin is measured at entries and excludes the 10% reserve.
- Across the strategies, each path recorded 13 missing held-basket minute observations, 14 unavailable-Greek minutes and 145 skipped entry/re-entry observations (not necessarily distinct days). Missing prices were not invented. A held gap over five consecutive minutes or a missing final held mark aborts the replay.
- Current hedged strategy rules are applied across the period; these results are hypothetical, not historical account returns.

## Verification

All 24 strategy/path ledgers reconcile; VectorBT independently reconciles cash flows. Checked 3,520 closed-leg rows, 7,071 source hashes and 98 local links. Gross less charges equals net; charge components sum to fees; outcome counts and monthly P&L reconcile. See `results/ledger_verification.json`, `results/combined_dashboard_verification.json` and `results/overall_summary.json`.

Sources: [FYERS charges](https://fyers.in/charges-list), [STT revision](https://fyers.in/notice-board/revision-in-securities-transaction-tax-stt-effective-april-01-2026). The report works offline; these reference links are optional.
