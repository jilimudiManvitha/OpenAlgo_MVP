# Six-task implementation plan and agent handoff

## Documentation checkpoint — 2026-09-30: four-strategy chart guide

The user requested one Markdown explanation of the four named strategy files,
with separate dynamic charts for signals, entries, stops, targets and trailing.
Created [the complete chart guide](../../strategies/FOUR_STRATEGIES_CHART_GUIDE.md)
and its linked [offline interactive charts](../../strategies/four-strategies-charts.html).
The guide follows the current 0.03% stop and ₹10,000 profiles, including the
legacy `1L` wrapper, strict trailing-profile VWAP checks, confirmed Sandbox fill
sizing and first-observed-price BB-middle exits after 3R.

Charts use explicitly illustrative prices/indicator levels, not market data or
a new backtest. Four separate panels provide five scenarios, VWAP filter examples,
playback and an observation slider/table. Source-function comparison matched all
20 illustrated exit paths / 140 observations; 28 browser scenario/filter checks,
playback, desktop/mobile inspection and local Markdown link checks passed.
No strategy code, execution settings, reports, database or app state was changed;
no orders, app restart, commit or push was performed. Preserve the pre-existing
local edit in `broker/fyers/streaming/fyers_hsm_websocket.py`. Frozen tasks remain
frozen. The earlier operational checkpoint below remains the restart reference.

## Active checkpoint — 2026-09-30: four 10K Sandbox strategies

**Latest amendment, 07:38 IST:** User requested all four stops change from
signal HA low minus ₹0.10 to **0.03% below signal HA low**. Shared entry now
uses `floor((signal_low * 0.9997) / tick + 1e-9) * tick`; fixed 3R and trailing
activation automatically use the updated risk. All four source docstrings,
future replay verification/report notes and guide updated. Existing September 29
reports are preserved **old-stop results**, not rerun or relabeled. Four new
price/tick regression cases failed against the old formula then passed after
the change; focused suite **118 passed**, scoped Ruff/diff checks passed.
Saved schedules were checked against all four desired configurations and still
point to these updated files: enabled NSE weekdays 09:15–15:00. No reinstall is
needed because schedule/file paths are unchanged. At the user's request, the
exact OpenAlgo PID 84279 (no child processes) was stopped via terminal Ctrl+C
at 07:38:50; terminal session 14444 exited and PID absence was verified.
Schedules remain saved/enabled but **OpenAlgo is intentionally stopped**.
User will start it manually; do not restart automatically. Earlier active-app
statements below describe the preceding checkpoint, not current process state.

User explicitly authorized the four strategy profiles, Nifty500 scanner and
weekday watchlist universes, 09:15–15:00 NSE weekday schedules, historical
replays, reports, and Go/Rust performance work. Strict variants use HA OHLC
above VWAP; 3R arms a first-observed-price-below-BB-middle exit while retaining
the original stop. Execution is OpenAlgo Sandbox only. Watchlist Chg% sort and
range filters are display-only. User approved the runtime cleanup fix.

Four entry files/shared runtime, display-only Chg% controls, EOD reports, native
acceleration and approved exception-safe runtime cleanup are implemented.
Final focused scanner/category/strategy suite: **114 passed**. Watchlist UI:
19 passed; frontend type check/build passed. Cleanup failure/mutant tests and
real Sandbox fill/position checks use isolated test databases. 120 native
worker/lock cycles pass the descriptor bound; Go race and Rust tests pass.
Browser fixtures pass all four reports/eight scenarios and mobile layout, with
three indicator lines and no page errors (mocked auth, not a live auth test).
Five real FYERS daily-history results match Python exactly: Go 0.690s vs Python
0.893s. Rust BB 1.901us vs old NumPy 12.615us. These are component benchmarks,
not market-hours order-latency claims or a full-session memory soak.

FYERS was reconnected. Exact non-overlapping epoch-range downloads and response
clipping resolved watchlist history overlaps; no candle values were fabricated.
User explicitly approved replacing only Tue's BSE:WIPRO with NSE:WIPRO: done,
item ID 16 / position 15 preserved. September 29 replays now cover **16/16 Tue
stocks** and **74/75 scanner stocks**; ANTHEM is excluded for invalid OHLCV.
Saved OLHC/OHLC net: scanner fixed ₹2,350.93/₹1,945.60; scanner trailing
₹1,391.14/₹575.31; weekday fixed −₹1,222.97/−₹1,430.71; weekday trailing
−₹60.86/−₹324.81. All four ledger verifications pass. These are alternative
modeled paths with illustrative costs and retrospective-selection bias, not
observed ticks or September 30 performance. Older reports remain untouched.

Four schedules installed/read back at 07:18 September 30: NSE weekdays
09:15–15:00, enabled. First detached app restart failed Werkzeug's non-TTY guard;
the subsequent interactive `.venv/bin/python app.py` launch succeeded. At
**07:24:59 IST startup logged `Restored 4 scheduled strategies`** and FYERS
order-update WS connected. `/strategy-reports` returned HTTP 200. The unrelated
Strategy Module's separate zero-job startup line is not the Python scheduler.
Current app runs in terminal session 14444; keep it and the Mac awake. Do not
repeat the failed detached launch or disable debugger safety. CLI installation
requires an app reload; Reports-page installation schedules in the live app.

Implementation/backtest/install work is complete. Remaining operational checks:
first market-hours forward execution, observed order latency and full-session
EOD/resource behavior. No production orders were submitted during verification.
Mon/Wed/Thu/Fri are empty; user must populate Wed for today's watchlist profiles.
Unresolved fills/positions block same-day restart until reconciled; do not erase
reports to bypass this guard. Shared account/symbol Sandbox positions mean users
should avoid unrelated manual Sandbox trades in the same symbols.

Full rules, four source links, metrics, caveats and commands:
[four-strategy guide](../../strategies/top_gain_volumes/README.md).
Preserve unrelated task.txt, skills-lock.json and agent skill folders. No commits
or pushes authorized/performed. Earlier frozen tasks/Crypto remain untouched.

## Latest checkpoint — 2026-09-29: stock categories saved locally

The user authorized importing `Stock_Symbols` into the DB by index/sector and
adding missing groups. This is scanner/category data work; frozen strategies
and Crypto remain untouched. Original 41 CSV/TXT inputs are unchanged.

Saved to `db/market_scanner_live.db`: **544 distinct ticker strings, 56 categories,
7,134 memberships**. There are **46 scanner categories** and ten separate
historical/download reference groups. Nifty 50/Next 50/500 contain 50/50/500
members. Includes all supplied broad/sector lists, Cement, 20 Industry-column
groups, plus derived LargeMidcap 250 and MidSmallcap 400. Six VIX price-history
files are explicitly excluded from equity membership. Historical aliases and
the stray `Done` marker cannot inflate official index groups.

The scanner's old `stock_symbols_CSVs` path was missing and its category payload
was `{}`. Bootstrap and authenticated refresh now use the actual `Stock_Symbols`
path anchored to the repository. Existing UI consumes category options from DB;
no frontend rebuild or broker/order operation was needed. Backend restart is
needed to load changed refresh code in any already-running process.

New normalized symbol/category/membership tables and an import audit coexist
with the legacy scanner JSON projection; writes are atomic and preserve account
settings/snapshots. Repeatable CLI: `scripts/import_stock_categories.py` with
`--dry-run`, `--source`, `--database`, `--master-db`. Consistent pre-import backup:
`db/backups/stock-categories-20260929-213925-658850.db`.

All sector company names resolved; exact/explicit mappings are retained in the
audit. No fuzzy symbol guesses. Source effective dates remain unknown. Official
Nifty catalogues were checked, but constituent downloads failed/timed out even
after network approval. Smallcap 50, Microcap 250, Total Market and other absent
official lists remain unavailable; do not claim all current NSE indices imported.
See [category documentation](../../Stock_Symbols/README.md) for scope and SQL.

Verification: final focused importer/scanner suite **79 passed**, changed-file
Ruff checks and `git diff --check` passed. Independent readback verified all
11 index sets, all 56 JSON/relational membership sets and all 41 source hashes;
SQLite integrity passed with zero foreign-key errors. Account and lease tables
match the pre-import backup. All 200 name-only rows have recorded resolutions.
A deliberate wrong Kotak Bank mapping failed the dataset test as expected.
Authenticated refresh/CSRF behavior was exercised with Flask test fixtures;
no authenticated live browser/broker session or app restart was performed.
Preserve the pre-existing `skills-lock.json` edits and untracked agent skill
folders. No commit/push was requested or performed.

## Repository synchronization checkpoint — 2026-09-29

**Resumed September 29:** The interrupted merge is committed as `4a91191d5`.
A fresh fetch found one additional upstream commit, `fe6aa97831f69d302242b0d3679388207402aa2e`,
merged as `53245154e`. All 136 originally overlapping paths retain the saved
local versions; the second merge had no overlapping customized paths and no
conflicts. Existing local source edits and September 29 research outputs are
included in the portable snapshot commit that follows these merges.

Validation: 122 focused scanner, strategy, FYERS and migration tests pass;
frontend TypeScript checking and a production build into a private temporary
folder pass. The served `frontend/dist` was preserved. The tracked-file audit
found no case collisions or plaintext matches for local environment secrets;
local Git LFS integrity passed. No Mac or live broker execution was performed.

The refreshed snapshot is `portable-backup/latest/`: 13 settings/database
files in seven AES-GCM parts, all decrypt/hash verified. It includes both
September 25 and September 29 research candle databases. Its separate key is
`.migration-private/mac-restore-20260929-latest.key`; the earlier snapshot/key
remain valid for the earlier point in time. Use the latest snapshot for migration.
**Push completed:** `7fa72c7ea` was pushed to `main` at
`https://github.com/jilimudiManvitha/OpenAlgo_MVP.git`. Git authenticated as
`jilimudiManvitha` with write access. Git LFS uploaded all 228 unique objects;
an authenticated destination batch check confirmed zero missing objects and
zero errors. Git accepted the complete branch (two existing 50+ MB ordinary
Git files produced advisory warnings only). The working tree was clean. This
completion note is saved in a final follow-up documentation commit. The older
403 below is historical and resolved. The original origin remote is preserved.

The user authorized merging latest `marketcalls/openalgo`, preserving local code
when upstream overlaps, and pushing the complete portable project to
`https://github.com/jilimudiManvitha/OpenAlgo_MVP.git`. This is repository
maintenance; it does not resume frozen strategy tasks or place orders.

Local work, symbol CSVs, backtest ledgers, reports, the complete frontend build
and an encrypted installation snapshot are saved in commit `95e37d7e4` before
merging upstream `f72ad84408c0330e833c1b346bba4c46231edc19` (131 new commits).
The merge preserves every file changed on both sides, including the entire
local frontend build; 401 other upstream paths are accepted. The local startup,
Python lock, scheduler/shutdown customizations and navigation therefore take
precedence. Some new upstream features needing these skipped integrations,
including OpenScript runner registration/dependency, remain unavailable.

`portable-backup/` contains seven AES-GCM encrypted LFS parts and an encrypted
manifest covering 12 local settings/database files; decrypt/hash verification
passed for all 12. The recovery key is ONLY in
`.migration-private/mac-restore-20260929.key`; transfer it separately to the Mac.
See [Mac setup](../installation-guidelines/macos-local-fork.md).

**Earlier push blocker:** GitHub returned HTTP 403 because Git is
authenticated as `Narasimha722`, which lacks write permission to the requested
destination. The destination was verified public and empty. The user has been
asked to grant collaborator write access or authenticate an authorized account.
Preserve the existing origin remote; do not force-push or upload to another repo.
Final validation and LFS transfer results will be recorded below.

## Latest checkpoint — 2026-09-28: positive scanner basket, live paper strategy and app reports

The user's new request explicitly authorizes scanner performance/sorting changes,
the named strategy, its local paper schedule, and reports within the main app.
They confirmed **Rs 100,000 per trade**, not a portfolio cap. Original Crypto,
old backtest engines/results and the other frozen tasks remain untouched.

- Strategy: `strategies/Top_Gain_Volumes_Live_1L_stategy.py`, with English rules
  in the source docstring. Runtime: `strategies/top_gain_volumes/runtime.py`.
  The dynamic union is top 50 positive gainers plus top 50 positive RVOL>1
  shockers, using five completed sessions as volume baseline. Membership is
  rechecked at entry against fresh Quote ticks. Immediate forming-minute
  signal-high breakout retains HA/no-lower-wick, BB20x2, VWAP, signal-low-0.10,
  3R target and one trade/symbol/day. Newly selected stocks need complete warmup.
- Paper fills are a **dedicated simulated ledger**, not OpenAlgo Sandbox orders
  or live broker orders. Market fills include 5 bps adverse slippage and fees
  are an explicitly illustrative 5 bps/fill. No actual brokerage/tax claim.
  Reconnect/gap/overflow guards suppress entries; missing exit quotes leave
  positions marked unresolved. Broker Quote observations are not guaranteed
  exchange tick-by-tick data. Current-minute history bridges dynamic warmup;
  missing history is skipped/retried, never synthesized.
- Schedule is actually saved in `strategies/strategy_configs.json` for the
  existing FYERS account: NSE weekdays **09:15–15:10 IST**, exchange-calendar
  aware. Uses the existing scheduler; app and authenticated broker/proxy must
  be running. No forward session or orders were run today. Market-hours
  operation and observed end-to-end latency still need the next session.
  September 29 final verification found the user had changed the stop to 15:10.
  They explicitly confirmed **keep 15:10 and square off all stocks at 15:05**.
  Runtime, installer, English rules and UI now match. The saved September 28
  historical replay retains its original 15:05 F&O / 15:20 other-stock cutoffs;
  it is not relabeled as a backtest of the revised uniform cutoff.
- `uv run app.py` serves **/strategy-reports**, linked in navigation, Scanner
  and Python Strategies. Account-owned report APIs share the scanner blueprint.
  Report DB: `db/scanner_strategy_reports.db`. UI provides scenario-separated
  metrics, every trade's raw/HA chart, and **only a trades CSV download**.
  There is no new `show_report.ps1`, report server or user launcher. Historical
  artifacts in other folders are preserved. Internal resumable input cache is
  `db/scanner_backtest_cache/2026-09-28`; replay intermediates are temporary.
- Today's completed 15:25:12 IST scanner snapshot: 2,675/2,680 valid quotes,
  50 positive shockers + 50 positive gainers = **75 unique NSE EQ instruments**
  (master EQ classification includes some ETFs). All 75 processed; **60** have
  complete minutes through cutoff; **15** excluded. Two OHLC-path scenarios:
  OLHC 54 trades, 34 winners, gross Rs 79,013.63, fees Rs 5,426.936685,
  **net Rs 73,586.693315**, peak notional Rs 3,293,019.73. OHLC 54 trades,
  34 winners, gross Rs 79,125.59, fees Rs 5,427.029985,
  **net Rs 73,698.560015**, peak notional Rs 3,293,152.79. Do not add scenarios.
  Afternoon selection creates look-ahead selection bias for morning replay;
  this is not a causal dynamic-scanner historical backtest. Drawdown is based
  on realized exits, not intratrade equity. Source/history hashes and independent
  verification of all 108 scenario trades are stored in the report record.
- Scanner: bulk baseline read replaces per-symbol cache connections; warm
  scans avoid the duplicate quote pass. Backend tick merge runs every 0.5s,
  UI polls at 1s visible/10s hidden without blanking displayed rows. Stream cap
  defaults to 5,000 (actual acceptance/capacity still broker-dependent). New
  day-change/volume/RVOL ASC/DESC sorts apply before the top-50 limit, plus a
  positive-day-change filter. FYERS dedup and scanner merge now retain changed
  volume at unchanged price within the same timestamp second.
- Verification: independent saved-ledger verification **108/108**, original
  engine **16 tests**, scanner/report/runtime **97 tests** (including a VWAP
  guard mutation, account isolation, atomic run claim, unchanged-price volume
  ticks, sizing/exits and 150 report-DB resource cycles). Chrome checks with
  mocked auth/API and real saved report data cover desktop/mobile charts,
  scenario switching, CSV link, sorting and 1s refresh; screenshots inspected.
  Frontend production bundle rebuilt; changed-file lint checked. UI tests do
  not establish an authenticated live broker session or market-hours behavior.

Usage details: [strategy and reports](../../strategies/top_gain_volumes/README.md).
The older September 25 pending-upload checkpoint below is historical; it is
not the new dynamic strategy or the new schedule.

Updated: 2026-09-15, Asia/Kolkata. Status: Task 2 integrated and locally verified. The September 11 comparison of 404 versions and separate ETH experiment are complete. The four-selected-version full DuckDB run remains stopped and incomplete. The user authorized a separate January-June 2026 Nifty 50 run; see the current checkpoint. Other Task 1 work and Tasks 3-6 remain frozen.

This is the canonical plan for the user's six tasks from 2026-09-11. The task numbers below belong to this request; similarly numbered historical tasks in `context.md` are different work. Read this plan before resuming implementation. All future progress belongs in the checklist and handoff section here.

## Current checkpoint — 2026-09-25: today's scanner basket and paper deployment

The user requested the same `narasimha_pc_backtest` strategy on today's volume
shockers/top gainers, explicitly **today's session only**, followed by upload and
scheduling in **paper mode at http://127.0.0.1:5000**. This authorizes the isolated
new folder and paper deployment; the original engine, old results, main source DB,
application and Crypto code remain unchanged. Other frozen tasks stay frozen.

Work is in [today's package](../../narasimha_pc_backtest/today_20260925/README.md).
The completed local scanner snapshot was frozen at 15:19:11 IST: 50 shockers,
50 gainers, 80 unique NSE EQ instruments (including EQ-classified ETFs). Original
snapshot coverage: 2,660/2,668 quotes. A first selection made during baseline
loading is retained as superseded, not used in the result.

Fresh FYERS history was downloaded to this isolated folder with 30 calendar days
of warmup and refreshed after the non-F&O square-off. September 25 only replay:
59 eligible instruments; 21 excluded for incomplete minutes. Both modeled paths
produce 53 trades / 38 winners, gross after slippage Rs 151,543.00, fees
Rs 5,368.06, **net Rs 146,174.94**, 71.70% win rate. Peak simultaneous entry
notional Rs 2,496,614.35 across 25 positions. Volume-shocker net Rs 75,093.32;
gainer net Rs 145,845.61; group overlap means these must not be added.
This afternoon-selected morning replay has selection bias and is not a causal
dynamic-scanner backtest. One-day daily-close drawdown does not measure intraday DD.

Verification: all 106 saved path trades pass the independent verifier, all 16
original engine tests pass, and seven paper tests pass including a VWAP-guard
mutation and target-fill/cancel race. Actual Chrome chart/mobile checks pass;
screenshots inspected. Initial verifier failure was missing pre-session warmup in
the exported candles; `verify_today.py` supplies it and proves all current-day
indicators match. No fills or strategy calculations were changed. Report is
served separately at **http://127.0.0.1:8783** (check before starting a duplicate).

Paper package prepared: `narasimha_scanner_paper.py` imports the isolated runtime.
It uses only local sandbox order services, a fixed 80-instrument basket, observed
quote candles, durable state, one entry/day, target LIMIT and reconciled software
stop/clock exits. Proposed NSE schedule: weekdays **09:00–15:25 IST**, with the
exchange calendar, starting on the next eligible session. Warmup must finish
before 09:15; late starts and feed gaps suppress entries. Paper quantity has a
small fill buffer; sandbox fills/costs differ from the backtest assumptions.
Review the README's runtime limitations before interpreting forward results.

**Upload/schedule still pending at this checkpoint.** OpenAlgo stopped during
work; the user restarted it. The stored API key verifies locally, but there is no
active FYERS auth session, causing the history API's generic 403 "Invalid openalgo
apikey" response. Do not regenerate the valid key. A real Chrome window opened
by `deploy_browser.cjs` is waiting for the user's normal OpenAlgo/FYERS login.
Never fabricate a session or bypass auth/CSRF. `deployment_plan.json` describes
the concrete intended upload; `READY_TO_UPLOAD.json` has NOT been created.
After user login: run `check_connection.py` (read-only history/WS probe), then
copy the plan to the readiness file for the waiting uploader, verify the resulting
`deployment.json` and the authenticated `/python/api/strategies` schedule, and
update this checkpoint. If the browser was closed, rerun `deploy_browser.cjs`.
No live or paper orders have been submitted. No global Analyzer setting changed.
Actual market-hours forward execution remains unverified.

## Launcher rerun — 2026-09-25, 14:15 IST

The user explicitly requested running `narasimha_pc_backtest/run_backtest.ps1`.
Completed all 50 symbols with unchanged default settings in 24.30 seconds,
exit code 0, saving to `narasimha_pc_backtest/output_rerun_20260925_141503/`
to preserve existing results. PowerShell initially blocked script execution;
the approved retry used a process-only execution-policy bypass.
The saved manifest is `COMPLETE_AVAILABLE_DATA`, the HTML report exists,
and the complete `trades.csv` SHA-256 matches the prior completed run.
OLHC net is -Rs 10,738,312.61 (56,701 trades); OHLC net is
-Rs 11,287,881.21 (57,239 trades). No strategy code was changed.
The earlier report server was not restarted or redirected to this output.

## Latest checkpoint — 2026-09-25: new Nifty 50 HA buy strategy completed

The user supplied `strategy_buy_doc_.txt` and explicitly requested use of the
local five-year one-minute DuckDB, HA conversion, backtest and dynamic charts
in `narasimha_pc_backtest/`. They confirmed the ambiguous entry wording means
both HA candles have no lower wick, upper wicks are optional, and breakout is
above the upper Bollinger Band and VWAP. The final paragraph requesting the
backtest now supersedes the file's initial code-only sentence. This authorizes
only the new isolated strategy, not resumption of the old stopped experiments
or other frozen tasks. Original application/strategy/Crypto code is preserved.

**Completed available-data run:** [code, results and commands](../../narasimha_pc_backtest/README.md),
[complete strategy rules](../../narasimha_pc_backtest/STRATEGY.md),
[interactive report](../../narasimha_pc_backtest/output/index.html).
The new PC source is `db/historify.duckdb` in this F: workspace, not the old
D: paths. This extracted working folder has no `.git`; no commit/push occurred.

All 50 exact symbols in `nifty50_symbols_For_HistoricData.txt` were processed:
22,977,386 source rows, 22,964,861 valid regular-session rows converted to HA
in separate compressed Parquet files. Requested September 25, 2021–September
25, 2026; eligible trading sessions actually span September 27, 2021–September
24, 2026. Today's source stops around 12:27–12:40 IST, so all September 25
sessions are excluded. JIOFIN starts August 21, 2023 at 09:55. Coverage records
60,830 eligible stock-days, 363 incomplete stock-days, 188 days excluded due
to 192 invalid regular-session OHLC rows, and 469 absent symbol-days against
the union of source dates. Out-of-session rows: 12,333. Invalid rows are saved
without repair; source SHA-256 is unchanged before/after and during verification.

Fixed buy-only HA1m/BB20x2/raw-session-VWAP rule, ₹100,000 per trade, one trade
per stock/day, signal HA low −₹0.10 stop and 3R target. Both OLHC and OHLC
modeled price paths use causal forming-candle prices; final volume is uniformly
distributed as an explicit approximation. Entry does not use the future final
wick state. Current-master ticks/F&O classification, 5 bps market slippage and
5 bps flat fee per fill are research assumptions, not historical broker facts.
All 50 are currently classified as F&O (15:05 square-off). Historical index/FO
membership, adjustment policies, funded-account limits and intraday drawdown
are not reconstructed. See the exact limitations in the strategy document.

Results under those costs: OLHC 56,701 trades, gross after slippage
−₹5,124,372.21, fees ₹5,613,940.40, net **−₹10,738,312.61**, win rate 24.63%.
OHLC 57,239 trades, gross −₹5,620,915.39, fees ₹5,666,965.82, net
**−₹11,287,881.21**, win rate 23.87%. Both paths lose; never add their P&L.
Fixed allocations continue after losses, so this is not a funded cash account.
Execution/conversion/report time was 23.62 seconds using four Numba CPU
workers; no GPU needed. Output is about 1.40 GB.

Verification: independent saved-ledger checks on all 113,940 trades pass;
synthetic/integration tests, named scenario parity and actual Chrome browser
checks are saved in the module artifacts. Browser charts/filters/HA/raw toggle/
mobile view pass with zero page errors and screenshots inspected. 128 versus
32 entry samples/leg produce identical trade selections, with small near-tick
P&L differences (+₹2.90 OLHC / +₹6.20 OHLC). Daily-limit mutation is caught;
121 success/exception DuckDB lifecycle cycles retain 600 handles after warmup.
Execution-code hashes match the completed-run manifest; tests/docs added after
that run have a separate final delivery/verification record.

Local report server started at `http://127.0.0.1:8782`; verify it is running
before starting a duplicate. Restart with
`& .\narasimha_pc_backtest\show_report.ps1`. It reads generated artifacts only.
`output/` is final; `smoke_output/` and `rejected_initial_run/` are preserved
diagnostic runs, not final results. Reruns require a new empty output folder.
No automatic source download or future September 25 completion is scheduled.

## New request checkpoint - 2026-09-17: selected-symbol Bollinger alerts

The user requested alerts when selected stocks or crypto cross the upper or
lower Bollinger Band. This is a new alert-only request, not a resumption of
the frozen strategy/backtesting tasks. Existing application/Crypto boundaries
are preserved: implementation is isolated under
[.development/bollinger-alerts](../../.development/bollinger-alerts/README.md).
No original application, broker, strategy or backtest code was modified.

Delivered a separate localhost dashboard, saved per-connection watches,
live-tick and completed-candle modes, configurable timeframe/period/deviation,
upper/lower/both selection, browser sound opt-in, pause/resume, SQLite alert
history, duplicate suppression, warmup/reconnect handling and stale-data states.
It uses each existing OpenAlgo host's history API and WebSocket LTP stream;
stock and crypto keys/hosts remain separate. No orders or external messages
are sent. Default settings are 5m, SMA 20, 2 population standard deviations,
ordinary close prices, live crossing, both bands and browser alerts. Optional
questions about timing/settings/delivery were sent; no answer was recorded
during implementation, so both trigger modes and editable settings were built.

Verification: 13 synthetic Python checks, Ruff, and eight Chrome desktop/mobile
checks pass with no page errors; screenshots inspected. Startup/reconnect does
not replay historical crossings; at most one alert per band per candle. Gaps
and delayed broker history at candle boundaries can miss crossings. Full
nominal durations determine candle completion, including shortened end-session
candles; all exact rules and limits are in the module README.

**Not activated or integrated into the main OpenAlgo UI.** User-selected symbols,
actual connection URLs/API keys and live stock/crypto adapter verification remain
pending. `.env.example` contains empty key fields and example ports; credentials
must be set locally. No credentials were read/copied and no real watch was
created. Start with `.venv/Scripts/python.exe .development/bollinger-alerts/server.py`
and open `http://127.0.0.1:8781`. No Telegram/WhatsApp delivery is implemented.
Preserve existing unrelated working changes. Nothing was committed/pushed.

## Repository synchronization - 2026-09-16 (historical)

The user requested committing and pushing all current repository changes to
`origin/main` (the private `openalo_indian_markets_mvp` repository). This includes
the portable crypto package and locally present `results_full` reports, selected
four/Nifty configurations, skills and notes. Large one-minute candle CSVs use
Git LFS; new clones need Git LFS installed and `git lfs pull` to retrieve them.
SQLite journals/shared-memory files and the crypto runtime writer lock are
excluded, along with existing ignored databases, credentials and environments.
This synchronization does not rerun or independently validate the backtests,
change the frozen task scope, or restart any process. The September 15 execution
checkpoints below remain historical; inspect current output before resuming work.

## Current checkpoint - 2026-09-15: portable four-crypto code delivered

The user requested **code only for the new PC**, without interrupting the Nifty
run: convert BTCUSD/ETHUSD/SOLUSD/XAUTUSD trade CSVs to 1m/5m HA candles and
backtest S029/S104/S232/S344 across all supplied years. Hardware supplied:
i9-14900F, 32 GB RAM, RTX 4070 Ti Super 16 GB. No full crypto replay was launched
here. The original Crypto tree remains read-only; existing engines are unchanged.

Delivered [portable package and instructions](../../backtesting/crypto_four_portable/README.md)
and `backtesting/crypto_four_portable/crypto_four_portable.zip`. The main file
`crypto_backtest.py` is standalone; dependencies, Windows installer/run scripts,
synthetic tests and verification evidence are bundled. Four bounded-memory CPU
workers are the new-PC default; GPU is unused. DuckDB imports/sorts in a separate
output cache, while Numba streams causal raw/HA/BB/VWAP calculations and the four
exact no-trailing/no-partial strategy configurations. Fills use source trades,
not HA prices. All 16 coin/strategy ledgers, candles, daily P&L, CSV/HTML comparison
and source audits are exported. Exact file copies are deduplicated by content
hash; ambiguous timestamps and non-identical overlapping exports are rejected.

Read-only inventory found ~19.4 GB of uncompressed content including duplicate
copies: real CSVs contain complete microsecond timestamps, SOL has archive and
extracted duplicates, ETH has some 2026 copies under 2024, and XAUT `.csv` files
are actually ZIPs. Date-folder names are not trusted. No full-source scan or
historical result was produced for this request. S029 and S232's earlier ETH
P&Ls are **negative** (-$6,788.67 and -$2,833.53); corrected in the guide.

Verification: 13 synthetic tests passed from an extracted standalone ZIP;
two-worker CLI exercised all four coins / 16 results, completed-coin resume and
the separately labeled benchmark mode. All 56 fills and MTM marks on 12,000
stored ETH events per timeframe match the prior engine. HA/BB/VWAP match the
original Maker on 1,200 synthetic ticks including midnight. Runtime/test evidence:
`reference_validation.json` and `package_validation.json`. Ruff passed for the
delivered main program and tests. The full new-PC run remains the user's action.

Planning estimate: 30-90 minutes on the new PC with SSD, excluding setup/transfer;
unmeasured and storage-dependent. Benchmark mode imports all data then samples
the first million sorted trades per coin and prints measured import plus projected
replay time. Interrupted file imports are cached; an interrupted coin's strategy
replay restarts from its beginning. Completed coins are skipped with matching
inputs/settings/code. Fees, 0.01 base-asset step and $100,000 notional are research
assumptions; funding, liquidation, broker multipliers and taxes are excluded.

Nifty job was not stopped/restarted by this task. At ~18:27 IST the active Nifty
command is `run_selected_four --config .../nifty50_2026_h1.json --resume`, launcher
PID **21592**, worker **7096** (earlier recorded PIDs are stale). Latest inspected
log committed May 19 and was processing May 20. Inspect actual current processes
and committed days before any future action; this task did not cause that restart.

## Previous checkpoint - 2026-09-15: four selected versions, Nifty 50, January-June

The user reduced the experiment to four strategies on Nifty 50 stocks from
January 1 through June 30, 2026 inclusive. This authorizes the separate smaller
run; the full-history output remains stopped and preserved. Versions stay S092,
S109, S299 and S305. Rules, both modeled paths, fees/slippage, warmup and
VectorBT reconciliation are unchanged.

Read-only audit of `stock_symbols_CSVs/ind_nifty50list.csv` found 49/50 stocks:
BAJAJ-AUTO is absent in this date range, with no matching alternate BAJAJ
symbol. Each available stock has 45,000 minute rows; total 2,205,000 rows on
120 source dates, January 1-June 30. An optional question about filling the gap
received no answer before launch; announced default is the available 49 with
BAJAJ-AUTO explicitly excluded. This is a fixed local basket, not reconstructed
historical membership. Do not silently substitute a different company.

`nifty50_2026_h1.json` freezes the date range, four IDs, 49 symbols and exclusion
note. `run_selected_four` now accepts `--config` and rejects other strategy sets;
its default full-history configuration is preserved. Audit/CLI imports and
selected definitions were verified; Ruff passed. No execution-engine code changed.

Background run launched at about 13:15 IST, launcher PID **17580**. Inspect
`backtesting/ha_bb_vwap_allstocks/nifty50_2026_h1_output/process.json`, logs,
manifest and committed SQLite days before any restart. Do not start a duplicate
writer. Launch is not completion; final ranking and runtime remain pending.
The wrapper generates final findings automatically only after all days commit.

[Scope, assumptions and commands](../../backtesting/ha_bb_vwap_allstocks/NIFTY50_2026_H1.md).
Resume only after verifying the prior writer stopped:
`& backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks.run_selected_four --config backtesting/ha_bb_vwap_allstocks/nifty50_2026_h1.json --resume`.
No dashboard was launched. Optional dashboard port is 8779.

Runtime check at approximately 13:58 IST: launcher 17580 and Python worker
5220 are alive, error log empty. Read-only SQLite check confirms **14/120 days
committed through January 21**, 686 stock-sessions tested, none skipped.
Elapsed time is 42.8 minutes since launch; manifest was written at 13:16:31 IST.
Observed replay averages about 2.9 minutes per source day. Linear projection is
about 5.2 hours remaining; communicate roughly 5-6 hours (around 19:00-20:00 IST)
if speed stays similar and the machine remains awake. This is an estimate,
not completion or a strategy-performance conclusion. No restart was performed.

## Previous checkpoint - 2026-09-15: four selected versions on full DuckDB history

**Stopped by user:** after requesting a runtime estimate, the user explicitly
said "stop this backtesting task". Verified selected-four Python worker PID
3796 and launcher PID 5820 were stopped and confirmed absent. The restarted
run last logged 50/778 stocks on 2017-07-03; no full day had committed.
Existing output/checkpoints, logs, configuration and source data are preserved;
`selected_four_output/process.json` records `stopped_by_user` and stop time.
Do not automatically resume this run or launch a replacement. The launch and
restart details below are historical, not evidence of a currently active job.

The user requested full DuckDB historical backtesting of the four group leaders
from the 22-stock September 11 comparison. Optional questions about stock scope
and the sell-5min tie received no answer before launch; announced defaults are
all available NSE stocks and S305 (10R), the prior representative of 26 tied
sell-5min variants. The selection is S092 buy-1m 6.5R, S109 buy-5m 13R,
S299 sell-1m 9R, S305 sell-5m 10R. Other tied variants are not included.

Read-only actual-row inspection found 1,576 NSE symbols, 859,729,779 minute
rows, and source timestamps spanning 2017-07-03 through 2026-09-11. The new
`backtesting/ha_bb_vwap_allstocks/selected_four.json` includes this final date
(the older run stopped at September 10), selects only these four versions and
writes separate `selected_four_output/` results. Both modeled candle paths,
Rs 100,000 per-stock allocation, existing costs/slippage and original strategy
factories are preserved. September 11 is both selection day and part of this
retrospective comparison; it is not independent prospective validation.

The old 404-version runner had stopped before this request: two of 2,280 days
were committed, through 2017-07-04. Its output is preserved. The four-version
run started at 12:38 IST and reached 275/778 stocks of the first day. The user
then explicitly requested **restart**. Only this job's verified Python PIDs
8256/20984 were stopped; the job restarted with `--resume` at 12:53 IST,
launcher PID **5820**. No full day had committed, so July 3 must replay.
Inspect `selected_four_output/process.json`, `run.log`, `run.err.log`, manifest
and SQLite committed progress before any further launch. No duplicate writer.

The new `run_selected_four` wrapper invokes the existing runner and builds the
comparison only when all planned days are committed. Exact selection/config
and CLI imports were checked; no engine code changed. Actual historical replay
began before restart with no logged errors. Completion and final performance
remain pending; do not promise an overnight runtime. Source data/application/
Crypto and unrelated working changes are preserved.

Commands, reporting assumptions and resume details:
[Selected-four guide](../../backtesting/ha_bb_vwap_allstocks/SELECTED_FOUR.md).
From repository root, resume only after the prior writer stops:
`& backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks.run_selected_four --resume`.
Dashboard: `& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks serve --config backtesting/ha_bb_vwap_allstocks/selected_four.json --port 8778`.
No dashboard server was started in this session. Final report will be
`selected_four_output/comparison/index.html` after completion.

## Previous checkpoint - 2026-09-13: separate ETHFUT 24/7 experiment

The user explicitly authorized all 404 existing strategy versions on only
`D:/Personal/OpenAlgo_Crypto/historical_data/ethfut`, without entry/exit time
restrictions, and instructed that the running all-stock job must not be interrupted.
This expands authorization for this isolated experiment only. Crypto remains read-only;
the original strategy package, all-stock runner/output and other frozen work are preserved.

Implementation is isolated in [backtesting/ethfut_404](../../backtesting/ethfut_404/README.md).
The two supplied archives contain 518,675 ETHUSD trades covering April-May 2024;
2025/2026 folders have no files. Source audit records both SHA-256 hashes, 223 gaps
over five minutes and a largest gap of 6,234.49 seconds. UTC timestamps, UTC-midnight
VWAP, USD 100,000 fixed notional, 0.01 ETH increments, 0.05% fee per fill and 0.05%
adverse slippage are disclosed research assumptions. Funding/tax/FX/margin are absent.
Signals and positions carry across midnight; only the end of the supplied data forces
liquidation. Actual trades form causal 1m/5m snapshots; no interpolated OHLC paths.

**Completed:** all 404 versions finished at 11:53 IST, and final verification
subsequently passed. [Offline report](../../backtesting/ethfut_404/results/index.html),
[written findings](../../backtesting/ethfut_404/results/report.md) and all 404
trade/fill/daily CSV sets are available. Four tests passed in 206 seconds:
all-404 compiled/reference parity on the first 12,000 real observations per timeframe,
midnight carry, stale-signal gap rejection and final liquidation. Ruff, Python
compilation and browser-script syntax checks pass. All 404 full-history fill ledgers
reconciled independently with VectorBT. A separate saved CSV verification matched
all 308,920 fills to actual source timestamps/prices plus slippage and reconciled
153,656 trades, fees and daily P&L. It counted 5,211 overnight trades and 114,379
entries outside NSE hours; source hashes are preserved. Offline Chrome verified
404 rows/choices, eight chart selections, filtering and local links, with zero page
errors; screenshot inspected. Evidence is under `results/` in `tests.txt`,
`validation.json`, `verification.json` and `browser-verification.json`.

Only 25/404 versions were profitable after modeled costs: 14 buy-5m and 11 sell-5m;
all 1m variants lost money. Group leaders: buy-1m S029 -USD 6,788.67; buy-5m S104
+USD 12,030.83; sell-1m S232 -USD 2,833.53; sell-5m S344 +USD 3,523.78. S104 uses
RR 10.5, 0.10 buffer, no trail/partial/indicator exit; 95 trades, 11.58% wins,
USD 22,530.45 maximum MTM drawdown. Its largest winning trade contributed
USD 11,951.21, leaving only USD 79.62 across all other trades. ETH buy-and-hold
netted USD 3,069.48. Rankings are retrospective across two months and exclude
funding/tax; they do not establish a deployable edge.

The all-stock PID 11620 was still active with its original 11:08:24 start time and
2,750.25 cumulative CPU seconds at the final operational check; no duplicate
all-stock writer was started or process stopped. The ETH run and its verification
processes have finished. Reproduction and assumptions are in the ETH README.

## Previous checkpoint - 2026-09-13: all-stock DuckDB runner and dashboard

**Latest full-completion request (2026-09-13, about 11:27 IST):** the user asked to complete the whole backtest and explain which strategy worked well. The existing run remains active (tool session 71726); the latest logged stock checkpoint is 25/778 stocks for 2017-07-03, with **0/2,280 full days committed**. No full-history winner exists yet. The first 25 stock-sessions took roughly eight minutes; the source has 859,377,449 minute rows. This serial baseline cannot reasonably complete the whole experiment within one interactive session. A bounded read-only profile of 20MICRONS/2017-07-03, all 404 versions and both paths, is recorded under `artifacts/throughput-profile.{json,txt}`. Repeated strategy snapshot validation dominates replay; its 43.9-second profiled duration includes profiler overhead, concurrent execution and more accumulator construction than production, so do not treat it as a full-history ETA. That sample generated zero trades and is not performance evidence. At this checkpoint the active result WAL was approximately 44 MB and about 75 GB remained free on D:; full retention/throughput scaling is not established. Do not claim completion or promise an overnight result.

Added `backtesting/ha_bb_vwap_allstocks/comparison.py`: read-only completion checks and final all-version/group rankings by lower-path net profit and lower-path net / larger-path MTM drawdown. It preserves ties, excludes versions unprofitable on either path from leader selection, shows yearly consistency, costs, capital and configuration, and exports HTML/Markdown/JSON plus ranking/path/year CSVs. Missing source days or strategy/path daily rows refuse final ranking; synthetic fixtures stay labeled. Three new focused comparison tests pass; Ruff passes. Core run fingerprint is unchanged. A completion watcher is active in tool session **64060**, started with `& backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks.comparison --watch`. It polls committed progress and writes `output/comparison/index.html` and companion files only when all planned days finish. It does not make the replay faster, restart a failed runner, or imply completion; if the environment stops, resume the runner and restart the watcher explicitly. No historical comparison output exists at this checkpoint. Application/strategy/source data remain unchanged.

The user first requested code only for all-stock history and then explicitly requested: "do backtest on all stocks ,tell how can i run this backtest code .give cmd to run ." This authorizes the historical run of the 404 existing HA/BB/VWAP versions, superseding the earlier freeze for this specific experiment. It does not resume unrelated frozen features or authorize live orders. Implementation is isolated in [backtesting/ha_bb_vwap_allstocks](../../backtesting/ha_bb_vwap_allstocks/README.md); source strategies, the application, Crypto and source market data are preserved.

**Delivered code:** a read-only DuckDB reader, bounded stock-session replay of the actual strategy factories, VectorBT fill reconciliation, atomic daily SQLite checkpoints and resume fingerprint checks, and a localhost interactive dashboard. Defaults select all available NSE source symbols, both buy/sell directions, 1m/5m strategies, two modeled minute paths, and 2017-07-03 through 2026-09-10 inclusive. Reports cover day/week/month/quarter/half-year/year/five-year/full-period P&L, brokerage/itemized costs, peak and average simultaneous notional, win/loss averages and extremes, win rate, profit factor, cross-day bar-close MTM drawdown, trade counts and exact modeled time position lookups. Every retained trade has an on-demand full-session red/green candle chart; CSV exports stream from the indexed results store.

**Verification:** nine synthetic unit/integration tests passed, including actual engine replay against invented DuckDB data, VectorBT reconciliation, source preservation, daily rollback/resume, cost dates, cross-day drawdown and partial-exit lookups. Ruff and JavaScript syntax checks passed. Headless Chrome passed all eight report groupings, time lookups, partial positions, trade charts, CSV export and honest no-results state, with zero page errors. Evidence: `backtesting/ha_bb_vwap_allstocks/artifacts/browser-verification.json` and screenshots. `demo_output` is explicitly synthetic and must not be quoted as historical performance.

**Run checkpoint:** the real command `backtesting/.venv/Scripts/python.exe -u -m backtesting.ha_bb_vwap_allstocks run` was launched on 2026-09-13. DuckDB opened and fingerprinted successfully (SHA-256 `dd1137b22956d148e4efa6e0c4532cd6f1c651fe1729c811fb5f36ad32b61e02`). The manifest selects 1,573 source stocks and 2,280 source dates, 2017-07-03 through 2026-09-10. The runner began `2017-07-03: 778 source stocks, 404 strategies`; output manifest and SQLite/WAL files exist. This checkpoint does not yet establish a completed historical day or performance result. The agent tool session is 71726; do not start a duplicate writer if it is still active. Inspect `backtesting/ha_bb_vwap_allstocks/output/manifest.json`, `results.sqlite` and the dashboard for committed progress on restart. Resume only after the prior process has stopped, using `run --resume`; an interrupted day is replayed while committed days are retained. Full-history runtime and storage have not been benchmarked.

**Commands from repository root:** `& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks run`; resume with `run --resume`. In another terminal: `& backtesting/.venv/Scripts/python.exe -m backtesting.ha_bb_vwap_allstocks serve`, then open `http://127.0.0.1:8777`. README documents configuration, chunked runs, source locks/WAL handling and historical overrides. Never delete a source WAL or stop the live application to bypass source access errors.

**Interpretation:** all stocks means all NSE symbols present in the configured source, not proven exchange-universe completeness. Fixed research fee rates and current local tick/F&O metadata are used unless effective-date CSVs are provided. Gross notional is not broker margin; independent Rs 100,000 stock allocations do not form a constrained shared-capital portfolio. The two interpolated candle paths, finite warmup, source gaps and missing corporate-action reconstruction limit historical conclusions. Earlier checkpoints below describe prior authorizations and are superseded only within the explicitly expanded scope above. Preserve unrelated local/staged changes, including the user's report extraction and text files.

## Previous checkpoint - 2026-09-13: bounded CSV strategy comparison complete

**Capital/risk follow-up (2026-09-13):** the user asked for total brokerage, capital used/maximum used, trade count, max drawdown, max profit/loss and trades open at a particular time. Added `capital_report.py` using the existing frozen fill ledgers and retained bar-close marks. No strategy rerun or trade changes. [Capital/risk overview](../../backtesting/ha_bb_vwap_v1_20260911/results/capital_overview.html) links 404 reports with separate OLHC/OHLC paths and an IST time picker listing open stocks/quantities/capital. New CSVs: 808 capital/risk rows, 37,993 exact modeled fill-time/boundary states, 182,608 bar-close MTM states, 41,802 fill-level brokerage/exchange/SEBI/STT/stamp/GST breakdowns. Reports distinguish allocated capital, cumulative reused entry notional, peak simultaneous notional, biggest individual win/loss and session MTM extrema; peak capital/concurrency and drawdown peak/trough times are recorded. All 808 fee/peak-notional/drawdown values reconcile with prior reports. Three focused accounting tests and 40 headless-browser time lookups passed; screenshot inspected. Example S092/OHLC: brokerage Rs 1,080, total charges Rs 2,246.44, peak notional Rs 898,563.25 and 9 open trades at 10:51 IST; largest winning/losing trade Rs 18,021.12 / -6,217.90. The ZIP and reproduction pipeline include the addition. Margin is not modeled; MTM remains bar-close rather than tick-complete. Broader frozen tasks remain frozen.

The user's later request, repeated with "retry", explicitly authorized backtesting every existing module in `strategies/ha_bb_vwap_v1/versions` on September 11, 2026: buy on `GainersOn11092026`, sell on the actual `LoosersOn11092026` folder. This supersedes the earlier code-only/no-backtest instruction for this bounded experiment only. The original strategy package, application, Crypto tree and source CSVs were preserved. Broader historical/DuckDB runs, live deployment and Tasks 3-6 remain frozen.

**Deliverable:** [backtesting/ha_bb_vwap_v1_20260911/results/index.html](../../backtesting/ha_bb_vwap_v1_20260911/results/index.html), with [written findings](../../backtesting/ha_bb_vwap_v1_20260911/results/findings.html), all 404 strategy reports and **20,783 distinct trade chart pages** spanning 09:15–15:30 IST, green/red HA candles, raw-price toggle, completed signal, entry/partial/exit markers, stop/target/trailing levels and relevant indicators. Forty-four shared candle assets plus local Plotly make the report offline. This tests 101 actual files per direction/timeframe, not the 6.9 million generated Cartesian combinations.

**Execution assumptions:** 22 supplied stocks, two explicit intraminute OHLC paths, 8,888 strategy-stock-path runs. Ten forming observations per minute interpolate O-L-H-C or O-H-L-C; uniform volume accrual is assumed. No reply arrived to the optional execution/cost questions, so the announced defaults were retained. The actual strategy factories consume causal OpenAlgo indicators; fills use real modeled prices plus 5 bps adverse slippage, adverse tick rounding and itemized estimated Zerodha NSE intraday charges. Whole-share entries stay within Rs 100,000; each 11-stock basket uses Rs 1,100,000 reference capital. Tick size/F&O cutoffs use the adjacent-date local master. Target 5m bars reaggregate supplied 1m and matched every overlapping 5m source; up to 600 prior bars initialize indicators. These are candle-path sensitivity estimates, not tick-accurate or exhaustive worst-case outcomes.

**Observed leaders by lower-path net P&L:** buy 1m S092, 6.5R, Rs 57,718.69–58,489.59 (27 trades/path); buy 5m S109, 13R, Rs 43,439.56–43,559.62 (9/path); sell 1m S299, 9R, Rs 14,272.30–14,491.07 (17/18); sell 5m S305, 10R, Rs 7,181.03–7,182.24 (13/path). All displayed leaders use 0.10 stop buffer, no trail/partial/indicator exit. Sell 5m has **26 tied RR 8–20.5 variants**, because no fixed target was hit. S092 has the highest profit; S109 has much lower observed drawdown (Rs 4,660.67 versus Rs 12,908.60). None beats the corresponding hindsight-selected open-to-cutoff basket reference. Concentration, default-version comparison and exit attribution are in written findings. One preselected day does not establish an edge or authorize deployment.

**Verification:** 63 strategy/replay tests passed; Ruff clean. VectorBT `from_orders` independently reconciled all 8,888 fill ledgers. Separate file verification checked 20,783 trades, 41,802 fills, dates/cutoffs, notional/quantity/tick constraints, no overlapping same-stock positions, all report totals and all 44 input SHA-256 hashes. Every trade page and script dependency exists. Headless Chrome verified all 404 strategy rows/search and 12 representative chart cases across direction/timeframe/path, partial exits and oscillators with no page errors; screenshots were visually inspected. Evidence: results/{validation,verification,browser-verification}.json and example PNGs. Browser/process/file lifetimes close on completion; no server or broker session was started.

**Limitations:** ASHOKAMET/DIGJAMLMTD/LADDERUP lack prior history; ASHOKAMET and KIRLOSIND have missing minute bars. Many bars have zero volume/flat prices. New entries on zero-volume minutes are rejected, but participation/circuit/exit liquidity is not modeled. F&O membership, corporate-action adjustments and real order-book execution are not historically reconstructed. Slippage/fees are estimates; drawdown is bar-close MTM. NIFTY input is absent and annualized metrics are omitted for one session. Preserve `task.txt` edits and any concurrent repository checkpoint commits.

Reproduce with `backtesting/.venv/Scripts/python.exe backtesting/ha_bb_vwap_v1_20260911/batch.py`; see its README for report-only and verification commands. Completed stock checkpoints are local, trusted pickle files, excluded from version control. They reject changed engine/harness fingerprints; changed data, definitions or metadata require a new output directory. Initial PINELABS smoke is preserved separately and excluded from final reports. Do not silently reuse this experiment for other dates or relabel the frozen wider tasks as completed.

## Previous checkpoint - 2026-09-12: Task 2 integration; other tasks frozen

Strategy-update/code-only milestone (2026-09-12): the user requested executing the instructions in `strategy_buy_doc_.txt` and `strategy_sell_doc.txt`. Both explicitly request code/documentation now and defer backtests/forward tests. Added the separate `strategies/ha_bb_vwap_v1/` package: broker-independent causal snapshot/intent/fill engine, `openalgo.ta` indicator adapter, 404 separately named strategy modules with 404 six-section documents (101 per buy/sell x 1m/5m), manifest and lazy generator for 6,918,660 full Cartesian configurations. The millions of full-product files are NOT all materialized; `generate --all --offset ... --limit ...` can produce any range. Three optional clarification questions received no answer while work proceeded: documented defaults are separate listed variants plus full generator, short SL at signal HIGH + buffer, and trailing distance as a percentage of target PROFIT distance with a breakeven clamp. README records other wording corrections (short sell entry, RSI >40 short exit, directional MACD, completed entire-OHLC exits), alternatives and integration limitations. Forming candles are required for intrabar entries; final-only HA CSVs do not prove event order. An execution adapter must supply actual completed fills; no broker integration, order, market-data backtest or forward test was run. **59 synthetic tests passed**; all 404 generated modules imported and matched their configs/docs; combined-configuration generation verified; Ruff clean. Evidence: package `validation.json`. The user's Task 1 strategy update has now been received and authored in this isolated package; historical/full-DuckDB testing and Tasks 3-6 remain frozen. Preserve the earlier shutdown changes and all user text-file edits/deletions.

Shutdown follow-up (2026-09-12, after the reported `MIS Square-off Backup Check` traceback): the earlier fix covered only two of the six application APSchedulers. `utils/shutdown.py` now also stops already-loaded sandbox square-off, Chartink, Flow and Historify schedulers; failures are isolated and disabled services are not imported/started during exit. Sandbox shutdown now drains outside its application lock and clears only its in-memory jobs; Chartink does likewise. Flow/Historify shutdown is idempotent, waits for active jobs and preserves persisted schedules (verified by reopening separate SQLite job stores). All six scheduler owners are covered by real-thread lifecycle checks. Verification: **84 focused tests passed**, no new Ruff findings, compilation/diff checks passed; **100 shutdown cycles for each of six schedulers** retained exactly **147 handles / one thread**, zero thread exceptions. Pytest still emits its separate captured-stream logging message at interpreter exit; no app/broker restart was performed. Preserve concurrent `task.txt` / `strategy_doc.txt` changes. Frozen feature tasks remain frozen.

Standalone shutdown fix (2026-09-12, explicitly requested): `utils/shutdown.py` now stops the already-loaded strategy-module and Python-host schedulers before health/session teardown. `app.py` runs that idempotent cleanup in a `finally` around `socketio.run()`, covering return, exception and reloader exits before the interpreter's executor exit hook. Both scheduler shutdown functions pause and clear in-memory jobs before `shutdown(wait=True)`; application locks are not held while workers finish. Python-host `cleanup_on_exit()` also stops its scheduler before subprocess cleanup as a fallback. This fixes the dev-server lifecycle; production hosting and hard process termination were not exercised. Verification: 73 focused graceful-shutdown/scheduler/Python-stop tests passed; all changed Python files compile; no new Ruff findings (app.py's import-order finding at line 47 already exists in HEAD). A 100-cycle-per-scheduler audit held 147 Windows handles and one thread before/after, with zero thread exceptions and 31,038 retained traced bytes. The audit exposed an APScheduler one-shot removal race during shutdown; pause/clear resolved it. Pytest's captured logger still emits a separate closed-stream message during its own atexit cleanup. No live app was restarted or broker action taken; `task.txt`, CSV work and the concurrently appearing `strategy_doc.txt` were preserved. No frozen feature task resumed.

Standalone gainers/losers CSV follow-up (2026-09-12): `CSVs/convert_gainers_losers_heikin_ashi.py` converted all 11 gainers and 11 losers, independently per timeframe, from the supplied Historify exports. Only 2026-09-11 rows are saved under `CSVs/GainersOn11092026/{1minHAdata,5minHAdata}/` and `CSVs/LoosersOn11092026/{1minHAdata,5minHAdata}/` (44 files; respectively 4,107 / 822 / 4,125 / 825 candles). Earlier history initializes continuous HA state. Verified every output date, row count, preserved non-price field and HA price using a Decimal reference with up to 200 preceding bars. ASHOKAMET has 358 / 72 source bars and KIRLOSIND has 374 one-minute bars; no missing bars synthesized. No inconsistent raw OHLC ranges on the target date. File-level counts and historical source warnings are in `CSVs/heikin_ashi_conversion_report_2026-09-11.csv`. No frozen task resumed.

Standalone CSV request (2026-09-12): converted the supplied PINELABS 1-minute and 5-minute files under `CSVs/historify_PINELABS_20260912_174459/` with the adjacent standard-library `convert_to_heikin_ashi.py`. The `heikin_ashi/` output folder contains full-history conversions (77,257 / 15,450 candles) and 2026-09-11 extracts (375 / 75 candles). HA state carries across sessions before date filtering; timestamps, volume and OI are preserved. Independently checked every output OHLC against Decimal calculations. Inputs contain 14 / 3 inconsistent historical OHLC ranges, none on September 11; supplied values were used without repair. This is a standalone data conversion; no frozen task or strategy work resumed.

Repository checkpoint: the user subsequently requested pushing everything to `Narasimha722/openalo_indian_markets_mvp`. The checkpoint includes the scanner integration, normal frontend build, handoff/test evidence, inherited `task.txt` edit and existing crypto backtest code/results. Credentials, runtime databases and dependency directories remain ignored. This synchronization does not resume any frozen task.

The user's latest instruction was to complete Task 2 "in this project," update Task 1's strategy later, and freeze the remaining tasks. This authorizes the scanner-specific integration into `D:/Personal/openalgo`; it does not authorize changes to the Crypto tree or work on Tasks 1/3/4/5/6. Earlier unresolved-boundary and isolated-only status statements below are historical and are superseded for **Task 2 only**.

- **Task 2 implementation is complete locally:** normal app startup initializes orchestration, authenticated navigation attaches the broker account, and `/market-scanner` exposes Volume Shockers, Top Gainers and Top Losers with category-before-top-50 ranking, daily price change, volume change, RVOL, observed-price sparklines, saved filters, pause/resume and honest stale/coverage states.
- Integrated the eleven manifest files only after verifying every original and candidate SHA-256. The normalized patch failed on CRLF source files, but all hashes matched; exact verified scanner candidates were installed. The existing application/upstream changes were retained. Added live tests to `test/test_market_scanner_live.py`; isolated legacy route-test state and scanner test DB configuration. Adjusted the navbar label breakpoint to accommodate Scanner without crowding the logo.
- Aligned the local installed `openalgo-charts` package with the repository's already-pinned **2.1.7**, using the previously installed isolated package. The old 2.0.2 package is preserved under the ignored development dependency backup. No package manifest/lock changes. Rebuilt the normal `frontend/dist` so the Flask application can serve the scanner.
- Verification: **76 backend tests passed**, including legacy routes and new login/two-tab, disconnect/retry/token-expiry and worker-takeover tests. **5 existing navbar tests passed.** Full production TypeScript/Vite build and scanner Python/Biome checks passed. **9 Chrome checks passed on the built `/market-scanner` SPA**, zero page errors; fixtures are explicitly synthetic. A 500-cycle integrated SQLite audit held **193 handles before/after**, with 248 retained traced Python bytes after GC.
- Current evidence: `.development/task2-scanner/artifacts/integrated/` (browser results, desktop/mobile screenshots, resource audit). `verify_integrated_browser.cjs` uses Vite preview on localhost:5188 and mocks session/scanner responses; it never places orders. The original integration patch/manifest remain historical pre-integration evidence; **do not reapply or regenerate them against the now-integrated source**.
- Operational limits: live market-hours streaming/long-running production reload observation and account-live Zerodha/other-broker verification are not completed. Fyers' real three-stock quote/baseline evidence remains the September 11 closing-session probe. Other adapters expose capability-dependent fallback and do not claim live verification. Production deployment/restart was not performed in this session.
- **Task 1 is frozen**, including the requested full-DuckDB run. Before resuming, first take the user's strategy update. **Tasks 3-6 are frozen.** No strategy edits or backtests were run. Preserve the inherited `task.txt`, crypto backtest/results and pre-existing compressed-build deletions; no commit/push was requested this turn.

To use: restart OpenAlgo normally, log in to the broker, and open **Scanner** (`/market-scanner`). Startup/login supplies background work; no scanner terminal command is required. On a nontrading day, current-session rows may be empty and older data is not relabeled as live.

Verification command from repository root:

```powershell
& .venv/Scripts/python.exe -m pytest test/test_market_scanner_live.py test/test_market_scanner.py test/test_market_scanner_routes.py --confcutdir=test -o addopts= -p no:cacheprovider -q
```

## Latest restart checkpoint — Task 2 prototype and repository synchronization

### Latest verified Task 2 milestone (after synchronization)

The requested repository synchronization completed: `8ccc15f92` was pushed to `origin/main`, preserving the user's upstream merge and GitHub's generated frontend build. The current Task 2 follow-up is now prepared for another checkpoint push.

The isolated scanner was rebased onto the upstream changes without overwriting original application source. Added an account-owned Quote connection to the existing shared broker WebSocket proxy (500-symbol default cap with full-universe polling fallback), timestamp/volume validation, fenced snapshot publication, completion/cooldown and changed-settings fixes, N/A volume degradation, persisted numeric filters, keyboard-accessible tabs, and application-start orchestration. Category filtering happens before top-50 selection. Every displayed row shows daily change from previous close and a separate volume-change percentage.

Verification now supersedes the prototype limitations below: **68 backend tests passed; eight actual Chrome browser checks passed with zero page errors; full isolated TypeScript checking and Vite build passed; Python lint and scanner-page Biome checks passed.** The dependency failure was the original installation's `openalgo-charts` 2.0.2 versus the updated source requirement 2.1.7. Installed 2.1.7 only in the isolated environment; original dependencies and original application source were preserved. Real read-only Fyers quotes and five-session baselines passed for RELIANCE/SBIN/ATHERENERG on September 11 after market close. A 500-cycle SQLite audit stayed at 192 handles before/after. The native Zerodha response contract passed offline tests; other broker/account-live verification and market-hours streaming/reload stress testing remain pending.

Review/restart: [.development/task2-scanner/README.md](../../.development/task2-scanner/README.md), [integration patch](../../.development/task2-scanner/artifacts/integration.patch), and [integration source hashes](../../.development/task2-scanner/artifacts/integration-manifest.json). Desktop/mobile fixture screenshots, browser results, live three-stock probe and resource audit are in the same artifacts directory. **Do not mark Task 2 fully complete or deployed:** the required original-code boundary clarification is still unanswered. Integration must apply only the eleven scanner files in the manifest to current sources and use the repository's required dependency version; do not replace the whole application with the development copy. No live orders were placed.

The notes below describe the earlier prototype checkpoint and remain as history.

The user brought Task 2 forward: show live daily percentage changes for every displayed stock and complete the scanner. On the next restart the user requested review of intervening code changes and pushing all current changes to `Narasimha722/openalo_indian_markets_mvp` before continuing Task 2.

- Isolated prototype: `.development/task2-scanner/`, committed by the user as `11ca386ab`. It contains a React scanner page, navigation/routes, existing scanner extensions, persistent polling orchestration and account-scoped snapshots, index CSV imports with unknown-date provenance, top-50 filtering, price/volume percentages, and bounded observed-price sparklines. **Task 2 is not complete or integrated into the original application.**
- Verified before the intervening merge: 61 backend tests passed (9 new tests plus 52 existing scanner tests). Isolated Vite production bundling passed. Full TypeScript checking reported the same six existing `chartProfiles.ts`/installed-chart-library errors in both the original and isolated copies. Frontend lint still needs its status-region accessibility fix and intentional polling-dependency annotation. Browser verification remains pending.
- The implementation currently uses batched polling, not full-universe streaming. Finish shared-feed integration, broker capability verification, lifecycle/reconnect/resource checks, and browser tests before declaring completion. No live orders were placed.
- The user then merged upstream into `main` (`36f8c2742`). Changes include broker streaming/rate-limit fixes, chart object/indicator work, market-calendar service changes, application startup changes and frontend dependencies. Preserve these changes. The isolated whole-file copies predate this merge: **do not copy their old `app.py`, full frontend tree or package lock over the updated original application.** Rebase only the scanner additions onto current sources when integration is authorized.
- Actual remotes at restart: `origin` is the requested private repository; `upstream` also exists and was used by the user. Preserve both. The old context statement that origin is the sole remote is historical.
- The edit boundary remains unresolved. An optional question requesting permission to integrate Task 2 into the normal app was sent; no answer is recorded. Continue isolated development until clarified. The push request explicitly authorizes committing/pushing the current changes, including the existing `task.txt` newline change; it does not resolve the original-code edit boundary.
- Task 1's later all-DuckDB request (2017-07-03 through 2026-09-10, temporarily skip the strategy volume filter) remains pending. No full-universe run was launched before the user brought Task 2 forward.

Resume backend checks from the repository root:

```powershell
& .venv/Scripts/python.exe -m pytest .development/task2-scanner/test_live.py test/test_market_scanner.py --confcutdir=.development/task2-scanner -o addopts= -p no:cacheprovider --basetemp=.development/task2-scanner/test-tmp -q
```

## Current stage — after the scanner-based strategy update

We are at **Task 1 baseline validation**, before full-history backtesting or optimization. Completed evidence: inventory of 93 CSVs and metadata for 1,573 NSE stocks; four provisional unrestricted reports for ATHERENERG/RELIANCE at 1m/5m; and now a separate scanner-selected partial-day replay through September 11 12:26 IST. The latter reconstructs 191 minute-level snapshots, produces 48 trade charts, and has eight focused execution/gating tests plus ledger/data/browser verification. These remain research artifacts, not a deployed strategy.

The existing Fyers scanner produced a verified September 11 intraday snapshot and standalone top-50 report. This is partial Task 2 progress: the integrated automatic live UI, broker-neutral support, category filters and sparklines remain pending. Tasks 3–6 have not started. The original-code boundary remains unresolved, so implementation continues in the isolated development copy.

**Latest user change:** Task 1 should take trades only from Volume Shockers, Top Gainers or Top Losers; the user then requested today's scanner, a backtest and a plot of each trade, and asked to resume the interrupted work. The contract is in **T1.2a** below. That bounded replay is complete for its frozen 12:26 IST cutoff; it does not include the afternoon or a full-history comparison. No live order has been placed. The next milestone is broader execution/data validation and comparison against the unrestricted reference before scaling.

## Scope and repository boundaries

The user originally asked to plan first and save enough memory for a restarted or different agent. That planning session changed documentation only. Later authorized resumption added isolated research code/reports and ran the existing market-data scanner; those milestones are recorded below. Original application code and credentials remain unchanged, and no live orders have been placed.

| Repository | Intended responsibility | Boundary |
|---|---|---|
| `D:\Personal\openalgo` | Existing Indian-market backend; source for strategy, scanner, web UI, sandbox behavior | Preserve existing code during planning; Task 3 must integrate without modifying it |
| `D:\Personal\openalgo_Crypto` | Existing crypto backend, Delta Exchange broker | Preserve existing code during planning and Task 3 |
| `D:\Personal\Algomirror` | Shared account interface and calculator for Indian and crypto brokers | Main Task 3 implementation target |
| `D:\Personal\openalgo-mobile` | Flutter client with web functionality parity | Main Task 5 implementation target |

The instruction “don't change any code” for the two OpenAlgo directories conflicts with Tasks 2, 4, and 6 explicitly requesting OpenAlgo changes. An optional clarification was sent during planning, with no answer recorded at save time. **Until clarified, keep both original code trees unchanged and prepare future OpenAlgo changes in a separate development checkout/copy.** Do not assume silence authorizes edits to either original tree. If the user clarifies that the freeze only applies to Task 3, implement other requested tasks in their designated development branches. Record that answer here.

Only `D:\Personal\openalgo` is a writable project root in this session. Later edits in sibling repositories require a workspace granting access or the normal tool escalation; task intent does not bypass filesystem restrictions. No such write is needed to finish planning.

Preserve pre-existing changes: `task.txt` was modified, and `delta-exchange-api-docs.md` plus `stock_symbols_CSVs/` were untracked at inspection. Do not overwrite, stage indiscriminately, reset, or delete them. Existing `context.md` documents the private remote and older work; do not replace its history or reset Git remotes.

## Evidence inspected

- `backtesting/stratagies/ATHERENERG_ha_bb_vwap_backtest.py`: single-symbol CSV/report adapter importing `ha_bb_vwap_strategy_astra.py`; several output filenames are hardcoded to ATHERENERG.
- `backtesting/stratagies/ha_bb_vwap_strategy_astra.py`: actual strategy. Existing baseline is long-only, five-minute, completed confirmation then next real bar open, one portfolio-wide position, maximum three daily entries, risk-based sizing, and configurable filters/exits.
- `scripts/market_scanner.py`, `services/market_scanner_service.py`, `services/market_scanner_provider.py`, `blueprints/market_scanner.py`, scanner DB and tests: useful backend already exists, but CLI selection, route authentication gate, and provider are Fyers-specific. Blueprint is already registered by `app.py`. No scanner page route was found in `frontend/src/App.tsx`.
- `db/historify.duckdb` exists, with a lock file. Its content and coverage were **not** audited during planning. Do not delete the lock or interrupt a writer to inspect it.
- `stock_symbols_CSVs/` contains 31 CSV files. A sampled Dhan Nifty Bank file has company names, screener URLs, LTP, volume, ratios, etc.; it is a screener snapshot, not timestamped historical OHLCV. `D:\Personal\CSVs` contains a charges CSV and spreadsheets in the inspected listing. Classify every file during Task 1; do not treat filenames or snapshot prices as history.
- `database/watchlist_db.py` already stores server-side named watchlists. `database/sandbox_db.py` stores sandbox orders/positions and uses integer order quantities; fractional mutual-fund units need a dedicated compatible model.
- OpenAlgo `frontend/package.json`: React, Vite, Tailwind v4, Radix components; MUI is not currently listed. Inspect actual installed/locked dependencies before migration.
- Local AlgoMirror README, `app/models.py`, calculator paths, and `package.json`: existing `TradingAccount` has broker name, HTTP host and WebSocket URL. UI uses server templates, Tailwind v3 and DaisyUI. Do not assume it is a React app.
- Local mobile README and `lib/`: Flutter, Provider, REST/WebSocket services, Material Design 3; existing trading screens and placeholder chart screens. README is an inventory lead, not proof that every feature is working.
- Local `delta-exchange-api-docs.md`: generated 2026-09-08; reviewed product metadata, contract values, margin/fee fields, orders, stop triggers, bracket parameters, leverage and wallet sections. Crypto broker `api/order_api.py` already contains leverage and bracket handling; verify public API field passthrough before promising those capabilities to AlgoMirror.
- `CLAUDE.md`, `docs/INDEX.md`, existing `context.md`, OpenAlgo and VectorBT skills were consulted. Preserve the supplied indicator mathematics even where a generic skill would normally select a different implementation.

External primary references checked during planning: [AlgoMirror repository](https://github.com/marketcalls/Algomirror), [Delta API documentation](https://docs.delta.exchange/), and [Material UI with Tailwind v4](https://mui.com/material-ui/integrations/tailwindcss/tailwindcss-v4/). Recheck current product constraints, fees and compatibility when implementing; examples are not live account settings.

### Screenshot reference map

All eight files were viewed. Directory: `C:\Users\nikhi\OneDrive\Pictures\Screenshots\`; each filename starts `Screenshot 2026-09-10 ` and ends `.png`.

| Suffix | Relevant content |
|---|---|
| `232438` | Delta API setup, account, IP whitelist, read/trading permissions |
| `232607` | Credential creation result; contains a key and secret. Never transcribe them into notes, code, logs, fixtures or commits. User was advised to rotate them. |
| `232820` | Long order panel, leverage, Limit/Market, quantity in lots, allocation presets, contract units, TP/SL, funds, flags, fees |
| `232832` | Maker Only, Stop Limit, Stop Market, Trailing Stop, Take Profit Market/Limit menu |
| `232847` | Bracket editor; trigger source, TP market/limit, SL market/limit/trail, percentage presets, exit/stop P&L |
| `232902` | Corresponding Short order panel |
| `232929` | ETH example with leverage choices up to 200x, maximum position and contract size |
| `232945` | Different product with maximum 20x and different unit size; limits must be product-specific |

Screenshots specify interaction requirements, not universal leverage, prices, contract sizes or fee rates. No need to copy credential screenshots into the repository.

## Shared design and execution order

Keep Indian and crypto engines separate. Run both simultaneously with distinct HTTP/WebSocket/internal messaging ports, database paths, process state, logs and credentials. Audit cookie names/domains as well: browser cookies are not isolated by port. Use separate hostnames or supported per-instance session-cookie configuration. Do not mutate a running setup during planning.

AlgoMirror should maintain a client and market-data subscription group per connection/account. Key instruments, quotes, orders, caches and events by connection ID + broker + exchange + instrument; never use a global “current broker” to route background work. A shared visual calculator delegates calculation rules to an asset/broker adapter. Keep native-currency balances separate; only aggregate with an explicit conversion source and timestamp. Crypto schedules must not inherit Indian daily square-off or session boundaries.

Recommended sequence (preserving the user's task numbers):

1. P0: confirm edit boundary; inventory data and API capabilities; create isolated implementation workspace and shared theme/API contracts.
2. T1: establish historical data coverage and reproduce the original baseline; bring forward T2's shared ranking/snapshot contract to implement T1.2a scanner-based selection, then produce the requested baseline reports before research variants. The full T2 UI is not a prerequisite for historical replay.
3. T3: implement account-aware calculator and simultaneous connection support in AlgoMirror.
4. T2: extend existing scanner and expose its live UI using the common theme foundation.
5. T6: add persistent sandbox investment watchlists and portfolio ledger.
6. T4: complete theme/component migration across the web route inventory; foundation starts at P0 so new pages already match.
7. T5: deliver mobile parity in batches against stable backend APIs, then integrated verification of all clients.

This is a dependency order, not a claim that implementation has been authorized to modify protected original code. No automatic live strategy deployment follows a good backtest.

## Task 1 — All-stock strategy, DuckDB, reports and automated research

“All-stock” now describes the universe scanned and historical data coverage. **The requested trading variant enters only eligible stocks from the scanner lists defined in T1.2a.** Keep the prior unrestricted variant as a clearly labeled reference for comparison, not as the updated requested strategy.

### T1.1 Data catalog and reusable ingestion

Inventory CSVs from `stock_symbols_CSVs`, `backtesting`, existing historical export folders including `D:\Personal\historify_ATHERENERG_20260908_112029`, and any further user-designated data folders. Read headers and classify OHLCV, universe/screener snapshots, charges/reference data, and generated outputs. Catalog every CSV and preserve its source; import useful data into the appropriate tables. Generated HA candles, trade reports and repeated normalized exports must not become independent raw-price history.

Use a dedicated research DuckDB with `source_files`, `instruments`, `universe_snapshots`, `raw_imports`/quarantine, normalized `ohlcv`, `coverage`, and `backtest_runs`. Historical timestamps should be unambiguous UTC instants with exchange timezone metadata. Unique candle identity: instrument/exchange + interval + bar-open timestamp + declared data version/source policy. File manifest stores path, hash, schema, imported row counts and errors. Imports are idempotent; conflicting duplicates are reported instead of silently overwritten. Snapshot datasets without a trustworthy as-of date must retain an unknown date, not an inferred historical one.

Validate OHLC ranges, positive prices, nonnegative volumes, timestamps, session calendars, duplicates, missing bars, incomplete sessions and corporate-action treatment. Resolve company display names to exchange symbols using instrument masters with unresolved mappings reported. Retain source/adjustment metadata; never mix adjusted and unadjusted series silently. Universe membership is point-in-time where available; label survivorship bias otherwise.

Use actual one-minute OHLCV for 1m tests; aggregate it into five-minute candles aligned to 09:15 IST for regular Indian sessions. Five-minute-only data supports 5m signal tests, not invented 1m data. Reuse Historify through supported readers or a consistent snapshot/export; separate ingestion writer from read-only research workers. Large imports and runs are chunked/resumable, with an immutable data version per run.

Deliver coverage per stock/timeframe: earliest/latest candle, rows, valid sessions, gaps, warmup eligibility, available years and exclusions. Request/backfill missing history only after coverage is known and broker availability is checked. The requested five/ten-year reports must say unavailable or partial when the stock/data lacks that history.

### T1.2 Preserve signal rules; change execution explicitly

Freeze a versioned copy/hash of the original strategy and reproduce its baseline first. Preserve HA recursion/seed across sessions; BB(20, 2) on HA close with population standard deviation; existing signal bullish/zero-lower-wick conditions; session real-HLC3 VWAP; existing volume filter by default (20 prior full sessions, RVOL >= 2). Short signals mirror the pattern with bearish/zero-upper-wick and lower BB. Keep configurable original breakout source, stop source and exit mode; default target remains 2R unless selected otherwise.

New execution state per symbol: `FLAT`, `ARMED_LONG`, `ARMED_SHORT`, `LONG`, `SHORT`.

1. At signal-bar close, require eligibility under T1.2a, then evaluate the unchanged completed HA/BB signal criteria and existing signal-time filters. Store signal time and HA high/low; also retain real OHLC for diagnostics and the original configurable real stop source.
2. Arm the immediately following bar only. Recheck scanner eligibility using the latest valid snapshot available before entry. A long enters on a real traded-price break strictly above signal high while price is above the causally available VWAP; short mirrors below signal low and below VWAP. Do not wait for the entry bar to close or defer to a third candle. Use instrument tick size to define strict crossing and adverse slippage for fills.
3. If that bar produces no valid entry, expire the old signal at its close. Evaluate that completed bar as a replacement signal and arm its successor when eligible. Repeat within the session. No signal is carried overnight.
4. After SL/TP closes a trade, resume signal evaluation and allow later long or short entries that day. Remove the three-trades/day limit and the single portfolio-wide position restriction.
5. Track simultaneous positions across stocks. Proposed default is one open position per stock, with unlimited sequential re-entry. Pyramiding multiple overlapping entries in the same stock is a separate policy to clarify, because “as many trades as come” does not specify it.

**Execution decisions to settle before calling results final:**

- The current original signal requires a fresh crossing from inside to outside the band. The user's replacement example may instead mean any qualifying candle still outside the band. Keep fresh-cross behavior as the primary preservation interpretation; expose a separately named continuation variant and obtain clarification before presenting it as the requested baseline.
- Existing completed confirmation-bar HA color/wick/close filters cannot be known at an intrabar entry. Preserve completed **signal** candle rules, replace the close-confirmation stage with the requested price/VWAP trigger, and label the change. Do not accidentally use future final HA values to claim those confirmation filters were met.
- Proposed trigger threshold retains the original signal HA high/low; offer real signal high/low as an explicit comparison if the user intended normal-candle extremes. Never fill at an unreachable synthetic HA price; real market data must cross the threshold.
- Original entry end is 15:00 and square-off is 15:20. The new request says traverse until day end. Proposed enhanced behavior permits entries until immediately before configured square-off, retaining 15:20 square-off initially; confirm whether the user wants a later market-close policy. Label timing in every report.
- VWAP at an actual tick can be computed from contemporaneous trades. Historical OHLCV cannot recover exact trade sequence or tick VWAP. Primary reproducible bar test uses the latest fully completed execution sub-bar's session HLC3 VWAP at the crossing opportunity; label this approximation and optionally compare a causal tick replay when data exists. Never use the entry bar's eventual HLC3/volume to qualify an earlier crossing.

For five-minute signals, replay available one-minute execution bars; for one-minute signals use ticks/sub-minute data if available, otherwise an explicitly approximate OHLC execution model. Gap through entry fills at real open plus adverse slippage when filters are valid. A bar touching both stop and target requires an ambiguity flag and conservative stop-first convention. When entry/exit ordering itself is unknown, report conservative and alternate sensitivity rather than invent timestamps; do not count an unknowable same-bar re-entry. Store event time precision. Reject invalid stop distance, zero affordable quantity and missing required data with reasons.

### T1.2a User update — scanner-based trade selection (2026-09-11)

**Requested:** take/place strategy trades in stocks from Volume Shockers, Top Gainers or Top Losers. Status: isolated minute-by-minute reconstruction and entry gating implemented and exercised on one partial day; broader acceptance and live integration remain pending. This changes stock eligibility for the planned strategy, not the HA/BB/VWAP entry pattern. It does not authorize placing live orders during research.

**Working defaults for implementation:**

| Rule | Contract |
|---|---|
| Candidate lists | Top 50 Volume Shockers, top 50 positive daily gainers, top 50 negative daily losers, each ranked across the entire configured eligible universe |
| Combined universe | Union of the three lists: membership in any one is sufficient; deduplicate by exchange/instrument identity, at most 150 unique candidates per snapshot |
| Trade direction | Preserve strategy signals: bullish setup can enter long; bearish setup can enter short. List membership alone does not force a direction. Restricting gainers to longs/losers to shorts would be a separately named policy, not an assumed user requirement |
| Entry gate | Require membership when arming the completed signal and immediately before an executable entry, using only a valid snapshot already available at each decision |
| Refresh | Historical working default: recompute rankings at each completed one-minute bar, available for the next execution bar; both 1m and 5m signals consume that same causal schedule. Live target uses shared streaming/cached data with an explicit snapshot availability time, not a new full history scan every minute |
| Stale/missing selection | Block new entries when the required snapshot is missing, from another session/account, or older than the configured freshness limit (initial working value: 60 seconds after availability). Record the reason; do not fall back silently to unrestricted trading |
| Membership changes | Newly selected stocks can arm qualifying signals once indicators are warmed. Removal invalidates an armed unfilled signal. Existing positions continue their normal SL/TP/square-off management; removal alone does not force an exit |
| Sizing and exits | Retain INR 100,000 fixed notional per trade, whole-share sizing, one position per stock, simultaneous positions across stocks, later re-entry, and the existing planned SL/TP/square-off contract |

These defaults make the requested update executable and reviewable; the user has not separately specified direction restrictions, a different list size, refresh interval or an intersection of the lists.

**Ranking and indicator preservation:** reuse T2's ranking mathematics and deterministic tie-breaking. Volume shockers initially require scanner RVOL > 1 against the previous five completed full-session volume totals; rank by RVOL descending. Gainers/losers use change from the verified previous trading-session close, with positive descending/negative ascending ranking. Apply category and instrument eligibility before top-50 selection, and report fewer than 50 when appropriate. A selected category is versioned in the run; initial historical scope is the available validated NSE stock universe, with coverage exclusions disclosed.

The scanner's five-session RVOL and the strategy's existing **20-session RVOL >= 2** are separate gates. Keep both and record both values/definitions. Do not disable the strategy volume filter merely because a stock was selected as a gainer or loser; any relaxation is a named research comparison. Calculate/warm indicators over each stock's available history even while it is outside the lists, so entering a list does not reset HA or VWAP.

**Historical selection must be reconstructed at the time of each decision:**

- Use prices, cumulative volume and completed daily baselines known by that snapshot's cutoff. The current execution bar's eventual high/low/close/volume and final day rankings cannot qualify an earlier entry. The September 11 11:36 snapshot is usable only from its actual availability time; it cannot choose stocks for that morning or prior years.
- Reconstruct rankings jointly across all eligible instruments at a common historical cutoff, before stock-level execution. Independently backtesting each stock and filtering its completed trades by today's list is not a valid implementation. A symbol with unavailable/stale bars is excluded with its reason; do not fabricate a current price by unlimited forward filling.
- Store `scanner_snapshots` and `scanner_memberships` (or equivalent versioned tables) with snapshot ID, market cutoff, availability time, session, source/account scope where applicable, universe/data version, ranking config, list/rank, instrument, quote/baseline timestamps, price change, cumulative/average volume, RVOL, coverage and exclusions. Preserve the actual refresh/availability delay for recorded live snapshots. Declare the assumed availability delay for historical bar reconstruction.
- Existing 1,573-stock history does not reproduce the full 2,642-instrument live scanner universe automatically. Mark historical results as rankings within the validated available-history universe; measure missing members and survivorship limitations. Separate equities from broker-classified ETFs for stock-only runs, using verified instrument metadata. Do not label missing-universe or unverified-previous-close periods as full-market rankings.
- The current terminal scanner is a slow one-off snapshot producer. Its successful run does not establish a continuously fresh live trade-selection service. Historical ranking can be implemented now; live strategy integration depends on T2's shared updates, freshness/coverage controls and existing order lifecycle integration. If live entry orders are later supported, reconcile fills and cancellation acknowledgements before treating an order as cancelled after membership removal.

**Reports and acceptance:** every entered trade records signal/entry snapshot IDs, source-list tags, ranks, scanner RVOL/price change, strategy RVOL and eligibility decisions. Record rejected signals separately. Compare unrestricted reference versus scanner-selected strategy on identical dates, validated universe, data version, costs and execution settings; display trade count, P&L, drawdown and peak funding differences. Breakdowns by list must disclose overlapping membership and must not double-count trades in portfolio totals.

Required tests: inclusion through each list; union versus intersection; top 50 after full-universe ranking; overlap producing one order/trade; long/short direction remaining signal-driven; candidate arrival/removal before entry; open-position management after removal; stale/missing snapshots blocking entries; future price/volume changes leaving earlier selections unchanged; 1m/5m timing; indicator continuity across membership changes; both volume filters retained; partial historical universe labeling; and ledger/snapshot attribution reconciliation. Run a bounded multi-stock replay that exercises competing ranks before attempting the full history or optimization. The existing two-stock smoke tests do not satisfy this acceptance.

### T1.3 Capital and metric contract

Interpret INR 100,000 per trade as a fixed notional allocation, not stop-risk or total portfolio capital: whole-share quantity is `floor(100000 / executable_entry_price)`, with entry costs recorded separately. Keep allocation fixed after wins/losses. Respect lot size where applicable. Model equity intraday shorts as intraday positions with square-off. Broker margin/leverage is a separate optional model, not an assumed funding benefit.

Provide two clearly labeled views: all valid opportunities with sufficient simulated funding, and optional constrained-capital replay. The first must disclose the funding it required; it cannot imply all concurrent trades fit inside one lakh. Use a fixed, disclosed starting-capital denominator for portfolio returns, daily marked-to-market equity/drawdown, and Sharpe. External top-ups, if modeled, are cash flows rather than profits. Daily Sharpe uses daily portfolio returns, a stated annualization convention/risk-free input and no trade-level annualization; zero variance/insufficient observations return N/A. Per-stock reference capital starts at the declared allocation plus any explicitly modeled fee reserve, and depletion is flagged.

Reports per stock AND timeframe include gross P&L, itemized costs, net P&L, return denominator, maximum marked-to-market drawdown in INR and %, win rate, Sharpe, trades, long/short breakdown, average win/loss, profit factor, expectancy, holding duration, exclusions and ambiguous fills. Record actual entry/exit, SL/TP, quantity, signals, strategy/data hashes, cost assumptions and research variant.

Daily capital table: trade count, sum of entry notionals/turnover, peak simultaneous notional, peak margin if available, peak concurrent positions, cumulative P&L, cash/funding requirement including fees/losses, and end-of-day equity. Turnover is not required capital. Reconcile daily trades and P&L to ledger and portfolio totals.

Aggregate per stock/timeframe for calendar month, quarter, half-year (Jan–Jun/Jul–Dec), year, five-year and ten-year windows. Use calendar-aligned multi-year blocks with documented anchor, plus trailing five/ten-year summaries when complete history exists. Flag partial windows. Trade counts/wins belong to exit period; period equity P&L and drawdown come from marked-to-market equity, including boundary positions. Never add percentage drawdowns or average monthly Sharpes to produce annual statistics.

Deliver an offline interactive HTML report, machine-readable CSV/Parquet/JSON tables, equity/drawdown charts, ranked stock summary, drill-down trade ledger, daily capital use, period tables, source coverage and assumptions. Include stock buy-and-hold and NIFTY benchmarks only where authentic aligned history is available; otherwise label unavailable. Rankings distinguish insufficient history/no trades from poor results. The user chooses stocks afterward.

### T1.4 Automated research with the entry pattern frozen

Version the scanner-selected baseline above; run a bounded experiment registry varying only additional filters/exits: EMA trend/slope, ADX strength, ATR regime, RSI momentum, relative-volume variations, VWAP distance/slope, time windows and stop/target/trailing alternatives. Scanner selection, VWAP and the requested candle/BB trigger remain mandatory in this baseline; do not quietly replace them. Preserve baseline RVOL and compare alterations as named experiments. Use causal OpenAlgo TA where new indicators are needed, validated against fixtures.

Use chronological train/validation/test splits with warmup outside scored periods, walk-forward evaluation, untouched final holdout, predeclared search budget/objective, minimum trade counts, cost/slippage stress and parameter-neighborhood stability. Select on training/validation only; record all trials, failed trials, seeds, data hashes and drawdown/capital tradeoffs. Do not optimize separately on each stock's entire history and present it as out-of-sample performance. Research produces a comparison report, never automatic deployment.

Acceptance: hand-checked long/short rollover examples; next-bar intrabar entry; VWAP rejection; multiple later re-entries; concurrent stocks; 1m/5m alignment; no future indicator access; gap and ambiguous-fill rules; whole-share one-lakh sizing; deterministic resumable imports; period/ledger/capital reconciliation; and explicit missing-history outcomes. Complete baseline all-stock reporting before optimizing.

## Task 2 — Built-in live scanner for all supported brokers

Extend the existing scanner provider/manager/DB/routes/tests rather than creating a second scanner engine. Replace Fyers-only routing with a broker-capability adapter using common quote/history/instrument services. Preserve ranking/filter semantics and cached baseline history.

### User additions recorded 2026-09-11 — volume changes, categories and sparklines

These additions extend Task 2; they are saved requirements, not implemented behavior.

- **Volume Shockers: show 50 stocks**, ranked by volume increase/RVOL descending. Scan the full selected universe before taking the top 50; do not scan only 50 symbols. If fewer than 50 qualify, show the actual count and coverage instead of padding results.
- Each row shows stock name/symbol, a very small intraday price line chart (sparkline), LTP, **today's price change %**, today's cumulative traded volume, **volume change %**, and RVOL. Keep price change and volume change in separately labeled columns. Price change % = `(LTP / previous trading session close - 1) * 100`; do not use today's open or yesterday's calendar date as the default reference.
- Volume change % = `(today's cumulative volume / selected baseline volume - 1) * 100`; RVOL uses the same baseline, so 2.5x means +150% volume change. Initially retain the existing configurable average of the prior five completed trading sessions, excluding today. Label it “Volume change vs 5-session average” (or the selected lookback), not an unlabeled daily percentage. This compares today's partial cumulative volume to historical full-day volume; expose that basis in the tooltip. An explicit “vs previous session” baseline may also be selected. Add a separately labeled same-time historical-volume baseline only when intraday history exists; never silently mix the modes. Missing/zero baseline produces N/A, not infinity or 0%.
- **Top Gainers and Top Losers: category/index filters** for All stocks, Nifty 50, Nifty 100, Nifty Next 50, Midcap and Smallcap. Midcap supports the available Nifty Midcap 50/100/150 constituent sets; Smallcap supports Nifty Smallcap 100/250. Default broad category mappings are Midcap 150 and Smallcap 250, with the exact index name visible. Also expose Nifty 200/500 where the supplied constituent lists are imported. Start with a single-select category filter, persist it, and apply it before ranking/limiting. Make the same filter usable on Volume Shockers for consistent navigation.
- Use the local `stock_symbols_CSVs/ind_nifty*list.csv` constituent files as import sources, including `ind_nifty50list.csv`, `ind_nifty100list.csv`, `ind_niftynext50list.csv`, `ind_niftymidcap150list.csv`, and `ind_niftysmallcap250list.csv`. Store normalized instrument membership, source, import time and effective/as-of date where known. Do not assume a snapshot is current without checking its provenance; show membership date or “date unknown” and provide a refresh path. Support legitimate overlap between index sets without duplicate rows within one result list. Match exchange symbols rather than fuzzy company-name text.
- Rank gainers by positive daily price change % descending and losers by negative daily price change % ascending **within the selected category**. Display daily price change % for every stock. Use a 50-row default for these tables too, with actual available counts; this extends the user's explicit 50-stock requirement for Volume Shockers consistently to the other tabs.
- **Sparkline in all three result tables:** put a compact line chart beside the stock name and daily change %. Use real timestamped intraday prices/minute closes from today's session, rendered in a small responsive SVG or equivalent lightweight component. Color by the sign of daily price change, include a neutral state, accessible text and an optional hover price/time. Keep numeric percentages legible without relying on color. Label the chart as price, not volume; it complements the volume columns.
- Seed sparklines from cached/batched intraday history where available, then append shared live-feed observations. Bound/downsample points for a small chart; avoid a heavyweight chart instance or separate polling/WebSocket connection per row. With only live observations, show the observed period as “since connected”; never fabricate the earlier session path. Preserve gaps and show stale/no-data states. Category switches reuse cached series, respect provider limits and reset series at the new trading session.

Illustrative row layout: `Stock name / symbol | small price line | LTP | Day change % | Today's volume | Volume change % | RVOL`. The gainers/losers views may keep volume fields secondary but must retain name, sparkline, LTP and day change %.

### Service and lifecycle

Add a Scanner navigation item/page: Volume Shockers, Top Gainers, Top Losers, universe/exchange filters, volume/RVOL/price filters, live status, update time, coverage and partial/error states. Persist preferences and auto-start setting; default the new feature to automatic startup once enabled/installed per the requested behavior. Running `app.py` initializes orchestration; scanning waits for valid broker login and automatically attaches after login/reconnection. No separate terminal command is required.

Seed quotes in batches, then reuse the existing shared WebSocket feed. Use throttled updates to the browser and rate-limited polling when a broker lacks streaming/batching. Implement subscription limits, reconnect/resubscribe, backoff, token refresh, market-open scheduling and stale-data labels. Missing volume/history must show unavailable RVOL, not zero. Crypto universes, if exposed, use their own 24/7 schedule and explicit rolling/session volume definition.

Use a single elected scanner worker/lease per instance/account across Flask reloads and production workers. Persist control state; stop/release resources on logout/shutdown. Avoid a new broker socket per tab or full-universe historical download every refresh. Broad broker support means each adapter declares capabilities and falls back honestly; keep an explicit verified-broker matrix, not a claim that untested brokers passed.

Acceptance: app startup + broker login alone produces updates; two browser tabs share work; broker switch isolates data; non-Fyers supported adapter works; unsupported volume degrades clearly; 429/disconnect/token expiry recovers; duplicate workers are prevented; ranking tests remain valid; DB sessions/subscriptions/threads close correctly. Run applicable resource/FD audit on implementation.

Additional acceptance for the user additions: top 50 is selected from the entire filtered universe; fewer matches remain truthful; a stock with LTP 110 and previous close 100 displays +10% regardless of today's open; cumulative volume 250,000 against baseline 100,000 displays +150% and 2.5x; zero/missing baseline gives N/A; each index filter excludes nonmembers before ranking; overlapping membership does not duplicate rows; gainers/losers use the correct sort direction; all three tabs show real small price charts with timestamps and missing-data states; category changes and 50 visible rows do not multiply broker connections or cause unbounded history requests.

## Task 3 — Crypto calculator in AlgoMirror and concurrent Indian/crypto use

Implement in AlgoMirror using the two existing OpenAlgo hosts, with no code changes to either protected backend for this task. Audit existing account model, `app/utils/margin_calculator.py`, `app/templates/margin/calculator.html`, connection clients and risk-monitor assumptions first.

Persist per-connection broker/market identity, API/WS hosts, account label and capabilities. Resolve calculator behavior from the selected account's verified broker (`deltaexchange`), not a global browser login flag. Provide Indian, Crypto and Both account views. Simultaneous background quotes, balances and positions must remain connected while the user changes foreground account.

Use a common calculator view model and separate equity/Indian-derivatives/Delta adapters. Inputs: instrument, long/short, capital or quantity, entry mode/price, product-specific leverage, TP/SL, trigger source and supported order flags. Outputs: integer contracts/lots, underlying units, notional, required/available margin, fee breakdown, SL/TP P&L and risk/reward with labeled currencies. Preserve existing Indian sizing and fee behavior with regression fixtures.

Delta inputs follow screenshots: Market, Limit, Maker Only/post-only, stop market/limit, trailing stop, TP market/limit; allocation presets 10/25/50/75/100%; TP/SL percentage presets; mark/last/index trigger source; reduce-only and supported time-in-force. Support these progressively only when the complete server/API route supports them. A calculator estimate must not change leverage or submit an order; explicit order submission is a separate existing user action.

Read paginated `/v2/products` metadata and appropriate ticker data through supported adapters. Use product contract value/type, tick/size constraints, quote/settlement/underlying assets, initial/maintenance margin scaling and fee fields. Obtain account balances/leverage through existing authenticated backend APIs; keep Delta secrets server-side. The local API notes describe `POST /v2/products/{product_id}/orders/leverage`, order bracket fields, `post_only`, `reduce_only`, and mark/last/spot trigger enums. Audit that OpenAlgo request validation/SDK/mapping preserves them end to end; existence of broker functions alone is insufficient.

For a supported linear contract, indicative notional is contracts × base-unit contract value × price; initial leverage-only margin estimate is notional/leverage; long/short gross P&L is signed contracts × contract value × price change. Use Decimal arithmetic, correct rounding, currency conversion and fees. Actual tiered/cross/portfolio margin can differ: use broker-provided requirements where exposed and label estimates otherwise. Reject unsupported inverse/option formulas until dedicated adapters exist. Never hardcode screenshot ETH lot size, 200x/20x, USD/INR conversion or a retail fee tier. Account-specific maker/taker rates, applicable tax, funding assumptions and data timestamp must be visible in estimates; estimate liquidation only with a validated margin-mode model.

Where an unchanged OpenAlgo backend lacks metadata, AlgoMirror may fetch public Delta metadata server-side. Where it lacks a required authenticated operation, record the gap and expose estimate-only/unavailable behavior for that operation; do not silently add a second credential store or direct order route. Deliver a precise capability-gap report for any separately authorized follow-up.

Acceptance: deterministic sizing/rounding/fee examples; differing ETH/VVV-style contract sizes and leverage caps; long/short P&L; insufficient funds and stale metadata; maker-only restrictions; partial-fill/TP-SL lifecycle for supported submission paths; Indian calculator regression; two simultaneous hosts without session/cache/stream crossover; Indian logout does not stop crypto. Unsupported product/order capabilities are visible and truthful.

## Task 4 — Complete web UI refresh with dynamic themes

Build a route/component inventory covering every existing OpenAlgo user surface: auth/dashboard, charting/order calculator, books/positions/holdings/funds, watchlists, scanner, sandbox, Historify, tools, strategy/RMS, Flow, Python host, logs/settings and other registered routes. Define migration status per route so “all UI” does not stop after a dashboard mockup.

Create central design tokens for semantic colors, typography, spacing, radii, borders, shadows, chart palettes, density and motion. Provide light/dark/system themes plus selectable accent palettes, font and density preferences. Persist preferences and apply before first paint. Maintain distinct gain/loss/warning/live/sandbox meanings across themes, accessible contrast/focus and reduced motion.

Use MUI components for the React UI and Tailwind/CSS for layout and styling, backed by the same CSS variables. Follow official CSS layer integration (`theme, base, mui, components, utilities`) so resets/overrides remain predictable. Verify installed React/MUI compatibility; migrate shared components in stages rather than loading conflicting resets throughout every page at once. Preserve chart interactivity, keyboard shortcuts, dense financial tables and numeric precision.

AlgoMirror is Jinja/Tailwind v3/DaisyUI: apply matching CSS tokens there, and decide explicitly whether its calculator merits an isolated React/MUI component. A whole-app React rewrite is not an implied dependency. Flutter uses native Material 3 equivalents with shared token values, not CSS/Tailwind binaries.

Acceptance: complete route checklist; responsive desktop/tablet/phone layouts; theme persistence; keyboard/screen-reader flows; chart/table colors; loading/error/empty states; visual review and targeted interaction regression; frontend typecheck/lint/build and relevant tests.

## Task 5 — Mobile app matching OpenAlgo functionality

Extend the existing Flutter app in `D:\Personal\openalgo-mobile`. Build a parity matrix from the actual OpenAlgo route/API inventory, including every surface listed in T4 and new T1 reports, T2 scanner, T3 calculators/account selection, and T6 portfolios. Classify existing, incomplete, missing, and backend-API-needed features. Do not call the app a full mirror while screens are placeholders or browser-session-only features cannot be used.

Retain native Material 3 and adapt navigation/tables/chart controls for touch. Provide multiple saved Indian/crypto server profiles and concurrent account overview with unmistakable server, broker, currency and live/sandbox badges. Backend calculations remain the source of truth. Implement shared API contracts, typed models, capability discovery, errors, idempotent submission handling and contract tests. Native mobile cannot simply invoke CSRF/browser-session endpoints with an API key: add scoped supported APIs in the permitted development backend where required.

Use platform secure storage for credentials; review actual current storage behavior instead of trusting README security claims. Stream through existing WebSocket services, handle app pause/resume/token expiry/reconnect, and mark cached quotes stale/offline. Never queue trading orders for an automatic send after reconnection. Mobile is a client; persistent scanner/strategy/sandbox monitoring runs on the server.

Deliver incrementally: (a) connection/auth/account state and themes; (b) trading, charts, calculators, books/funds/positions; (c) scanner/watchlists/sandbox portfolios and backtest reports; (d) strategy/tools/Historify/Flow/Python/settings/logs parity. For complex editors, explicitly specify a functional responsive editor or authenticated embedded server view and track its limitations; do not replace required functionality with a “coming soon” page. Android is the initial existing platform target; preserve Flutter Web and record additional platform work separately.

Acceptance: end-to-end parity checklist against web; Android device/emulator and Flutter Web smoke tests; secure credential lifecycle; two-profile isolation; live updates and background recovery; sandbox actions never invoke live trading; `flutter analyze`, meaningful unit/widget/integration tests and a reproducible APK build. Report unsupported capabilities explicitly until implemented.

## Task 6 — Sandbox investment watchlists and portfolio tracking

Add a sandbox Investment Portfolio section with named watchlists categorized as Swing, Positional, Long-term and Mutual Funds. Reuse existing server watchlist identity/persistence where appropriate, while separating a symbol-to-watch from an actual recorded purchase. Entries support instrument, exchange/scheme ID, entry price, quantity/units, purchase date/time, optional SL/TP, notes and current quote/NAV with valuation timestamp.

Use a transaction ledger for recorded buys/sells, partial exits, fees, adjustments and optional dividends/cash flows. Derive open lots, remaining quantity, weighted cost, realized/unrealized P&L, invested amount, market value, return and days held. Preserve original purchase timestamps and an audit history of corrections. A symbol can exist in several styles without merging ownership accidentally. Scope all data by instance/user, sandbox portfolio and instrument identity; include connection identity where multiple hosts are aggregated.

Suggested additive tables: `investment_portfolios`, `investment_watch_items`, `investment_transactions`, `investment_lots` (or derived lot views), `investment_valuations`, `investment_events`. Use Decimal monetary values and fractional units for mutual funds. Document FIFO or weighted-cost realization policy and keep it consistent. Keep fees/cash and corporate-action adjustments visible; do not overwrite entry price with current quote.

For the user's ATHER ENERGY example: buy 100 at INR 1,000 -> invested INR 100,000; SL 900, TP 1,200. At price 1,100, unrealized gain is INR 10,000 (+10%) before fees; at 950 it is a INR 5,000 loss (-5%). Display purchase date, days held, current price/as-of time, SL/TP distance, quantity and style totals. Display risk to SL and gain to TP separately from realized results.

Default behavior is tracking/alert-only for SL/TP. A recorded historical purchase does not place a broker order, spend live cash or reset the intraday sandbox balance. If desired later, an explicitly selected simulated auto-exit policy can create paper ledger exits with a documented fill model. Do not attach swing/long-term entries to MIS daily square-off. Restart/offline monitoring cannot prove a missed threshold event from current LTP alone; show unknown/history-derived events with their source.

Mutual funds use scheme identifiers, fractional units and dated NAV, rather than exchange tick quotes unless the instrument is actually an ETF. NAV source/update frequency must be verified during implementation; stale or unavailable NAV is labeled. Record SL/TP if requested, but treat them as NAV-based watch thresholds, not intraday executable stops. Support multiple purchases/SIP transactions and redemptions without rewriting history.

Expose sandbox-only authenticated CRUD/ledger/valuation endpoints and common mobile contracts. Add style lists, detail timeline, transactions, portfolio summary, P&L charts and CSV export. The existing sandbox reset action must explicitly describe whether it affects these longer-lived portfolios; default preserve them unless the user chooses to reset/archive them.

Acceptance: exact ATHER example; multi-lot purchases, partial sale and fees; style isolation; fractional MF units/NAV staleness; persistence/restart; no daily square-off; no live endpoint calls; identical web/mobile valuation; schema migration preserving existing watchlists/sandbox history.

## Task checklist and next-agent procedure

| ID | Deliverable | Status |
|---|---|---|
| PLAN | Repository/source review, six-task plan, durable handoff | Complete |
| P0 | Resolve code-freeze boundary; safe development workspace; API/data inventory | Task 2 integration authorized by September 12 request; other tasks frozen and their boundaries unchanged |
| T1.1 | CSV catalog, DuckDB ingestion, coverage and missing-history report | Frozen - resume only after the user updates the strategy. Prior status: In progress: 93-file inventory and 1,573-stock catalog exported; full candle validation/ingestion acceptance pending |
| T1.2 | Baseline reproduction and approved enhanced execution contract | Frozen - resume only after the user updates the strategy. Prior status: In progress: original selftest and indicator parity pass; isolated fresh-cross default corrected; original historical execution baseline and final contract pending |
| T1.2a | Scanner-based trade eligibility: union of volume shockers/gainers/losers, historical snapshots and entry gate | Frozen - resume only after the user updates the strategy. Prior status: In progress: isolated 191-minute reconstruction/gated replay verified; full acceptance, latency/coverage studies and live integration pending |
| T1.3 | Full-universe scanner-selected 1m/5m reports and daily capital reconciliation | Frozen - resume only after the user updates the strategy. Prior status: In progress: September 11 through 12:26 replay with 48 trade charts reconciles; afternoon/full-history reports and unrestricted comparison pending |
| T1.4 | Bounded filter/exit research and holdout comparison | Frozen - resume only after the user updates the strategy. Prior status: Pending |
| T2 | Broker-neutral automatic live scanner; 50 volume shockers, price/volume %, index filters and row sparklines | Implementation complete and integrated locally; 76 backend tests, 5 navbar tests, 9 built-SPA browser checks, typecheck/build/lint and resource audit pass. Market-hours and broader account-live verification remain operational follow-up |
| T3 | AlgoMirror shared calculator, Delta adapter, simultaneous accounts | Frozen by user on 2026-09-12; not started |
| T4 | Theme foundation and full route-by-route UI migration | Frozen by user on 2026-09-12; not started |
| T5 | Flutter parity matrix, implementation and Android artifact | Frozen by user on 2026-09-12; not started |
| T6 | Sandbox style portfolios, ledger, valuations and watch thresholds | Frozen by user on 2026-09-12; not started |

Resume by reading root `AGENTS.md`, this file, then `context.md` for prior implementation history and `docs/INDEX.md` for canonical references. Check current Git status in every target repo and applicable nested instructions before editing. Do not redo the planning pass or treat older task numbers as these tasks.

Next concrete work: no Task 1 or Tasks 3-6 implementation until the user resumes them. Task 2 is integrated locally; use the current checkpoint above for usage and pending live operational checks. For Task 1, receive the strategy update first, then resume from existing saved research artifacts without redoing completed downloads.

At each milestone update this file with date, completed checklist rows, changed files, commands/results, data/run IDs, remaining decisions and next command. Keep credentials and account payloads out. Do not mark implementation complete merely because a plan or test scaffold exists.

## Restart milestone — 2026-09-11

The user requested resumption. Inspection found an existing untracked `backtesting/all_stock_ha/` implementation and outputs which were not recorded in the planning checklist. Treat these as inherited work, not as evidence that the six tasks were complete. Its original `smoke_v1` selects ATHERENERG/RELIANCE with research enabled, but has only partial ATHERENERG 1m outputs, zero `done.json` markers and a research DB status of `running`. This session did not overwrite those files or change that DB status.

### Safe development location

- New isolated **research copy**, not a Git checkout: `.development/six-task-research/`. It contains the research Python files and a frozen copy of `backtesting/stratagies/ha_bb_vwap_strategy_astra.py`; it does not contain application databases or credentials. Use the original backtesting virtual environment to run it.
- The original code-freeze question was sent again during resumption; no answer was received at this milestone. The separate-copy fallback in this plan was used. No permission to edit original Indian/Crypto application code is inferred.
- Original `data.py`, `engine.py`, `report.py`, and `run.py` still match all four hashes in the inherited smoke manifest. The original strategy copy matches its recorded hash. Original application code and both source databases were only read.
- Sibling AlgoMirror, Crypto and mobile Git status were clean at inspection, using command-local `git -c safe.directory=<exact path> -C <path> status --short`; no persistent Git configuration changed. Existing `task.txt`, scanner-plan additions and untracked original research files were preserved.

### Data evidence

Artifacts: [audit summary](artifacts/2026-09-11-resume-audit/summary.json), [CSV inventory](artifacts/2026-09-11-resume-audit/csv_inventory.csv), [Historify catalog](artifacts/2026-09-11-resume-audit/historify_catalog.csv).

- Inventoried 93 CSV files across stock lists, backtesting, data, `D:/Personal/CSVs` and the ATHERENERG Historify export. This includes seven generated research outputs. All 86 previously catalogued files still exist and match their stored SHA-256 hashes.
- Existing research catalog: 85 imported files and one quarantined reference file. `D:/Personal/CSVs/broker_charges_comparison.csv` has extra fields at data row 119. Keep it quarantined; no source repair or tariff assumption was made.
- Historify opened successfully in read-only mode without touching its lock file. `data_catalog` reports 1,573 NSE 1m instruments and 859,377,449 rows. Date spans are at least five years for 999 instruments and at least ten years for zero. These are **metadata date spans**, not proof of complete or valid history. Ten-year reports cannot be represented as complete from this source.
- Only the two smoke stocks received row/session validation in this milestone: ATHERENERG 126,419 source rows, 336 retained full sessions, 2 excluded sessions; RELIANCE 851,008 source rows, 2,207 retained full sessions, 72 excluded sessions. Exclusions remain in each report's `sessions.csv`. This validation assumes normal 09:15–15:30 sessions; exchange-calendar verification is outstanding.

### Isolated corrections and verification

Changed only isolated `engine.py`, `run.py`, and `test_engine.py`: fresh-cross signal mode is now the default; continuation mode is a separate `rolling_continuation` experiment excluded from filter/exit selection; the manifest accurately names the selected signal policy. Added a fixture where two consecutive outside-band candles produce one fresh signal versus two continuation signals.

Commands, from `D:/Personal/openalgo`:

```powershell
& backtesting/.venv/Scripts/python.exe -m pytest .development/six-task-research/backtesting/all_stock_ha/test_engine.py -q --confcutdir=.development/six-task-research/backtesting/all_stock_ha -o addopts= -p no:cacheprovider
& backtesting/.venv/Scripts/python.exe .development/six-task-research/backtesting/stratagies/ha_bb_vwap_strategy_astra.py selftest
& backtesting/.venv/Scripts/python.exe .development/six-task-research/backtesting/all_stock_ha/run.py run --historify D:/Personal/openalgo/db/historify.duckdb --symbols ATHERENERG RELIANCE --rollover fresh --out .development/six-task-research/backtesting/all_stock_ha/smoke_fresh_v1
```

Results: **11 pytest tests passed**; original strategy selftest passed (NumPy timedelta deprecation warning). Initial sandbox pytest access to its existing temporary directory was denied; the approved escalated rerun passed. Smoke run completed all four stock/timeframe results, with 42/12 ATHERENERG and 66/21 RELIANCE trades for 1m/5m respectively. No research sweep or live operation ran.

Run ID: `1669d7de00814c6b777ad18eb0bc4380a62517a3dd738ba963c93245d1fcd3b8`.

Report: `.development/six-task-research/backtesting/all_stock_ha/smoke_fresh_v1/index.html`. [Reconciliation evidence](artifacts/2026-09-11-resume-audit/smoke_verification.json) confirms trade counts, ledger P&L/costs, daily totals, six calendar-period groupings, per-trade notional <= INR 100,000 and both aggregate portfolio totals. Four completion markers exist. This is an enhanced-execution pipeline smoke test, **not** reproduction of the original confirmation/next-open historical strategy or a completed all-stock baseline.

Resource audit scoped to this copy: DuckDB connections use context managers; CSV/file reads and NumPy archives use context managers/finally cleanup. The command completed and exited, releasing resources. No service, socket, thread or cache lifecycle was introduced by the correction. Full-universe memory/scaling behavior remains unverified; aggregation retains per-stock trade frames and a calendar-minute timeline and should be bounded before scaling.

### Remaining gates before larger runs

1. Reproduce the original historical execution baseline; preserve configurable original breakout source and exit modes in the enhanced model. Existing parity tests cover indicators/default long signals, not original historical P&L.
2. Validate per-symbol ticks, calendar exceptions, adjustment/source policies, missing whole sessions and cross-file conflicts. Current strict session exclusion changes retained HA history and the set of prior volume sessions; determine/report the correct continuity policy.
3. Replace the metadata-only run fingerprint with immutable candle-content versions for trustworthy resume after source changes. Existing catalog hashes and file size cannot detect every price correction.
4. Review all entry/exit ambiguity cases: entry-bar stop/target ordering requires more than the current target-first sensitivity, and rejected entries need recorded reasons. Final execution choices remain those listed in T1.2.
5. Current costs are illustrative 5 bps per side plus 5 bps slippage; itemized broker charges, real tick metadata, authentic benchmark coverage and a constrained-capital replay are absent. Do not present the smoke results as investment recommendations or verified net broker returns.
6. Improve report missing/research-not-run states and bounded aggregation; complete baseline reporting before enabling research. Existing research selection needs short-history/empty-fold validation before any sweep.

Resume with the isolated source and these artifacts; do not rerun or overwrite the inherited `smoke_v1` as if it were an approved baseline. Use a new output directory whenever inputs or code change.

### Today's scanner request — 2026-09-11, 10:48 IST

The user requested today's volume shockers and top gainers/losers. Ran the existing scanner with `uv run --no-sync python scripts/market_scanner.py --limit 50 --output tmp/market-scanner-2026-09-11.json`. The first quote batch returned HTTP 401 and the scanner stopped with `Fyers authentication failed. Log in again.` No current quotes were obtained (0/2,643); empty result lists mean authentication failure, not absence of market movers. User must renew the Fyers login in OpenAlgo before rerunning that command. The prior `tmp/market-scanner-today.json` snapshot is dated September 10 and must not be shown as September 11 data. No application code changed for this request.

**Retry succeeded after the user requested “RETRY NOW”.** The same command ran from 11:18:56 to 11:36:24 IST on September 11. Scan ID `ab28f03978f848aa8caec970879b3b76`: 2,642 instruments scanned, 2,625 valid current-day quotes, 2,622 usable five-session baselines; 233 volume shockers (>1x RVOL), 736 gainers and 1,855 losers. Top 50 per list saved in `tmp/market-scanner-2026-09-11.json`. Partial coverage: 17 stale/invalid quotes, two insufficient histories and one unavailable history. No rate-limit retries; normal history pacing accounted for the approximately 17.5-minute first scan. Quotes refreshed after baseline loading. These are intraday snapshots, not closing results.

Added standalone presentation/verification utilities in `.development/market-scanner-report/`, preserving original application code. `verify.py` independently checked all 150 ranked rows against current-day timestamps, sort order, previous-close percentage change and the read-only cached historical volume baselines. Evidence: `tmp/market-scanner-2026-09-11-verified.json`. `render.py` generated the searchable three-tab report at `tmp/market-scanner-2026-09-11/index.html` with separate price/volume percentages, RVOL, timestamps, coverage notes and three CSV downloads. This standalone snapshot report does not implement T2's integrated live UI, categories or sparklines. The utilities perform no broker calls; all file/SQLite handles close explicitly or via context managers. Python compilation and report structure/link checks passed.

Re-render without a new broker scan:

```powershell
& .venv/Scripts/python.exe .development/market-scanner-report/verify.py tmp/market-scanner-2026-09-11.json
& .venv/Scripts/python.exe .development/market-scanner-report/render.py tmp/market-scanner-2026-09-11.json tmp/market-scanner-2026-09-11/index.html
```

## Latest milestone — today's scanner-selected backtest and every trade plot

The user requested today's scanner, a backtest on its candidates, and each trade plotted, then requested resumption. The initial download completed while work was interrupted. Resumption reused the saved inputs and did not restart the completed download. No answer was received to the optional period question; the stated default, today's session so far, was retained with its original frozen cutoff.

**Run directory:** `.development/market-scanner-report/runs/2026-09-11-1226/`.

**Final backtest:** [backtest-v4/index.html](../../.development/market-scanner-report/runs/2026-09-11-1226/backtest-v4/index.html).
**Current-list snapshot:** [scanner/index.html](../../.development/market-scanner-report/runs/2026-09-11-1226/scanner/index.html).
Use `backtest-v4`; earlier `backtest`, `backtest-v2` and `backtest-v3` folders are superseded intermediate artifacts. Do not use the first version's chart count: a duplicate filename defect was corrected before final delivery. The final version has 48 unique trade IDs and 48 distinct chart pages, all verified.

### Inputs and selection

- Scanner `871316bcfe544ddbbb68bbf80072fe60` completed September 11 at 12:26:48 IST: 2,642 configured instruments, 2,628 valid quotes, 2,626 volume baselines, 319 volume shockers, 778 gainers, 1,812 losers; top 50 each, 127 unique current candidates. Fourteen stale/invalid quotes and two insufficient histories make coverage partial.
- Fetched one-minute history for all 2,642 instruments with no request errors. The frozen execution window is **09:15–12:26 IST**, containing 191 completed minutes; no afternoon data enters this run. The first 127 current candidates received 50 calendar days of warmup; an additional 25 historical candidates were fetched after reconstruction. Inputs live under `inputs/today` and `inputs/warmup`; hashes are in `input_hashes.json` and the final report manifest.
- Reconstructed the three top-50 lists at each completed minute using the same full configured universe, with price change against Fyers previous close and scanner RVOL against five prior daily volumes. No final midday list is applied backward to choose morning entries. Existing candidates retain indicator warmup even when outside a list.
- **Partial historical coverage:** 2,078 instruments have usable continuous minute history through the cutoff. Missing bars are not fabricated; input problems/continuous-prefix exclusions are in `reconstructed_coverage.csv`. The reconstructed rankings are within this available coverage, not an assertion of exact full-exchange rankings. The broker's EQ universe can include ETFs, which remain explicitly disclosed.
- 376 instruments entered at least one reconstructed list. Of these, 73 could also satisfy the preserved strategy volume gate (20 prior full daily sessions, RVOL >= 2); 72 were evaluated at 1m and 5m, while INFRA was excluded for insufficient warmup history. Others have explicit no-trade/coverage statuses. Trades occurred in 31 instruments. This avoids selecting history solely from the final 127-stock snapshot. `scanner_snapshots.csv`, `scanner_memberships.csv` and `rankings.npz` retain selection attribution.
- A BSOFT candle revision was found when comparing the later warmup response with the original today download. `read_candles()` now always preserves the original today bars for both ranking and execution; later warmup contributes prior days only. All 25 overlapping downloads were checked against this rule. Original raw files remain available and hashed.

### Results at the saved cutoff

Each timeframe is an independent simulation with INR 100,000 notional per entry and concurrent stocks. Costs/slippage remain illustrative, as below. Open trades are marked at the last completed candle, with entry costs deducted; they are not forced into synthetic exits.

| Timeframe | Trades | Closed / open | Closed net P&L | Open marked P&L after entry cost | Combined net / marked P&L |
|---|---:|---|---:|---:|---:|
| 1m | 43 | 29 / 14 | -14,667.52 | -3,591.46 | -18,258.98 |
| 5m | 5 | 1 / 4 | -1,563.05 | +1,628.82 | +65.77 |

The report contains every trade's real 1m candlestick chart, a separate signal-timeframe HA/BB/VWAP panel, signal marker, entry, exit or open mark, SL/TP levels, quantity, source-list ranks and costs. It includes searchable trade links, per-stock no-trade reasons, rejected signals, CSV ledgers, portfolio timelines and a price-only NIFTY reference (+0.2879% over this window). Return denominators and capital requirements are stated; Sharpe is N/A for a single partial day. Reference capital is INR 100,000 per ever-selected instrument (INR 37.6 million), not an assertion that a single lakh funded every concurrent position.

### Verification and limitations

- Eight focused tests passed in `test_intraday.py`: full-universe top-50/overlap behavior, previous-close math, missing-minute exclusion, signal/entry gating, continued position management after removal, open marks, ambiguity/ledger reconciliation, future-price independence of earlier entries, signal-driven direction and 5m entry rechecking.
- `verify_backtest.py` passed all 48 trade rows: causal times, signal/entry rank attribution, 20-session volume threshold, lot/quantity/notional constraints, closed/open cutoff behavior, fees/P&L reconciliation, local chart links, all source hashes and original-today precedence for the 25 overlaps. Evidence: final `verification.json`.
- Playwright with installed Chrome rendered all 48 chart pages, verified trade markers/search and recorded no page errors. Evidence: `browser-verification.json`, `overview.png`, `example-trade.png`. The initial missing bundled Playwright browser was resolved using installed Chrome; no browser download was needed. Visual inspection led to clearer spacing/time labels between chart panels.
- Resource audit: SQLite connections close in `finally`, gzip/files and NumPy archives use context managers, provider calls use the existing limiter, and the headless browser closes in `finally`. No app-level worker/cache/socket lifecycle was introduced. Original application trees were unchanged. No live orders were placed.
- Still provisional: zero modeled processing delay at historical minute close, incomplete universe/history coverage, current master metadata, 50-day HA initialization rather than full-history identity, unverified corporate-action adjustments, and 5 bps fees per side plus 5 bps slippage. Three 1m trades have ambiguous OHLC ordering and use stop-first treatment. A richer ordering sensitivity analysis and itemized broker charges remain pending. Existing daily-session volume cache is used explicitly; complete source/calendar validation is outstanding.
- This run demonstrates isolated selection/execution/report plumbing on a partial day. It does not complete all T1.2a acceptance tests, establish full-history performance, implement T2's continuous live service, or authorize strategy deployment.

### Reproduction and next command

From repository root; all commands use existing inputs unless a new fetch is explicitly chosen:

```powershell
& backtesting/.venv/Scripts/python.exe -m pytest .development/market-scanner-report/test_intraday.py -q --confcutdir=.development/market-scanner-report -o addopts= -p no:cacheprovider
& backtesting/.venv/Scripts/python.exe .development/market-scanner-report/verify_backtest.py .development/market-scanner-report/runs/2026-09-11-1226/backtest-v4
node .development/market-scanner-report/verify_browser.cjs .development/market-scanner-report/runs/2026-09-11-1226/backtest-v4
```

The pipeline is `fetch_backtest.py` -> `reconstruct.py` -> additional warmup fetch listed in `warmup_needed.json` -> `backtest_today.py` -> verification. `backtest_today.py` refuses a completed output directory; use a new `--report-name` after any code/input change. Its code is confined to `.development/market-scanner-report/`, with the preserved indicator implementation imported from the isolated `six-task-research` copy. Next work is an unrestricted comparison on the same frozen data and outstanding execution/data tests, or a separately versioned full-day extension if requested. Never silently relabel this 12:26 report as closing-day results.
