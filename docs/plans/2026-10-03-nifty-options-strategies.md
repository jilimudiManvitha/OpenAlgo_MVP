# NIFTY options strategies — October 3 implementation checkpoint

## Authorized scope and confirmed rules

Separate user request, not resumption of frozen scanner/Crypto/investment work.
Twelve separate Python launchers under `strategies/`: iron condor, delta and
premium; each intraday/positional and current/next listed weekly expiry.
NIFTY NFO only. Equal quantities on basket legs; condor hedges exactly 200 points.
Current/next use actual listed expiries, including holidays and historical changes.

User follow-up confirmed:

- Entry at **09:30 IST** for all families; no opening-range breakout required.
- Rebalance all delta/condor variants at **absolute signed net delta >= 0.50**;
  include hedges. This supersedes individual-leg 0.50 interpretations.
- **₹20 lakh allocated per strategy**, whole lots sized by broker basket margin
  for scheduled paper trading and an explicitly labelled historical margin model.
- Intraday square-off **15:20 IST**. Positional loss accounting carries through
  the full trade and all adjustments. ₹20,000 strategy stop takes priority.
- Premium stop = entry premium * 1.30; close only hit short and retain survivor.
- Condor stop = either short entry premium * 4; close all four, then reselect.
- Sandbox total capital **₹5 crore**; all state and positions persist on restart.
- Initially asked five-year history; **latest instruction supersedes this: last
  three months only**, interpreted **2026-07-03 through 2026-10-01**, latest
  completed trading day before October 3. Old five-year downloader stopped.
- Backtest data/results and all future backtests go in **`backtest/`**, never the
  application Reports database/page. Preserve existing historical reports.

Implementation defaults to disclose: positional exit at expiry 15:20; initial
entry grace ends 09:31; delta matching tolerance 0.05; adjustment cooldown 60s;
re-entry cutoff 15:15. Positional stop latch remains through that expiry; intraday
stop latch through that trading date. Fee/slippage/margin model are estimates.

## Current checkpoint — October 4 (implementation and three-month backtest complete)

- Created twelve launchers and `strategies/nifty_options/` shared profiles,
  selection, decision engine, SQLite state/event store, direct Sandbox-only
  execution adapter, WebSocket runtime, historical collector and data probes.
- **45 focused tests pass**, covering selection, loss latches, net delta,
  partial/crashed order recovery, whole-lot sizing, observed-price gaps and
  independent VectorBT reconciliation. An in-memory disabled re-entry guard made
  the actual regression fail; restored code passes. 200 real SQLite/lock cycles
  including conflicts/exceptions kept descriptors flat at 3. No market-hour soak.
- Sandbox capital successfully changed 10,000,000 -> 50,000,000 without resetting
  ₹265.28 realized profit, positions or margins. Available balance was
  50,000,265.28; used margin zero. Automatic resets set to Never. Audit JSON in
  `db/nifty_options/` (private runtime data).
- FYERS probes returned real 2021 and 2026 NIFTY option minute candles.
  Historical Greeks are unavailable; derive and label Black-76 model deltas.
- Five-year catalogue contained 98,304 contracts, but that scope is now obsolete.
  Retain its cache, do not resume its downloader. Three-month archive completed
  October 4: **7,096/7,096 contracts**, after resuming expired-login and temporary
  rate-limit failures. Explicit no-data responses are retained as empty archives;
  a completed request does not imply every contract traded each minute.
- VectorBT 0.28.5 installed in project venv for independent accounting validation.
- **Twelve schedules are installed**, plus eight original definitions verified
  unchanged. User explicitly approved restart/install. The final schedules use
  NFO weekdays 09:15–15:40, with entry 09:30 and intraday exit 15:20. Startup
  confirmed 20 schedules restored. User says OpenAlgo is running October 4;
  **leave it running**. Schedules are enabled, not market-hour runs yet.
- All twelve use NRML; their own runner handles intraday 15:20 exits so the
  existing account-wide 15:15 MIS manager cannot close them behind their ledger.
  This preserves existing strategies' global settings.
- Read-only live check verified API-key WebSocket authentication/subscriptions,
  960 current/next NIFTY contracts and FYERS sample basket margin ₹294,105.07.
  No NIFTY orders placed. Live ticks, fills and actual 09:30 timing remain untested
  outside market hours. Evidence under `backtest/nifty_options/verification/`.
- Real July validation replay completed, 24 scenarios with closed-leg accounting
  reconciled, and local Plotly/OpenStatz artifacts generated. This is a bounded
  validation sample, **not** the requested three-month result. The final three-month replay is now complete; use its results instead.
- Replay uses prior-completed-minute signals and next opens, modeled OLHC/OHLC
  stop paths, historical margin/fee/slippage assumptions. Option session extends
  through 15:40 from August 3 (375 -> 385 minutes); Greeks use matching expiry
  times. Index benchmark uses available 09:15–15:29 closes. Holiday sessions checked.
- Missing held bars delay the whole basket to its next complete observed bar;
  no price/fill/equity mark is fabricated. Each gap is recorded; >5 consecutive
  minutes or missing final held marks abort. This can delay stops/understate
  drawdown. Invalid Greeks delay delta decisions while price/clock risk continues.
- Full replay log: `log/nifty-options-three-month-replay.log`; current download
  and result status JSON live in `backtest/nifty_options/2026-07-03_2026-10-01/`.

## Sources

- [NSE NIFTY specifications](https://www.nseindia.com/static/products-services/equity-derivatives-nifty50)
- [2024 lot revision, effective April 26](https://nsearchives.nseindia.com/content/circulars/FAOP61415.pdf)
- [2024–25 weekly/monthly lot transitions](https://nsearchives.nseindia.com/content/circulars/FAOP64625.pdf)
- [2026 NIFTY lot size 65](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf)
- [NSE derivative session timings](https://www.nseindia.com/static/products-services/closing-auction-session)
- [2026 F&O holidays](https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf)
- Local `docs/api/market-data/expired-fno.md` and existing FYERS provider.

## Completed three-month results

[Results and reproduction](../../backtest/nifty_options/2026-07-03_2026-10-01/README.md)
([interactive HTML](../../backtest/nifty_options/2026-07-03_2026-10-01/results/index.html)).
Both modeled paths completed all **64 sessions**, all 12 variants each.
**2,428 closed-leg rows**, 7,097 source hashes and 98 local links verified;
24 offline OpenStatz dashboards generated. Source and policy are frozen under
`results/source/`. Final `status.json` is complete and `ledger_verification.json`
passed. A final verifier failure on mixed fractional-second ISO timestamps was
reproduced, fixed using explicit ISO8601 parsing, then the entire replay rerun.
No trading-model changes were made for that reporting fix.

Nine variants gained and three lost under both paths. Highest ending profit:
delta intraday current-week, ₹55,859.63 OLHC / ₹55,849.87 OHLC. Largest ending
loss: iron-condor positional next-week, −₹36,830.03 / −₹36,734.12. The arithmetic
sum across ₹2.4 crore allocated is +₹2,10,727.34 / +₹2,10,665.46 (about 0.878%);
this is not a shared-account margin/execution simulation. NIFTY gross −7.794%.
Iron-condor intraday current-week drawdown is about ₹2.15 lakh / 9.62%, despite
ending profitable. The ₹20,000 trigger is not a peak-equity trailing stop or a
guaranteed maximum fill loss; worst completed OLHC cycle lost ₹27,533.31.

Each path ends with two observed-marked open premium positional legs. Each has
three missing held-basket minutes (condor positional next-week) and eight Greek
unavailable minutes (six condor intraday current-week, two positional next-week).
These are recorded, not silently filled. Costs, historical margin, deltas and
intraminute ordering remain modeled. All 45 focused tests and scoped Ruff pass.
The final read-only OpenAlgo check confirmed 12 schedules, quote authentication
and subscriptions, 960 current/next contracts and sample margin ₹294,105.07.
The original eight schedule definitions remain unchanged; sandbox capital is
₹50,000,000, available ₹50,000,265.28, used zero, reset Never. No NIFTY orders
were submitted during this task.

## Operational follow-up

Requested code, scheduling, persistence, capital setup and three-month backtest
are complete locally. Market-hour tick/fill timing and a live restart soak remain
unverified; do not describe those as tested. Keep OpenAlgo running. No push and
no Reports writes. Future backtests also go under `backtest/`. Unrelated frozen
six-task/Crypto/investment work and existing user edits remain untouched.

## October 4 follow-up — one combined dashboard

User requested one full-period report with each strategy's win rate, win factor,
trade count and charts. Added `dashboard.py` and its offline HTML template;
`reporting.build()` generates it automatically for future replays.
[Combined dashboard](../../backtest/nifty_options/2026-07-03_2026-10-01/results/combined_dashboard.html)
and combined CSV contain all 12 variants per selected path, full-cycle trade
counts/win rates/profit factors, average-win/loss payoff, expectancy, P&L, fees,
returns, drawdowns, Sharpe/Sortino and open positions. Six interactive charts,
monthly marked P&L, filtering/sorting/CSV export and embedded cycle details.
Open cycles excluded from trade win metrics; no mixing of alternative paths.

Reconciled metrics against original summaries and monthly sums against net P&L.
Chrome verified all 24 strategy/path cycle counts and chart values, table totals,
filters/search/empty state, sorting, CSV and mobile overflow; no page errors or
network requests. Renderer/input hashes and browser verification are in the
result directory. Original simulation files/frozen code remain unchanged;
this is a reporting addition, not a rerun. OpenAlgo, schedules, trading code and
Reports database untouched.
