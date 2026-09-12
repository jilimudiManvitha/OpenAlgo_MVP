# Backtest methodology — 11 September 2026

## Scope and reproduction

All **404 Python versions actually present** in `strategies/ha_bb_vwap_v1/versions` are tested: 101 versions in each buy/sell × 1m/5m group. Each runs independently on its supplied 11-stock basket under two assumed minute paths, for **8,888 strategy-stock-path runs**. This does not generate the millions of possible combined parameter configurations. No source strategy rule was changed or optimized.

Buy inputs are the normal candles under `CSVs/GainersOn11092026/historify_export_20260912_194124`; sell inputs are under the actual folder spelling `CSVs/LoosersOn11092026/historify_export_20260912_195613`. Previously converted HA files are not inputs. Only the September 11 session can create trades. Up to 600 earlier bars per timeframe initialize indicators and HA state. This finite initialization is not a claim of exact full-history equivalence. ASHOKAMET, DIGJAMLMTD and LADDERUP have no earlier bars in the supplied files.

From the repository root, using the installed backtesting environment:

```powershell
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/batch.py
# Rebuild reports from completed stock checkpoints:
& backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/run.py --report-only
```

Source hashes and coverage are in `data_audit.json`; settings, metadata and engine fingerprint are in `run_config.json`. Checkpoints resume completed stocks and reject changed engine/harness code. Do not reuse them after changing CSV contents, definitions, metadata or assumptions; preserve this run and use a new output directory. The verifier checks source hashes against the frozen audit.

## Intrabar approximation and causal indicators

The strategy requires forming-candle observations. A completed OHLC CSV does not contain the real tick sequence. Each one-minute candle is therefore reconstructed with either **O → L → H → C (OLHC)** or **O → H → L → C (OHLC)**. Each of the three legs has three evenly spaced linear price steps, giving ten observations including the open, between second 0 and second 59.999. Volume accumulates linearly from zero to that minute's supplied total. These paths and volume assumptions are synthetic. Results are sensitivity scenarios, not actual executions or mathematical upper/lower bounds; more path shapes, resolution choices and volume timing can change the ranking.

At each observation, the current OHLC includes only the path traversed so far. HA and indicators use that prefix plus completed earlier bars, never the final current bar before it completes. OpenAlgo TA supplies Bollinger Bands 20/2, SMA9, EMA9/21, RSI14, MACD12/26/9 and Supertrend14/2. Indicators use HA prices as specified by the source strategy; session VWAP uses raw HLC3 weighted by volume and resets daily. HA state carries between sessions. Final bars commit once.

Five-minute forming candles aggregate observed one-minute data. Their completed target-session values are therefore reaggregated from the 1m source, while earlier warmup comes from the supplied 5m file. Differences against the supplied target-day 5m file are listed in the audit, not silently substituted during a forming candle. Missing source minutes remain missing; no price/volume candle is fabricated.

Every run instantiates the actual version's `create_strategy` factory. The existing engine owns signal timing, immediate-next-bar entry, no-adverse-wick checks, indicator exits, risk/reward, partial exits, trailing stops and square-off. Its full/tick exit distinction is preserved. “Tick” here means a modeled forming observation. Actual path order, spreads, queue position, processing delay and intermediate crossings are unavailable.

## Execution, capital and costs

An emitted order fills immediately at its observed **real-price reference**, with 0.05% adverse slippage, then adverse tick rounding. Synthetic HA prices are never used as executable fills. Whole-share entry size is reduced when necessary so actual entry notional stays at or below Rs 100,000. Partial exits pay their own order charges. No margin leverage is assumed. Multiple stocks can overlap: basket return uses Rs 1,100,000, with peak concurrent entry notional also reported. Capital is a fixed allocation per stock/trade; profits are not compounded into larger entries.

Zero-volume minute observations cannot open trades. Existing positions can still exit at the last modeled reference, including non-liquid/final observations and scheduled square-off. Such fills are uncertain: there is no participation cap, depth, bid/ask, queue or circuit-limit fill model. The whole-minute volume gate itself is a bar-data approximation, not evidence of available volume at an exact simulated second.

Square-off is 15:05 for locally identified F&O underlyings and 15:20 for the others. The clock event is processed before the first observation at/after the cutoff, using the then-known reference (normally the preceding completed minute's close). Tick sizes and F&O status come from the read-only local instrument master on September 13; this is adjacent-date metadata, not a reconstructed September 11 master. Exact historical membership, corporate-action adjustment policy and short-sale/circuit execution availability remain unverified.

Estimated NSE cash intraday charges per fill:

| Component | Rate |
|---|---|
| Brokerage | min(Rs 20, 0.03% of turnover) |
| Exchange transaction charges including IPFT | 0.00307% of turnover |
| SEBI fee | 0.0001% of turnover |
| STT | 0.025% of sell turnover |
| Stamp duty | 0.003% of buy turnover |
| GST | 18% of brokerage + exchange + SEBI fees |

Sources: [Zerodha charges](https://zerodha.com/charges), [exchange transaction charges](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges), [STT calculation](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated). These are research estimates, not a broker contract note: daily tax rounding, any broker auto-square-off surcharge, and account-specific charges are not modeled.

`gross_pnl` includes slipped/tick-rounded fill prices but excludes fees. `net_pnl = gross_pnl - fees`. `reference_pnl` uses the same filled quantities and order references without price friction; `slippage_cost = reference_pnl - gross_pnl`. This is an execution-cost decomposition of the same ledger, not a separate frictionless strategy run (slippage also affects risk targets and sizing).

## Metrics, charts and interpretation

Each strategy report includes both paths, individual stocks including zero-trade cases, every round-trip trade and partial fill, win rate, drawdown and peak notional. CSVs additionally provide profit factor, per-trade expectancy and return on basket allocation. Drawdown is **bar-close mark-to-market**, including realized P&L and fees already paid; it can miss deeper intrabar drawdowns. Profit factor is null when there are profits and no losses. Annualized Sharpe/Sortino/CAGR are omitted because one session cannot support meaningful estimates.

VectorBT `Portfolio.from_orders` independently checks every replay fill ledger's final P&L and acceptance of all fills. It uses sufficient accounting cash to avoid a second artificial cash constraint; strategy sizing and reported basket allocation remain as above. This validates accounting, not the realism of synthetic fills.

The comparison benchmark buys/shorts each supplied stock at its first nonzero-volume open and exits at its scheduled cutoff's open (or last available preceding close), using the same sizing, slippage, ticks and charges. It is a descriptive same-universe session reference. It differs slightly from the strategy clock's last-known-price convention. NIFTY data was not supplied, so no index comparison is claimed.

Each trade has an offline interactive chart covering **09:15–15:30 IST**, with green/red HA candles, raw candles available through the legend, BB/VWAP, entry/exit fills and stop/target levels. Entries and exits appear within their timeframe bucket; exact assumed timestamps are in hover text and the fill table. The last normal candle starts at 15:29 (1m) or 15:25 (5m) and ends at 15:30. No artificial candle starting at 15:30 is created. The toolbar exports a high-resolution PNG; retain the adjacent assets folder when copying reports.

Ranking uses the **lower net P&L of the two scenarios**, then mean net, then drawdown. Equal results can arise when varied thresholds never trigger, or paths produce the same fills. A high configured reward/risk does not prove the target was reached. Winners are chosen among 101 tested candidates per group on this same day, creating parameter-selection bias. Gainers/losers chosen using the day's outcome add universe-selection bias. The result identifies the best observed version on this supplied sample, not a strategy established to work on future days.
