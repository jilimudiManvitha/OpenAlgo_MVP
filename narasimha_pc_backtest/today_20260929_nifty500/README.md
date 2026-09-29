# September 29, 2026 — Nifty 500 volume-shocker and top-gainer backtest

Same strategy, same engine, same cost model and same independent verifier as the
September 25 and September 28 runs. The only change is the **universe**: the
selection is restricted to `Stock_Symbols/ind_nifty500list.csv` instead of the
scanner's all-EQ list. No strategy, indicator, sizing, cutoff or ledger code was
modified. Nothing was overwritten: output lives in this folder and candles in
`db/scanner_backtest_cache/2026-09-29-nifty500/`.

## Universe and selection

| | |
|---|---|
| Universe file | `Stock_Symbols/ind_nifty500list.csv`, 500 symbols |
| Source | Completed local FYERS scanner snapshot, frozen **16:35:20 IST** |
| Snapshot | 2,671 valid quotes of 2,678 instruments |
| Nifty 500 rows present | **497 of 500** |
| Absent from the broker master contract | `HEG`, `HFCL`, `JBCHEPHARM` |
| Nifty 500 candidates — volume shockers (rvol > 1, positive) | 102 |
| Nifty 500 candidates — top gainers (positive) | 137 |
| Selected per group | 50 + 50 |
| Unique after dedupe | **75** (25 in both groups, 25 shocker-only, 25 gainer-only) |

Selection uses the application's own `rank_rows` and `validate_options` with
`limit=50, positive_only=True`, so ranking and tie-breaks are identical to the
live scanner. Frozen once into `selection.json`; `selection_table.csv` has the
per-symbol LTP, change, volume, average volume and rvol.

## Coverage

75 of 75 sessions eligible, **0 missing minutes** through square-off, 0 rejected
source rows affecting eligibility. 30 calendar days of FYERS one-minute candles
were downloaded per symbol (7,882 candles each) for indicator warmup; only
September 29 trades are evaluated.

## Results (₹1,00,000 per trade, one trade per stock per day)

Engine cost model unchanged: HA1m signal, BB20x2, raw session VWAP, forming
entry on the next minute, stop at signal HA low − ₹0.10, target 3R, 5 bps market
slippage and 5 bps fees per fill, whole shares, no portfolio capital cap.

| Basket | Selected | Eligible | Trades/path | Winners | Net P&L (OLHC) | Net P&L (OHLC) |
|---|---:|---:|---:|---:|---:|---:|
| Volume shockers | 50 | 50 | 50 | 18 | **−2,191.91** | −2,235.82 |
| Top gainers | 50 | 50 | 50 | 22 | **+10,036.24** | +10,134.75 |
| Deduplicated union | 75 | 75 | 75 | 27 | **−1,654.87** | −3,670.04 |

**Never add the two group rows or the overlapping totals** — the 25 symbols in
both groups are counted twice.

Union, OLHC path:

| Metric | Value |
|---|---:|
| Trades / winners | 75 / 27 |
| Win rate | 36.00% |
| Gross P&L | ₹5,712.61 |
| Estimated fees | ₹7,367.48 |
| **Net P&L** | **−₹1,654.87** |
| Profit factor | 0.955 |
| Best trade | +₹2,611.24 (TECHNOE) |
| Worst trade | −₹2,503.70 (ACUTAAS) |
| Peak simultaneous entry notional | ₹25,48,741.04 |
| Mean entry notional | ₹98,195 |

Exit reasons: **48 stop-outs, 23 targets, 4 square-offs.** A 31% target hit rate.

### Where the money was made and lost

| Group | Symbols | Trades | Winners | Gross | Fees | Net (OLHC) |
|---|---:|---:|---:|---:|---:|---:|
| In both groups | 25 | 25 | 13 | 11,945.95 | 2,446.75 | **+9,499.20** |
| Gainer only | 25 | 25 | 9 | 3,011.94 | 2,474.90 | +537.04 |
| Shocker only | 25 | 25 | 5 | −9,245.28 | 2,445.83 | **−11,691.11** |

The entire loss is concentrated in **volume shockers that were not also top
gainers** — 5 winners out of 25, gross already negative before fees. The stocks
that appeared in both groups carried the session. This is the same "stronger
confirmation wins" pattern the September 28 run showed, in the same direction,
but the day's overall result is negative.

## Verification

`output/verification.json` — **PASSED**, 150 trades checked (75 symbols × 2
paths). Re-derives signal conditions, next-minute entry, forming-candle HA
wick/BB/VWAP geometry, tick-rounded fills, 3R target, exit price range and
cutoff, fees, slippage, P&L, per-day totals and the source SHA-256 from the
saved candles — independently of the engine that produced them.

Engine tests: `uv run python -m pytest narasimha_pc_backtest/test_engine.py`
was not re-run for this universe filter; the filter touches selection only.

## Interpretation and limits

- **This is a retrospective basket, not a causal scanner backtest.** The basket
  was frozen at 16:35 after the close, so stocks that qualified only in the last
  hour were selected using entry times that had already passed them. Winners are
  selected partly because they already won. This inflates the result relative to
  a genuine live run — and today it still came out **negative**.
- **One session.** The September 25 all-EQ run returned +₹1,46,175 and the
  September 28 run +₹73,587; today returned −₹1,655. One day neither validates
  nor invalidates the strategy. It does not overturn the earlier negative
  five-year Nifty study.
- **Fees exceed gross profit** (₹7,367 vs ₹5,713) at ₹1 lakh per trade. The
  strategy needs a materially higher target hit rate than 31% to clear its own
  modelled costs at this size.
- **The engine still squares off at 15:20 for non-F&O stocks** (`run.py:119`,
  `cutoff = 905 if is_fo else 920`). The forward paper test moved to 15:05 for all
  stocks on September 29. This run therefore uses the older cutoff, and the
  engine was deliberately left unchanged. Re-running with a 15:05 cutoff is a
  separate, explicitly-requested change.
- 1-minute OHLC paths approximate tick data. Slippage and fees are illustrative
  flat 5 bps, not actual brokerage and statutory charges. Drawdown is realized
  exits only; intratrade drawdown and margin are not modelled. This is not a
  funded-account simulation and peak notional is not margin required.
- No annualized Sharpe, CAGR or QuantStats figure is derived from a one-day
  returns series.

## Reproduce

```powershell
.\.venv\Scripts\python.exe narasimha_pc_backtest\today_20260929_nifty500\run_nifty500.py
```

Read-only against `db/market_scanner_live.db` and the broker history API. The
selection freezes on first run and the candle cache resumes, so re-running is
idempotent. Sends no orders. Requires `numba` in the project venv (installed for
this run; it is listed in `narasimha_pc_backtest/requirements.txt`).

## Outputs

| File | Contents |
|---|---|
| `selection.json` | Frozen basket, snapshot provenance, universe coverage, the three exclusions |
| `selection_table.csv` | Per-symbol LTP, change %, volume, 5-day average volume, rvol, group flags |
| `result.json` | Full result including every trade, coverage row and audit row |
| `output/trades.csv` | 150 rows — 75 symbols × OLHC/OHLC |
| `output/coverage.csv` | Per-symbol session eligibility and missing minutes |
| `output/verification.json` | Independent verifier result |
| `output/audit.csv` | Per-symbol row counts, hashes, timing |
| `output/candles/*.parquet` | Per-symbol candles with HA/BB/VWAP and eligibility flag |
| `candles.duckdb` | Frozen source, SHA-256 recorded in the manifest |
