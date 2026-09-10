# NIFTY50 BB + VWAP + Heikin Ashi: strategy review and backtest status

Prepared: 5 September 2026, IST.

**Status: historical backtest and optimization are blocked by API access. No historical performance results exist yet, and no best strategy has been established.**

The requested period is **5 September 2021 through 5 September 2026**, using five-minute candles and Nifty 50 stocks only. The runner will use the latest completed trading session available from the API. These dates are the requested window, not a claim that data was received.

## What has been completed

- Read the indicator-expert, vectorbt-expert, backtest and optimize skills and the relevant fee and chronological validation guidance.
- Inspected `backtesting/stratagies/nifty500_bb_vwap_heikin_ashi_openalgo.py` without executing its live trading entry point.
- Inspected `autoresearch/README.md`, `program.md`, and the preparation, model and evaluation structure in `prepare.py` and `train.py`.
- Implemented `backtesting/stratagies/nifty50_bb_vwap_ha_research.py`: an API-only historical runner, shared portfolio simulator, VectorBT accounting audit, 35 predefined experiments, chronological selection, and report generation.
- Created an isolated Python 3.13 environment at `backtesting/.venv`, leaving the application's Python environment unchanged. Pinned Plotly below version 7 after a real compatibility failure with VectorBT.
- Passed 11 synthetic tests covering source signal agreement, causal indicators, session resets, shared capital, whole shares, transaction costs, next-bar fills, gap stops, risk sizing, daily loss cutoff, drawdown, timestamp normalization and report/chart export.

Synthetic test fixtures verify software behavior. They are not market data and were not used to claim strategy returns.

## Execution blocker

The root `.env` and current process environment contain no `OPENALGO_API_KEY`. The configured server, `http://127.0.0.1:5000`, also refused connections when checked.

The API preflight stopped with:

> OPENALGO_API_KEY is missing from the root .env or process environment

`run_status.json` records the failed preflight. No market history was retrieved or saved. Brokerage application credentials already present in `.env` are not interchangeable with the user-facing OpenAlgo API key.

To unblock, set `OPENALGO_API_KEY` in `D:\Personal\openalgo\.env`, start OpenAlgo, and log into the connected broker. If OpenAlgo runs elsewhere, set `OPENALGO_HOST` to that URL. Keep the key out of chat and reports.

From `D:\Personal\openalgo`:

```powershell
.\backtesting\.venv\Scripts\python.exe backtesting\stratagies\nifty50_bb_vwap_ha_research.py --preflight
.\backtesting\.venv\Scripts\python.exe backtesting\stratagies\nifty50_bb_vwap_ha_research.py --start 2021-09-05 --end 2026-09-05
```

The full command uses read-only history and public constituent APIs. It contains no order-placement endpoints. Omitting explicit dates requests the five years ending on the actual run date.

## Source strategy reconstructed

| Component | Source behavior |
|---|---|
| Universe | Originally Nifty 500; the research runner requests exactly 50 current Nifty 50 symbols from the NSE JSON API |
| Candle interval | Five minutes, completed candles only |
| Candidate filter | Gain at least 1% versus previous daily close OR cumulative session volume at least 2x prior 20-day average daily volume |
| Candidate ranking | Maximum of normalized gain and volume scores; top 30 |
| Signal | Bullish Heikin Ashi, no lower wick, HA close crosses above BB upper and stays above session VWAP |
| Confirmation | Immediately following candle: HA close above signal HA high, BB upper and VWAP; bullish and wickless |
| Bollinger Bands | SMA(20), 2 standard deviations, calculated on HA close |
| Session behavior | HA, BB and VWAP restart each morning because the live source fetches current-day candles |
| Account | Rs 10,000 capital; 5x leverage; Rs 50,000 notional ceiling |
| Position constraints | One shared position across the entire universe; maximum three entries per day |
| Initial stop | HA-close test at entry minus Rs 10/share; not a resting market-price stop |
| Target | HA close reaches 2R; default behavior continues holding rather than selling at the target |
| Trail | HA close below BB middle exits; this also applies before the 2R target |
| Square-off | 15:20 IST |

The source's requirement for at least 22 completed candles means its first eligible signal is approximately 11:05 IST. The first possible confirmed market entry follows one bar later. Its displayed 09:20 entry-window start does not eliminate this indicator warmup.

## Material findings

1. **Synthetic fills:** the source's paper mode enters and exits using HA reference prices. These are calculated values and may not be executable. Historical results must use real prices. The runner executes after confirmation at the next actual bar open, with adverse slippage.
2. **Stop timing:** the original Rs 10 stop is checked only against completed HA close. An actual-price move through the stop need not exit. Calling that a guaranteed Rs 10 maximum loss would be incorrect.
3. **Stop removal after target:** with trailing enabled, reaching 2R disables the initial stop; only the BB-middle condition remains. Enhanced candidates keep an actual-price stop active.
4. **Unequal capital risk:** nominally allocating Rs 50,000 to a Rs 100 stock gives 500 shares and Rs 5,000 of specified stop distance, before costs. Allocating to a Rs 1,000 stock gives 50 shares and Rs 500 of specified stop distance. The same rule therefore has very different account risk across stocks.
5. **Shared capital matters:** running 50 independently funded stock backtests and adding their returns would misrepresent this one-position strategy. The runner selects trades chronologically from one shared account.
6. **Historical scanner inputs:** live quotes cannot be recreated exactly from five-minute candles. The reconstruction uses completed real closes and cumulative volume available at each decision time. Prior daily volume is shifted to avoid using the final volume of the day being traded.
7. **Coverage and constituent bias:** today's Nifty 50 membership is not historical membership. Current members that listed or changed identity during the window may lack early history. Coverage is disclosed and unavailable data is not backfilled. Provider adjustment behavior for splits, dividends and demergers still needs validation against actual API responses.

The runner additionally caps notional by remaining account equity and reserves entry fees. These constraints prevent the fixed-capital source configuration from silently assuming unlimited replenishment after losses.

## Enhancement hypotheses prepared for evaluation

The predefined 35 configurations include:

- Original strategy reconstruction.
- Persistent actual-price stop with the original fixed rupee distance.
- ATR(14)-based stops at 1.0x, 1.5x and 2.0x.
- Risk sizing at 1% of current account equity, plus a 0.5% variant.
- A 2.5% daily loss cutoff for risk-managed variants.
- BB periods 15, 20 and 25, with multipliers 1.8, 2.0 and 2.2.
- Earlier entry cutoff, time-of-day relative-volume confirmation, VWAP-extension filtering and a fixed-target exit variant.

These are **untested hypotheses**, not recommendations or claimed improvements. There is no `best_strategy` performance result. The executable candidate definitions are in `experiments()` in the research runner; `search_space.json` records their parameters before market results are available.

## Adapting autoresearch

The supplied `autoresearch` project trains a GPT-style language model on one GPU. Its original score, `val_bpb`, measures language-model quality. Running its `prepare.py` would retrieve unrelated training data and would not backtest this strategy.

The strategy research adopts its useful experimental method: establish a baseline, fix the evaluator, log each candidate, prefer simpler changes when evidence is similar, and keep or discard based on measured results. The language-model files remain unchanged.

The research uses a finite, auditable search:

1. Development: 5 September 2021 to before 5 September 2024, divided into three chronological folds.
2. Validation: 5 September 2024 to before 5 September 2025; compare the five strongest eligible development candidates and the baseline.
3. Holdout: 5 September 2025 through the last completed session on or before 5 September 2026. Lock parameters before evaluating this period.
4. Cost stress: rerun the locked candidate on holdout with slippage doubled from 5 to 10 basis points each side.

The development score penalizes drawdown and instability across folds. Minimum trade counts and profitable-fold checks reject thin evidence. Holdout failure does not trigger further optimization on that same holdout. A selected full-period curve will be labeled retrospective; only the reserved final period is a holdout for selection.

## Costs and data policy

The cost model approximates current Fyers intraday charges: brokerage of min(Rs 20, 0.03% turnover) each side, sell-side STT, buy-side stamp duty, exchange/SEBI charges, an explicit IPFT assumption and GST. Current rates are applied consistently across the historical period; historical tariff changes and charge rounding are not reconstructed. Sources: [Fyers charges](https://fyers.in/charges-list) and [Fyers brokerage calculator](https://fyers.in/calculator/brokerage).

All price and volume history must come from OpenAlgo `history(source="api")`. The runner requests short date chunks, computes in memory, and saves only reports, trade results, account-equity series, parameter settings and coverage metadata. It does not save raw OHLCV, constituent-response files or a market-data cache. It does not read local history databases. The constituent list comes from the [NSE Nifty 50 JSON API](https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050).

## Reports generated after a successful run

The final report will replace this status report and include strategy-versus-NIFTY metrics, full-period and holdout results, drawdown, returns, CAGR, Sharpe, Sortino, trade count, win rate, profit factor, fees, and cost stress.

Supporting files will contain baseline and selected-candidate trade ledgers, all 50 stocks' attribution including zero-trade stocks, monthly/yearly P&L, interactive offline equity/drawdown charts, development parameter heatmaps, experiment rankings, validation results, locked parameters, and reproducibility metadata.

At present, all historical performance fields are **unavailable**, because API access has not passed preflight.
