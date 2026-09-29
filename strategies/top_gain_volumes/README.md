# Top Gain Volumes live paper test

Run the application normally with `uv run app.py`. Open **Reports** in the
navigation, or `/strategy-reports`. Today's backtest is already stored there.
Choose a scenario, then any trade to view its candle chart. The only report
download is **trades.csv**; no separate server or PowerShell launcher is needed.

The bundled entry point is `../Top_Gain_Volumes_Live_1L_stategy.py`; its docstring
contains the English strategy. Support modules are application implementation,
not additional user launchers. The saved NSE paper schedule is Monday–Friday,
09:15–15:10 IST, subject to the exchange calendar. Keep OpenAlgo and its Quote
proxy running and log in to FYERS. Manage the schedule under **Python Strategies**.
The Reports page's **Schedule paper test** button reinstalls this one schedule.

The runtime selects the union of the top 50 positive gainers and top 50 positive
volume shockers (today's volume / prior five full-session average > 1). It uses
timestamped broker Quote events, rechecks membership at entry, and waits for
history readiness. A qualifying completed HA1m signal is followed by an entry
**during the next minute**, as price crosses signal HA high, forming upper BB
and VWAP with a green/no-lower-wick forming HA candle. It never waits for the
entry candle close. Each trade uses up to Rs 100,000 entry notional, fees extra,
whole shares, one entry per stock/day. Stop is signal HA low minus Rs 0.10;
target is 3R. **All forward-test stocks square off at 15:05 IST**, as confirmed
by the user on September 29. The process stops at 15:10.

This is an independent paper ledger: **no orders go to a broker or Sandbox**.
Market fills use observed prices plus 5 bps adverse slippage and instrument tick
rounding. Target fills are at least the target. Estimated charges are a flat
5 bps per fill, not actual brokerage/taxes. No total portfolio capital cap is
imposed. Stale quotes, gaps, failed history and event loss suppress entries.
If no fresh exit quote arrives, the report keeps that position unresolved.
A day's existing paper run cannot be overwritten/restarted automatically.
Broker Quote updates can be sampled/coalesced; this is not exchange TBT data.

Reports include gross/net realized P&L, estimated charges, peak simultaneous
entry notional, remaining entry notional, best/worst trade, win rate, profit
factor, realized drawdown and net/peak-capital return. These are not broker
margin figures; realized drawdown omits intratrade drawdown. Open trades are
listed separately. Charts use downloaded history and observed live candles.

September 28 replay uses the saved 15:25 scanner selection: 75 instruments,
60 complete sessions and 15 incomplete exclusions. Each path has 54 trades and
34 winners. OLHC net Rs 73,586.69; OHLC net Rs 73,698.56. This saved historical
run used the previous cutoffs (15:05 F&O / 15:20 other stocks), before the user
changed the forward-test cutoff to 15:05 for all stocks on September 29. Alternative path results
must not be added. Afternoon selection biases morning replay; historical tick
order and historical live scanner membership were not recorded. This result
does not validate future paper performance.

Internal report storage is `db/scanner_strategy_reports.db`; resumable input
downloads live under `db/scanner_backtest_cache/<date>`. Research intermediates
are temporary. For developer reproduction, `uv run python -m
strategies.top_gain_volumes.backtest` replays today's frozen selection/cache
and independently checks the ledger before updating the report.

Scanner visible refresh is 1s, with a 0.5s server merge interval; those are
configured intervals, not measured feed-to-screen latency. Warm scans bulk-load
cached baselines, cold/new-day baseline requests remain rate limited. Streaming
requests up to 5,000 symbols by default; FYERS documents this v3 limit in its
[subscription guidance](https://support.fyers.in/portal/en/kb/articles/is-there-a-limit-to-the-number-of-symbols-i-can-track-using-the-data-websocket-in-api-v3).
Actual subscription acceptance is checked; other active instruments consume
broker capacity. No market-hours forward run was observed during delivery.
