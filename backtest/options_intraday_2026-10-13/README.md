# NIFTY options intraday — October 13, 2026

[Open the offline report](results/index.html). [Summary CSV](results/summary.csv).
[Full methods and handoff](../../docs/plans/2026-10-13-options-intraday.md).

Six intraday variants only; no positional/equity results. Four completed cycles
per modeled path: one winner, three losers, 25% win rate. Two current-week variants
skipped entry under existing delta rules. OLHC net -₹49,359.13; OHLC net
-₹49,359.87. Results include estimated FYERS standard charges and adverse slippage.
₹20 lakh allocated separately per strategy. These are alternative simulations,
not actual trading results, tick paths, or guaranteed bounds.

948 option history requests: 382 nonempty, 566 provider no-data responses;
139,407 option candles and all 375 index candles retained. Zero missing held-price
minutes or open legs. Ledger checks, VectorBT reconciliation and browser report
checks passed. Raw source responses and SHA256 hashes are saved.

Reproduce offline from the repository root:

```sh
.venv/bin/python .development/options-intraday-20261013/run.py replay
node .development/options-intraday-20261013/verify_report.cjs
```

OpenAlgo was stopped with explicit user authorization and remains stopped.
All 28 schedules remain unchanged. No Reports database import or broker orders.
