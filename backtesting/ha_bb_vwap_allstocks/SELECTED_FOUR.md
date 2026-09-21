# Four selected strategies: full DuckDB history

**Status: stopped at the user's request on September 15, 2026.** No full
historical day completed. Output and logs are preserved. Do not restart
without a new user request; commands below are for future reference.

Selection fixed on 15 September 2026 from the September 11 comparison:

| Group | Version | Reward/risk |
|---|---|---|
| Buy 1min | S092 | 6.5R |
| Buy 5min | S109 | 13R |
| Sell 1min | S299 | 9R |
| Sell 5min | S305 | 10R |

S305 represents the 26 tied sell-5min versions; their September 11 tie does
not imply equivalence across history. No answer to the optional selection
questions arrived before launch, so all source stocks and S305 were used.

Read-only source inspection found 1,576 NSE stocks and 859,729,779 minute
rows, spanning 2017-07-03 through 2026-09-11. The new configuration includes
the final source date, unlike the older 404-strategy run. All four strategies
test every source stock; the original 22-stock gainers/losers baskets are
not applied to past dates. September 11 is the selection day and is included;
this is a retrospective robustness comparison, not prospective validation.

The unchanged strategy factories, Rs 100,000 whole-share entry cap, 0.10 stop
buffer, no trailing/partial/indicator exit, both OLHC/OHLC modeled paths,
600-bar warmup, 5 bps adverse slippage and existing itemized research fee
assumptions are retained. Each strategy/path is independent. See the
[main guide](README.md) for execution, metadata, coverage, capital and cost
limitations. Intraday exchange hours and square-off rules remain in force.

## Commands (PowerShell, repository root)

```powershell
# Start once. Do not run while a selected-four writer is active.
& backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks.run_selected_four

# Resume only after the previous writer has stopped.
& backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks.run_selected_four --resume

# View committed results in a separate terminal at http://127.0.0.1:8778
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks serve --config backtesting/ha_bb_vwap_allstocks/selected_four.json --port 8778

# Inspect completion without starting another backtest.
& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks.comparison --output backtesting/ha_bb_vwap_allstocks/selected_four_output
```

Results are isolated in `selected_four_output/`. The wrapper automatically
generates `comparison/index.html`, `findings.md` and ranking/path/year CSVs
only after all days finish. The September 15 background launch writes
`selected_four_output/run.log` and `run.err.log`; `process.json` records its PID.
Daily commits are resumable; interruption replays the uncommitted day.
This remains a large serial historical replay. Starting it does not mean
completion; no completion time or profitability is promised.
