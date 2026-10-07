# NIFTY options strategies — October 3 implementation checkpoint

**October 7 local release:** User authorized combining Portfolio and scheduled-strategy fixes and pushing. The normal frontend is built; 407 backend checks and 20 frontend checks pass. Stock report shutdown grace and zero-position square-off are additionally repaired. [Morning checklist and operational limits](2026-10-07-local-release-readiness.md). The October 6 historical reports stay unchanged.

## October 6 — capacity repair and all-schedule daily backtest

The user confirmed **October 6 only** for this session review/backtest and asked
to fix the scheduled options. All 20 strategies now have two modeled intraminute
scenarios in [one offline HTML report](../../backtesting/all_scheduled_20261006/index.html).
[Results, reproduction and limitations](../../backtesting/all_scheduled_20261006/README.md)
include the strategy-wise table, source coverage, log findings and Portfolio review.

Today's twelve runners stayed alive but did not enter: subscription retries could
not overcome the shared 3,000-symbol capacity. The scanner could stream all 2,679
equities while options required 960 contracts plus NIFTY. Handshake/HSM/network
failures also occurred. Six stock reports retain pre-close `running` snapshots;
their final fills require separate reconciliation. No saved report was rewritten.

Implemented `market_scanner_feed.stream_limit()` caps FYERS scanner streaming at
1,000 while retaining full-universe REST refresh. Option `feed.required_contracts()`
selects each profile's complete required expiry and preserves held/pending cycle
chains for adjustments. Runtime staggers flat startup handshakes by 0–11 seconds;
held positions connect immediately, retries are paced. Entry windows and risk
rules are unchanged. **The scanner change requires the user's OpenAlgo restart**;
next scheduled subprocesses independently load the runner changes. This supersedes
the October 5 claim below that the whole repair needs no application restart.

Verification: **139 focused tests pass**, including the real shared-pool allocator
offline (1,000 scanner + 500 disjoint equities + 960 options + NIFTY = 2,461 slots),
all twelve actual runner loops, retry/error cleanup and carried expiry selection.
Disabling each of the cap, chain filter and delay in memory makes its regression
fail at the intended assertion. Scoped Ruff passes. No added resource owners or
unbounded caches; existing 200-cycle report success/error FD test passes. No live
market-hour soak or fill guarantee. Evidence: `log/test/scheduled-options-capacity.*`,
`log/test/{capacity,chain,stagger}-regression.log`,
`.development/scheduled-options/verify_capacity_regression.py`.

All 40 report scenarios/chart endpoints reconcile in offline Chrome; filters,
CSV download and desktop/mobile layout pass with no page errors or network
requests. 92 unique stock histories are complete for the selected baskets;
366 of 960 option contracts returned candles and 594 returned no candles.
Three current-week positional profiles skipped because their premium selection
band was unavailable. No bars/fills were synthesized. Historical membership is
retrospective; all simulations start flat today, not from prior carried positions.

Twenty schedules remain enabled and byte-identical:
`da5150800eb92b1d6cc86f4e5bdfa38354a93bb5532b7508f03dec65776e905f`.
All 520 protected schedule/frontend files match the captured baseline. No app
signals/start, production DB writes, schedule installer, orders, production
frontend build, commit or push. Portfolio implementation is locally complete;
deployment still waits for “combine and launch.” Network disruptions, stale stock
report reconciliation and the MCX missing-quantity error remain follow-up items.

## October 5 — scheduled startup repair and daily Reports

User authorized investigating today's failed schedules while OpenAlgo stays
running. All twelve option logs show the same 09:15 crash: any non-success
subscription batch raised `DataUnavailable` outside the recovery handler.
The original proxy rejection detail was discarded, so the exact upstream
morning trigger cannot be established. A read-only after-hours probe accepted
all **960 options + NIFTY** in the original 50-symbol batches. This confirms
current acceptance, not market-hour ticks/fills or the original rejection cause.

Changes, shared by all twelve launchers:

- Incremental, paced quote subscriptions retain per-symbol acknowledgements,
  retry only missing symbols with 2–30 second backoff, restore subscriptions on
  socket replacement, and preserve useful rejection details. Held symbols and
  NIFTY are requested first. New entries wait for complete acknowledgement;
  held-position price/clock risk still runs using fresh quotes during retries.
- Connection failures are paced; freshness is rechecked after a blocking ack.
  The 09:30–09:31 initial-entry window, capital/risk rules and Sandbox-only
  execution remain unchanged; missed entries are not submitted late.
- `daily_reports.py` publishes daily sessions to the existing Reports store,
  including no-entry/failure status, confirmed closed legs and carried open
  legs. Refresh every ten seconds and at shutdown. Restart rebuilding uses the
  owner/strategy/day journal, avoiding duplicate fills. Report-save errors do
  not interrupt basket management. P&L is full leg profit realized that day,
  not daily MTM; open unrealized P&L/brokerage excluded, metrics count legs and
  premium turnover rather than baskets/margin. No synthetic candles.
- **Latest destination instruction supersedes the older `backtest/` default:**
  new historical outputs use **`backtesting/nifty_options/`**, never Reports.
  Accepted existing `backtest/` files stay untouched and legacy archives remain
  readable. Historical backtests were not rerun or moved.
- Test database defaults now live under `log/test/`, matching the standing
  isolation rule. The existing isolated scheduler directory fix is preserved.

Verification: **109 focused tests pass** (18 new), scoped Ruff and whitespace
checks pass. Executing the original runtime in memory makes the actual recovery
test fail at its original `Option subscription failed` line. A 200-cycle real
SQLite report success/failure test keeps descriptor counts flat; retry sets and
queues are bounded (static review plus repeated-failure regression). No live
market soak or end-to-end fills were tested. Evidence:
`log/test/scheduled-options-fix.log`, `.xml`,
`.development/scheduled-options/verify_regression.py`, and `probe.py`.
Pytest exits zero; the existing scheduler atexit logger emits closed-capture
stream warnings after the passing suite. This is not a trading failure.

Read-only checks: all **20 schedules enabled**, saved bytes unchanged
(`4ca13320a7ffb9bb3f72cbd043b3c34ac722f05ad2a4413b0ed0d1cb0264e50f`);
API key valid, four production databases pass quick_check, twelve option
states have zero held legs/pending actions. Eight stock reports already exist
for October 5 (several retain `running` status); no old report was rewritten.
Monday watchlist now has 30 entries, supplied by the user.

OpenAlgo remains running. No signals, app restart, orders, production database
writes, schedule changes or frontend build were performed. The scheduler
launches separate Python processes, so **the next strategy start loads this
repair without an OpenAlgo restart**. Existing missed October 5 option entries
were not replayed, and today's failure reports were not retroactively inserted.
Daily option reports start with the next run. No commit or push requested.

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
