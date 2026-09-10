# CSV backtest reports

Run from the repository root using `backtesting/.venv/Scripts/python.exe`.
The existing environment supplies pandas, NumPy, matplotlib, Plotly and OpenStatz.
Install the added dependency with:

```powershell
uv pip install --python backtesting\.venv\Scripts\python.exe -r backtesting\ha_bb_vwap_reports\requirements.txt
```

```powershell
.\backtesting\.venv\Scripts\python.exe backtesting\ha_bb_vwap_reports\run_csv_report.py --csv PATH_TO_HISTORIFY_CSV --out REPORT_DIRECTORY --capital 100000
.\backtesting\.venv\Scripts\python.exe backtesting\ha_bb_vwap_reports\plot_executed_trades.py --report-dir REPORT_DIRECTORY
```

The runner uses the saved ATHERENERG HA-high breakout / BB-middle-exit strategy,
with the volume filter disabled. It is not a generic strategy selector.

## Polars boundary

`polars_data.py` scans the required Historify CSV columns, parses IST timestamps,
checks OHLCV and duplicate timestamps, and retains only complete, finished regular
sessions. It writes normalized real candles and converts the validated data once
to the pandas/NumPy types expected by the unchanged strategy. It also aggregates
trade P&L into daily, monthly and exit-reason tables. No-trade sessions remain in
the daily return series.

Global validation and the strategy still materialize the dataset in memory.
No claim is made that the whole backtest streams or handles larger-than-RAM data.
Python position processing and the HA recurrence have not been rewritten.

The original `ha_bb_vwap_strategy_astra.py` is unchanged. Broker services and other
backtesting engines are unaffected by this scoped CSV-report implementation.

## Heikin Ashi exports

The input must be **actual OHLCV**, not previously converted Heikin Ashi candles.
The strategy calculates these values in timestamp order:

- HA close = (real open + real high + real low + real close) / 4.
- First HA open = (first real open + first real close) / 2.
- Subsequent HA open = (previous HA open + previous HA close) / 2.
- HA high = max(real high, HA open, HA close).
- HA low = min(real low, HA open, HA close).

The recurrence continues across included sessions, without a daily reset. Excluded
sessions do not contribute to the recurrence. BB(20,2) uses HA close and population
standard deviation; VWAP uses actual HLC3 and actual volume. Actual OHLC drives
entries and exit checks. HA prices are synthetic signal prices.

`ATHERENERG_heikin_ashi_5m.csv` exports HA as open/high/low/close with original
volume. `real_vs_heikin_ashi.csv` keeps real and HA OHLC side by side. These exports
come directly from the same indicator frame used to generate the signals.

## Verification

```powershell
.\backtesting\.venv\Scripts\python.exe -m pytest backtesting\ha_bb_vwap_reports\test_polars_data.py -q -p no:cacheprovider -o addopts=
.\backtesting\.venv\Scripts\python.exe backtesting\ha_bb_vwap_reports\verify_polars_migration.py --csv PATH_TO_HISTORIFY_CSV --report-dir ORIGINAL_REPORT_DIRECTORY
```

The migration check compares normalized candles, all HA/indicator values and every
trade with the saved original report, then reconciles daily/monthly/exit totals.
It records three alternating-order preparation timings in `polars_validation.json`.
The timing includes CSV parsing, validation, filtering, normalized export and the
pandas boundary. The new path also removes the old normalized CSV reread, so the
speedup is for the preparation workflow, not an isolated library comparison or
an end-to-end backtest benchmark. Memory usage is not measured.

On the supplied 25,153-row ATHERENERG CSV, the initial check passed with 25,050
included candles, 73 unchanged trades and net P&L of INR -6,262.724055.
Median preparation time was 2.657 seconds before and 0.529 seconds after (5.02x).
These timings are machine- and workload-specific.
