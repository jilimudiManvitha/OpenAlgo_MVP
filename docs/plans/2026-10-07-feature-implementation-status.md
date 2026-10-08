**October 8 update:** The direct-build/project-review request supersedes the older backtest pause and isolation holds in this historical feature map. Latency is integrated, the normal bundle and main runtime were verified, and the new July 8–October 7 options backtest is complete. See [current review](2026-10-08-project-review-options-backtest.md) and [single report](../../backtesting/options_3months_2026-10-07.html). OpenAlgo and strategies are stopped; 28 schedules preserved.

# Feature implementation status — October 7, 2026

Documentation refreshed October 8. The user asked to skip further backtesting.

This is the current implementation map following the authorized evening combination.
It supersedes older **isolated / not deployed** descriptions in the development
checkpoints. Features are in the normal local application build. Only the user
starts or stops OpenAlgo; availability in the build is not proof of real-account
execution. The [release handoff](2026-10-07-evening-combine.md) records integration
checks and the restart procedure.

| Feature | Implemented behavior | Detailed implementation and limits |
|---|---|---|
| Portfolio | Ten asset classes, ledger, dashboard, nine reports, scoring/charts, watchlists, weighted average and FIFO; separate Live/Sandbox data and explicit order/GTT review | [Portfolio completion](2026-10-06-portfolio-completion.md), [mode support](2026-10-07-live-sandbox-features.md) |
| Reports | IST day containing all strategies, combined and strategy P&L/trade/win/loss/charge/capital metrics; stock groups and individual trade charts; April–March calendar with strategy/stock filters and streaks | [Journal implementation](2026-10-07-report-journal.md) |
| Brokerage | Standard retail estimates selected from recorded broker context, falling back explicitly to the login broker on older reports; same estimate logic for Live/Sandbox; actual confirmed fees take priority | [Profiles, components and sources](2026-10-07-report-brokerage.md) |
| Screener | Live market quotes in both execution modes; current mode shown; execution/report integrations retain mode attribution | [Mode implementation](2026-10-07-live-sandbox-features.md) |
| Trade Copier | Master to multiple children, native FYERS/Zerodha/Dhan and separate OpenAlgo gateway children for other installed broker plugins; Live/Sandbox separation, concurrent dispatch, encrypted credentials, partial fills, durable deduplication, risk/stop controls, reconciliation and latency display | [Copier architecture, usage and verification](2026-10-07-trade-copier.md) |
| Scheduled equity | Eight long and eight short profiles, 1m/5m scanner/watchlist fixed/trailing variants; equity entry cutoff and square-off at 15:15 | [Short rules](../../strategies/short_equity/README.md), [long profiles](../../strategies/top_gain_volumes/profiles.py) |
| Scheduled options | Twelve Delta/Premium/Iron Condor variants, intraday/positional and current/next expiry; every new basket has equal-quantity, same-expiry 200-point protective wings | [Options rules and recovery](../../strategies/nifty_options/README.md) |

## Where to use the features

- **Reports** (`/strategy-reports`): select the financial year and PAPER/LIVE
  scenario, choose estimated or recorded fees, and click a date for combined
  totals. Expand a strategy and stock group; use the filters for their calendars
  and streaks, or open an individual trade chart.
- **Portfolio** (`/portfolio`): the main Live/Analyze switch selects the separate
  account ledger. Use Watchlists & orders to prepare an order/GTT and review the
  displayed mode, broker, instrument, price, quantity and estimated charges.
- **Scanner** (`/market-scanner`): market quotes remain real in either execution
  mode. Sandbox changes execution, not the price source.
- **Trade Copier** (`/trade-copier`): select the intended mode, add each child
  account with credentials and explicit symbol/risk policy, verify the account,
  review and arm copying. Review unknown outcomes before re-arming; a timeout is
  not proof an order failed. Stop blocks further copying and does not flatten
  already-filled child positions.

## Boundaries that remain

- The 28 scheduled strategy runners are **Sandbox strategies**. Supporting both
  modes in Portfolio/Reports/Copier does not convert these runners to live trading.
- Copier credentials, child account policies and deliberate arming remain user
  actions. Enabling the feature creates no child and submits no order. Native
  child token renewal is manual. Other brokers need a separate compatible child
  OpenAlgo instance; universal native adapters are not claimed. Real broker fill
  latency, cloud deployment and a multi-account market-session soak remain unverified.
- Portfolio live GTT support depends on the installed broker adapter's capabilities.
  Execution acknowledgements alone do not become confirmed ledger fills.
- Brokerage coverage is eight verified broker profiles and supported NSE/NFO
  segments. Unsupported brokers/segments show unavailable estimates. Contract-note
  rounding and excluded account/financing/exercise charges can differ.
- Reports use available, owner-attributed saved strategy reports and confirmed
  Strategy Builder fills. They are not a universal import of every broker trade.
  Report capital is entry-value exposure/premium turnover, not historical SPAN.
- Existing carried option baskets retain their saved state. Missing wings are
  acquired by the updated runners only with fresh quotes and confirmed fills.
  Source updates do not themselves protect or liquidate those positions.
- 28 schedules are installed: sixteen equity 09:15–15:15 and twelve options
  09:15–15:40 (intraday trading exit 15:20). Watchlists remain user-managed; their
  current content, rather than older empty-list notes, determines a day's replay.

## Backtest checkpoint — paused by the user October 8

The user said **“skip backtest for now.”** Do not resume downloads, simulations or
backtest validation unless requested again. October 7 remains the requested
session; do not silently substitute October 8 after the date changed.

Before that instruction, the isolated October 7 replay produced
`backtesting/all_strategies_2026-10-07.html` as the sole new HTML deliverable.
It covers 28 profiles in two separate modeled paths, with daily, strategy and
stock/contract metrics, FYERS estimates, capital exposure and a one-day calendar.
The file is retained; final backtest sign-off is not claimed. Desktop/mobile
browser checks and displayed-total reconciliation completed, but the final
preservation check did not pass: the schedule file and six operational database
hashes differed from the 19:54 baseline. Their source was not established before
work was paused. Do not overwrite or restore those files, or infer that this
backtest changed them. The read-only schedule check still found 28 schedules
with the expected times; the options state and frontend build hashes matched.

Private inputs, caches and available evidence remain under
`log/test/day-review-20261007/`; generators/checkers are under
`.development/day-review-20261007/`. No backtest was inserted into application
Reports. All command sessions started for this backtest had completed before
the pause. Data limits include retrospective scanner membership, one excluded
stock with invalid warmup OHLC, empty option contract histories, and a flat start
for positional strategies. A one-day test cannot establish a longer day streak.
