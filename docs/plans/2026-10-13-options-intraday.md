# October 13 options intraday backtest

User request: “backtest only options intraday strategies on today”. Today is
2026-10-13 in Asia/Kolkata; request handled after the completed NSE session.

## Scope and isolation

- Six existing NIFTY intraday variants: Iron Condor, Delta, Premium, each current
  and next expiry. No positional or equity replay.
- Existing 09:30 entry / 15:20 exit / same-expiry 200-point wings / ₹20 lakh per
  strategy / ₹20,000 loss threshold. Existing modeled sizing, Black-76 Greeks,
  FYERS standard estimated charges and ₹0.05 adverse slippage retained.
- Both OLHC and OHLC modeled candle paths; alternatives, never added together.
- Running OpenAlgo is left untouched. No order API, Reports writes, production
  DB writes, source deployment, schedule mutation, build, commit or push.
- Private read-only-source authentication/master/calendar snapshot under
  `log/test/options-intraday-20261013/private`; source and result files under
  `backtest/options_intraday_2026-10-13` per current user instructions.
- Annual and previous-quarter collection remain stopped; this request does not
  authorize restarting either.

## Completed result

All 948 contract histories were collected; 382 returned candles and 566 returned
no data. There are 139,407 option candles; 256 contracts have all 385 minutes.
All 375 index minutes are present. Both paths completed with zero held-price gaps,
zero unavailable held-Greek minutes, and zero open legs. No synthetic prices.

| Intraday strategy | OLHC net INR | OHLC net INR |
|---|---:|---:|
| Iron Condor current | 0.00 (skipped) | 0.00 (skipped) |
| Iron Condor next | -20,992.23 | -21,089.53 |
| Delta current | 0.00 (skipped) | 0.00 (skipped) |
| Delta next | -21,096.27 | -21,096.24 |
| Premium current | -20,474.78 | -20,475.57 |
| Premium next | 13,204.15 | 13,301.47 |
| **Combined** | **-49,359.13** | **-49,359.87** |

Each path: four completed cycles, one win, three losses, zero breakeven, 25% win
rate; 16 closed legs. Separate ₹20 lakh allocation per strategy (₹1.2 crore total).
Costs are ₹3,875.38 / ₹3,876.12. NIFTY gross minute-close return was +1.7956%.
These are alternate modeled paths, not actual trades or additive results.

Current Iron Condor failed the short delta-match tolerance; current Delta failed
hedged basket neutrality. They correctly skipped initial entry. Next Condor and
Delta hit capital stops. Both Premium variants stopped one spread; current later
hit its capital stop and next retained its surviving spread until 15:20.

All 32 closed-leg rows across 12 scenarios passed VectorBT and cash-flow/fees/
whole-lot/source/link reconciliation; 1,898 source files hashed. Browser validation
passed desktop/mobile layouts, chart traces, displayed P&L and offline loading.
The first report run exposed a forward link to a verification file before it
existed; the link was removed and the final replay/report checks passed.

**OpenAlgo remains stopped by explicit user instruction.** The user approved
stopping it for this backtest and leaving it stopped. Fresh process inspection
confirmed graceful exit of app, wrappers and baseline-fetch child; ports 5000 and
8765 no longer accept connections. All 28 schedules and their file hash are
unchanged (`preservation_before.json`, `preservation_after.json`). No orders,
production data edits, frontend build, Git commit or push. Annual/quarter jobs
were not resumed. Do not restart OpenAlgo.

The runner's DB snapshot connections use context-manager cleanup, ORM sessions
have `finally: remove()`, and HTTP uses the shared bounded client with final
cleanup. Static resource review only; no long-running leak benchmark claimed.

## Commands

```sh
.venv/bin/python .development/options-intraday-20261013/run.py probe
.venv/bin/python .development/options-intraday-20261013/run.py fetch
.venv/bin/python .development/options-intraday-20261013/run.py replay
```

`all` runs fetch then replay. Validated cached candles resume without duplicate
broker calls. Do not run multiple collectors concurrently. The replay limits
the existing engine's profile mapping within the isolated Python process only;
the production package is not edited.

Final output: `backtest/options_intraday_2026-10-13/results/index.html`,
summary CSV/JSON, all trade/equity CSVs, source hashes and ledger reconciliation.
Final results require both paths to complete, no open intraday legs, and
successful cash-flow/fee/lot-size/source reconciliation. Missing or malformed
data must not be replaced with synthetic prices. One session does not support
meaningful annualized Sharpe/Sortino or conclusions about long-run performance.
