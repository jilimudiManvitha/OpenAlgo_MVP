# September 11, 2026 — all materialized HA/BB/VWAP V1 versions

Start with [results/index.html](results/index.html) or [written findings](results/findings.html). There are 404 strategy reports and 20,783 individual full-session trade charts. Everything works offline; keep `assets`, `strategies` and `trades` beside `index.html`.

The follow-up [capital/risk report](results/capital_overview.html) adds brokerage separately from taxes/other charges, total entry notional and turnover, allocated and peak simultaneous capital, biggest winning/losing trade, session MTM extrema, drawdown peak/trough times and maximum concurrent trades. Each strategy has a time picker showing open trades, stocks, remaining quantities and entry notional at any chosen session time. `capital_report.py` derives these from the frozen fills and retained bar-close checkpoint marks; it does not rerun or change the strategy.

This is the specifically requested 11-gainer/11-loser, 1m/5m CSV comparison. The actual losing-stock folder is spelled `LoosersOn11092026`. Existing strategy factories are imported from `strategies/ha_bb_vwap_v1/versions`; their rules are preserved. No broker calls or live orders are involved.

OHLC cannot recover true ticks. The runner uses two explicitly synthetic minute paths with linear intermediate prices and assumed uniform volume. Read [methodology](results/methodology.md) before interpreting profit. Rankings on one hindsight-selected day do not establish out-of-sample performance.

Run from `D:\Personal\openalgo`, with the existing Python 3.13 backtesting environment (OpenAlgo, VectorBT, NumPy, pandas, Polars and Plotly):

```powershell
# Completed stocks resume from local checkpoints; three processes bound concurrency.
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/batch.py

# Rebuild presentation without replaying:
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/run.py --report-only
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/findings.py
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/capital_report.py

# Verification:
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/verify.py
& backtesting/.venv/Scripts/python.exe -m pytest backtesting/ha_bb_vwap_v1_20260911/test_replay.py strategies/ha_bb_vwap_v1/tests -q --confcutdir=backtesting/ha_bb_vwap_v1_20260911 -o addopts= -p no:cacheprovider
node backtesting/ha_bb_vwap_v1_20260911/verify_browser.cjs
node backtesting/ha_bb_vwap_v1_20260911/verify_capital_browser.cjs
```

The browser checker uses the existing `frontend/node_modules/@playwright/test` and installed Chrome in headless mode. It checks representative charts across both directions, timeframes, paths and partial/indicator exits. The Python verifier checks every ledger and trade-page asset link plus all 44 source hashes.

`replay.py` builds causal indicator observations and acknowledges modeled real-price fills through the original strategy engine. `run.py` independently reconciles accounting in VectorBT and generates CSVs/checkpoints. `report.py` creates shared offline charts. `findings.py` adds detailed interpretations of this fixed run; its narrative is specific to September 11 and must be rewritten after any new experiment.

Checkpoints contain trusted local Python pickle data and should only be loaded from this run. The engine/harness fingerprint rejects code changes. Source hashes are validated by `verify.py`; input, metadata or strategy-definition changes require a separate run/output directory. Do not reuse these checkpoints for another experiment. `results/smoke` preserves the initial PINELABS trial before formatting changes; it is excluded from final counts and the report package.

Final files: `strategy_summary.csv` (404 rows), `strategy_path_metrics.csv` (808), `strategy_stock_metrics.csv` (8,888), `all_trades.csv` (20,783), `all_fills.csv` (41,802), source/settings audits and verification JSON. Quantities are whole shares with up to Rs 100,000 actual entry notional per stock/trade; results use Rs 1,100,000 per basket. Fees/slippage and capital conventions are stated in the methodology.

Additional files: `capital_risk_metrics.csv` (808 strategy/path rows), `capital_trade_timeline.csv` (37,993 event/boundary states), `portfolio_mtm_timeline.csv` (182,608 completed-bar/boundary observations), and `brokerage_breakdown.csv` (41,802 fills). Event states apply after all fills at a timestamp; exits precede new entries when timestamps match. Between fills, open count and remaining entry notional are constant. MTM at a selected time is the latest completed-bar observation, not fresh intrabar valuation. Capital is gross entry notional, including shorts, and does not estimate broker margin. Reused cumulative entry notional is not capital needed simultaneously. All original fees, peak capital and drawdown values reconcile. Three additional focused tests cover partial releases, simultaneous exit/entry, initial-loss drawdown and empty trading; 40 browser time lookups passed.
