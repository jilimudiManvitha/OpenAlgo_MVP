# OpenAlgo — complete project handoff and migration guide

Archive prepared October 29, 2026. This is the single starting document for what
we built, what is complete, what is unfinished, and how to move this installation
to another system. It summarizes the repository and dated evidence; historical
test results below are not claims that those entire suites were rerun today.

Repository: https://github.com/jilimudiManvitha/OpenAlgo_MVP — branch `main`.
The starting commit for this archive was `49238be55` (October 8). The archive
commit adds the later research work, cached data and this handoff. Find it with
`git log -1 -- PROJECT_HANDOFF.md`; verify the remote before deleting local files.

## Current state and instructions

- The user requested a complete handoff, Git push and a migration ZIP before
  deleting this checkout. This authorizes archiving, not restarting trading.
- On October 29, TCP checks found no listeners on 5000 or 8765. No app or
  collector was started or signalled by the archive work. The last authorized
  operational state is **OpenAlgo stopped**, from October 13.
- The saved configuration contains **28 schedules**: 16 equity and 12 options.
  Its archive-time SHA-256 is
  `b2eff3bd363305624a0301468f7f4efb2ba9012b52058ed12eff771d8f02d51c`.
  This is an observation, not a value to restore over later user changes.
- Annual and April–July option collectors remain stopped and incomplete.
  Neither automatically resumes on the next day. Do not publish partial results.
- The scheduled strategy runners are Sandbox strategies. Portfolio/Copier live
  support does not convert those runners to live trading.
- Only start the migrated app after reviewing paths, schedules, mode and broker
  authentication. Do not submit orders as part of migration verification.
- Preserve the original Crypto project outside this repository; it is outside
  this archive. Roadmap Task 1 and Tasks 3–5 remain frozen unless requested.

## What the project contains

This is a customized OpenAlgo fork: Flask/Python backend, React/TypeScript/Vite
frontend, broker adapters, REST/MCP interfaces, WebSocket streaming, SQLite
operational state, DuckDB/history research and paper trading. It also includes
upstream OpenAlgo features; the table describes the main local work rather than
claiming every upstream feature as newly developed here.

| Area | Work completed and current behavior | Main references / locations |
|---|---|---|
| Position calculator | Capital/leverage sizing, Buy/Sell, Market/Limit, trade-type and risk inputs, integration with chart order tickets, brokerage estimates and Order Book charges. Live base orders do not automatically implement attached stops merely because those fields are supplied. | [Earlier implementation history](context.md), `frontend/src/components/trading/PositionCalculator.tsx`, `services/brokerage_charges.py` |
| Market scanner | Integrated broker-neutral scanner, volume shockers/gainers/losers, volume/price changes, categories/index filters and sparklines; lifecycle, pacing and streaming recovery fixes. FYERS streaming scanner capped at 1,000 symbols while retaining the REST universe. | [Canonical roadmap](docs/plans/2026-09-11-six-task-roadmap.md), `/market-scanner` |
| Equity strategies | Eight long profiles plus eight mirrored shorts: scanner/Nifty500 and weekday-watchlist selection, 1m/5m, fixed/trailing exits, HA/BB/VWAP rules, state/restart recovery and daily reporting. Scheduled 09:15–15:15 IST. | [Long strategy](strategies/top_gain_volumes/README.md), [short strategy](strategies/short_equity/README.md) |
| NIFTY options | Twelve variants: Delta, Premium and Iron Condor × intraday/positional × current/next expiry. Persistent positions, pending orders and loss cycles; all variants now require equal-quantity same-expiry 200-point wings. | [Rules, sizing and recovery](strategies/nifty_options/README.md), [implementation history](docs/plans/2026-10-03-nifty-options-strategies.md) |
| Investment Portfolio | Requested asset-class screens, transaction ledger, valuations, dashboard, nine reports, scoring/charts, watchlists, weighted-average and FIFO accounting. Separate Live/Sandbox accounts and explicit order/GTT review. Non-stock prices use manual/CSV input. Existing Sandbox GTT fills reconcile idempotently into the ledger. | [Completion](docs/plans/2026-10-06-portfolio-completion.md), [mode support](docs/plans/2026-10-07-live-sandbox-features.md), `services/investment_*`, `/portfolio` |
| Reports and calendar | Combined IST-day, strategy and stock metrics; trade charts; April–March performance calendar, filters and streaks; confirmed Strategy Builder fills and mode attribution. | [Report journal](docs/plans/2026-10-07-report-journal.md), `/strategy-reports` |
| Report brokerage | Eight standard retail broker profiles for supported NSE/NFO segments; estimated/recorded fees distinguished; recorded broker context and net P&L. Actual contract notes can differ. | [Brokerage handoff](docs/plans/2026-10-07-report-brokerage.md) |
| Trade Copier | Master/multiple children; native FYERS, Zerodha and Dhan, gateway children for other adapters; Live/Sandbox separation, encrypted credentials, deduplication, partial fills, reconciliation and risk/stop controls. Children must be configured and deliberately armed. | [Copier handoff](docs/plans/2026-10-07-trade-copier.md), `/trade-copier` |
| Latency and FYERS reliability | Separated order/data metrics, consistent filters, corrected HTTP attribution, bounded telemetry, retry/cooldown handling and preserved 429 responses. Startup ordering, token lookup pacing, session/subscription retry and capacity fixes. | [Integrated review](docs/plans/2026-10-08-project-review-options-backtest.md), [after-hours checks](docs/plans/2026-10-08-after-hours-latency.md), [rate-limit repair](docs/plans/2026-10-08-fyers-rate-limit-repair.md) |
| Margin/capital display | FYERS option-basket margin and capital utilization display; sizing verification and documented estimates. | [Capital display](docs/plans/2026-10-08-fyers-capital-display.md), [capital checks](docs/plans/2026-10-08-options-capital-check.md) |
| Expired F&O API | Authenticated expiry discovery, contract discovery and historical candles/OI through FYERS, with bounded windows, validation and explicit unsupported/no-data errors. Not an automatic Historify import or a new trading strategy. | [API guide](docs/api/market-data/expired-fno.md) |
| Watchlists and MCP | Authenticated watchlist CRUD/batch edits shared with the chart; eight watchlist and three expired-F&O tools. Historical local verification listed 60 MCP tools. Desktop launch uses a separate private key file; remote transport remained disabled. | [MCP setup](mcp/README.md), [watchlist API](docs/api/symbol-services/watchlist.md) |
| Research tooling | CSV/DuckDB ingestion, HA/BB/VWAP strategies, fixed strategy comparisons, daily equity replays, options replay engines, source hashes, ledger checks and offline HTML dashboards. Portable four-crypto package delivered separately. | `backtest/`, `backtesting/`, `narasimha_pc_backtest/`, [crypto package](backtesting/crypto_four_portable/README.md) |
| Migration and development tools | Earlier encrypted installation snapshots, local Mac restore guide, isolated fixture servers, tests and archived development lanes. | `portable-backup/`, `scripts/migration_backup.py`, `.development/`, [old Mac guide](docs/installation-guidelines/macos-local-fork.md) |

Portfolio, Reports, Copier and the short strategies were combined into the normal
application on October 7; latency followed on October 8. Older documents saying
these remain isolated or await “combine and launch” describe earlier checkpoints.
Implementation/integration is not proof of successful real-account execution.

## Timeline of the work

| Period | Milestone |
|---|---|
| Earlier fork work | Position calculator, leverage and brokerage UI/backend; upstream merges and preserved custom order-ticket behavior. Historical task numbers in `context.md` differ from the later six-task roadmap. |
| September 11–12 | Six-task plan and boundaries established; scanner integrated. Other roadmap work frozen. Research prototypes and evidence retained without claiming full acceptance. |
| September 13–17 | Stock/DuckDB research, four selected strategy versions, ETH experiment, portable four-crypto package and selected-symbol Bollinger alert work recorded in the roadmap. The portable package delivery was not a claim that a full new-PC replay finished. |
| September 25–29 | HA/BB/VWAP equity strategy and scanner-selected paper workflows, research reports, stock categories, upstream synchronization and encrypted Windows-to-Mac installation backups. |
| September 30–October 1 | Eight equity schedules and daily backtests; startup/scanner/subscription reliability repairs; expired-F&O APIs and watchlist/MCP support. |
| October 2–4 | Broader Investment Portfolio approved; initial ledger/dashboard/stocks implemented. Twelve options variants added, taking schedules to 20. July–October initial options replay and comparison dashboard completed. Scheduler test isolation repaired after a caught configuration overwrite. |
| October 5–6 | Options subscription/startup/capacity repairs; all-schedule October 6 replay; remaining Portfolio phases completed in isolation. |
| October 7 | Portfolio and strategy fixes released locally; eight equity shorts, Reports/calendar/fees, mode support and Copier combined; schedules increased to 28. All options families updated to 200-point hedges. |
| October 8 | Latency integrated; full-project checks and runtime smoke; current-hedge July–October options replay complete. Annual collector developed, then stopped at user request. Separate previous-quarter collection started. |
| October 9 | Quarter collection paused for foreground quota contention, later resumed with app stopped/full daily quota; invalid provider ranges deferred; stopped at 5,000 shared requests. |
| October 13 | Six intraday options variants replayed for the completed session; data and results reconciled. User authorized stopping OpenAlgo and leaving it stopped. |
| October 29 | Project review, consolidated handoff, Git archive and private migration ZIP preparation. No new trading, data collection or production deployment. |

## Backtests: completed versus pending

OLHC and OHLC are alternative modeled candle paths; never add their results.
Historical Greeks, fees, margins, slippage and intrabar execution carry the
limitations in each report. These are simulations, not account performance.

| Scope | Status and result | Artifact |
|---|---|---|
| Eight equity schedules, September 30 / October 1 | Completed daily replays. October 1: 73 scanner and 20 Thu symbols, 16 scenarios, 1,240 modeled trade rows. Only Nifty500 fixed 1m was positive in OLHC (+₹536.55), negative in OHLC (−₹631.85); other profiles lost in both. Selection was retrospective. | [October 1 results](backtesting/eight_scheduled_20261001/README.md); September 30 references in the roadmap |
| Options, July 3–October 1 | Completed initial three-month replay: 64 sessions, 24 scenarios, 2,428 closed-leg rows. Nine variants positive and three negative in both paths. Preserves historical rules, including the earlier hedge behavior. | [Results](backtest/nifty_options/2026-07-03_2026-10-01/README.md), [combined dashboard](backtest/nifty_options/2026-07-03_2026-10-01/results/combined_dashboard.html) |
| All 20 schedules, October 6 | Completed daily review/replay with documented options startup/capacity failures and data/model limitations. | [Report](backtesting/all_scheduled_20261006/index.html), [methodology](backtesting/all_scheduled_20261006/README.md) |
| All 28 strategies, October 7 | HTML retained, but final preservation sign-off remained unresolved when paused. Schedule/operational DB hashes differed from the baseline; the cause was not established. Do not label this as a fully signed-off archive. | [Report](backtesting/all_strategies_2026-10-07.html), [limits](docs/plans/2026-10-07-feature-implementation-status.md) |
| Options, July 8–October 7 | **Complete**, current hedged rules: combined net **₹7,88,522.66 OLHC / ₹7,91,755.49 OHLC**, separate ₹20 lakh per strategy. | [Single offline report](backtesting/options_3months_2026-10-07.html), [methodology](backtesting/nifty_options/2026-07-08_2026-10-07/README.md) |
| Options, October 9, 2025–October 8, 2026 | **Incomplete / stopped by user**. 6,733 history chunks cached, 19,351 remaining. Final annual replay/HTML not produced. Calendar corrections are research-only. | [Handoff](docs/plans/2026-10-08-options-one-year.md), [archive](backtesting/nifty_options/2025-10-09_2026-10-08/README.md); intended `backtesting/options_1yearBacktest.html` |
| Options, April 8–July 7, 2026 | **Incomplete / quota stopped**. 2,404 histories cached, 4,558 ranges remaining, including four malformed provider ranges. October 9 shared usage reached 5,000 with zero reserve. | [Handoff](docs/plans/2026-10-08-options-previous-quarter.md), [archive](backtesting/nifty_options/2026-04-08_2026-07-07/README.md); intended `backtesting/options_3months_2026-07-07.html` |
| Six options intraday variants, October 13 | **Complete**. 948 contract requests; 12 scenarios. Each path: four completed cycles, one win, three losses, 25% win rate, zero open legs. Net **−₹49,359.13 OLHC / −₹49,359.87 OHLC**. Two current-expiry variants skipped by delta rules. | [Offline report](backtest/options_intraday_2026-10-13/results/index.html), [results and verification](docs/plans/2026-10-13-options-intraday.md) |

The incomplete collector counts above were reread from their saved status files
on October 29; they are checkpoints, not fresh broker requests. Resume only on a
new instruction, with valid login/quota and complete-data verification. Shared
FYERS quota can affect the foreground app even with a daily reserve or low CPU
priority. Never alter malformed prices to make the replay complete.

## Remaining work and known limits

- Finish annual/quarter downloads and their full replay, ledger and browser
  gates if requested; resolve the quarter's four invalid provider ranges.
- Real-market broker fills, multi-account Copier latency/soak, all broker
  adapters and cloud deployment are not comprehensively verified. Native Copier
  child token renewal remains manual; Stop does not flatten existing fills.
- Portfolio prices and reports use recorded valuations; they are not automatic
  fund NAV ingestion, a tax engine or fabricated historical TWR/XIRR. Live GTT
  depends on each broker adapter. Order acknowledgements are not confirmed fills.
- Report capital/fees and backtest margin are estimates or entry exposure, not
  universal historical SPAN or contract-note accounting.
- Carried option positions need fresh quotes and confirmed hedge fills during
  runner recovery. Updating source alone does not protect existing positions.
- Roadmap Task 1 still awaits the user's strategy update. Tasks 3 (AlgoMirror/
  crypto calculator), 4 (full UI/theme migration) and 5 (mobile parity app) remain
  frozen. Task 2 scanner is integrated; Task 6 Portfolio is implemented and
  integrated, superseding the roadmap's older “implementation not started” row.
- Historical operational issues and evidence remain in dated handoffs; do not
  interpret stale PIDs, empty-watchlist observations or old schedule counts as
  current instructions.

## Verification evidence

Historical milestones include October 8's 6,305 backend passes / 28 skips /
one expected failure, full frontend checks, integrated browser/runtime smoke,
and 300 mock/paper orders with 45 after-hours regression checks. October 13
includes source hashing, 32 closed-leg rows across 12 scenarios, cash-flow/fee/
lot reconciliation and desktop/mobile offline browser checks. See the dated
handoffs for exact coverage; market-closed mock results do not establish live
execution latency.

Fresh archive preparation ran **102 passing isolated tests**:

```sh
.venv/bin/python -m pytest test/test_options_year_collector.py \
  test/test_nifty_options_replay_calendar.py test/test_nifty_options_strategies.py \
  test/test_nifty_options_hedges.py test/test_python_strategy_config_isolation.py -q
```

The scheduler's known atexit logging warnings (`I/O operation on closed file`)
occurred after the passing test result; exit code was zero. Tests use
`test/conftest.py` to isolate databases, quota and schedule writes. Do not bypass
that isolation. This archive task did not rerun the full application suite,
start the app, rebuild the frontend or re-execute any market backtest.

Archive checks also confirmed all 28 saved schedule definitions read-only,
unchanged schedule hash, valid local Git LFS objects, and existing relative links
in this handoff. Candidate files were screened for four known local secret
values and common token/private-key markers with no matches; this is a scoped
screen, not a security audit of all Git history. The generated October 13 HTML
contains third-party Plotly trailing whitespace; it is preserved byte-for-byte.

## What Git preserves and what the private ZIP preserves

| Git repository | Private migration ZIP |
|---|---|
| Versioned source, tests, docs, existing frontend assets, research reports and eligible data/caches, including October 13 CSV downloads and incomplete collection manifests | The working project including Git-ignored local data: `.env`, `db/`, saved schedule configuration, strategy state, logs/test evidence, ignored CSVs, downloaded histories and existing frontend builds |
| Older encrypted September 29 backups via Git LFS, requiring their separately retained recovery keys | Current local files directly; no old encrypted-backup recovery key needed for the current DB/settings files |
| Does not contain current plaintext credentials, operational databases or the current saved schedules | Contains credentials and account data: **keep private; do not upload to Git or share publicly** |

ZIP destination: `../OpenAlgo_Migration_2026-10-29.zip` (the Downloads folder,
outside `OpenAlgo_Mac`). Alongside it are a SHA-256 checksum and verification
JSON. The ZIP contains `OpenAlgo_Mac/` and a file-hash manifest. The archive
builder reads back every member and compares SHA-256 hashes before publishing
the final filename. Its manifest records exclusions and the exact Git commit.

Excluded from the ZIP: `.git/` history, `.venv/`, `node_modules/`, Python bytecode,
tool caches and OS metadata. These are recoverable from Git or reinstallable;
platform-specific dependencies should be recreated on the destination. Hidden
project settings and data are included. Files outside this project, including
desktop MCP client configuration/key files and the separate original Crypto
source/data, are not included. The older September 29 backup is not a substitute
for the new ZIP's October state.

Do not delete the original until the Git push is confirmed and the ZIP and its
checksum have been copied to the destination or another durable drive. A ZIP in
Downloads survives deleting this project folder, but not losing this computer.

## Restore on another system

1. Transfer the private ZIP and `.sha256` file securely. Check its SHA-256 (macOS:
   `shasum -a 256 OpenAlgo_Migration_2026-10-29.zip`; Windows PowerShell:
   `Get-FileHash OpenAlgo_Migration_2026-10-29.zip -Algorithm SHA256`) against the
   sidecar. Extract into a new empty directory; include hidden files. Do not
   merge it into an unrelated live installation.
2. For continued Git development, install Git/Git LFS and clone
   `https://github.com/jilimudiManvitha/OpenAlgo_MVP.git`, run `git lfs pull`, then
   overlay the extracted project contents onto that matching clone, preserving
   the clone's `.git/`. The ZIP itself contains runnable source but no Git history.
3. Install Python through uv and a Node version supported by
   `frontend/package.json`. The project declares Python >=3.12; the archive
   verification environment used Python 3.13. Recreate dependencies from locks:

   ```sh
   uv sync --frozen --no-dev --python 3.13
   npm --prefix frontend ci
   ```

   Backtesting extras may need the dependencies described in each research
   README. A fresh-machine install has not been tested by this archival task.
4. Keep the restored `.env`, `APP_KEY`, `API_KEY_PEPPER`, encryption keys and
   databases together. Replacing those secrets can make saved encrypted values
   unreadable. Check `.env` paths, URLs and broker callbacks privately. Broker
   sessions expire; authenticate again before use.
5. Review `strategies/strategy_configs.json` **before starting**. It contains
   28 schedules and absolute paths referring to the old checkout. Update those
   paths for the new location; inspect any saved running/PID metadata and do not
   treat old PIDs as live processes. Review other launcher/client paths too.
   Do not run schedule installers merely to verify the migration.
6. Reconfigure desktop MCP clients using [mcp/README.md](mcp/README.md). Their
   settings and private key at `~/.config/openalgo/mcp-api-key` are outside this
   ZIP. Do not paste credentials into Git or documentation.
7. The ZIP retains the current frontend build. If rebuilding is necessary, run
   `npm --prefix frontend run build` while the app is stopped. Review schedules,
   execution mode and user account state before the user's deliberate start:

   ```sh
   uv run --no-sync app.py
   ```

   Default local UI: `http://127.0.0.1:5000`; WebSocket port 8765. Restored
   schedules may run at their next trigger, so starting is an operational action.
8. Verify login, portfolio/reports and saved schedules without placing orders.
   Resume research separately, only if requested. Historical absolute paths in
   manifests may need relocation for reruns; offline HTML reports remain viewable.

## Where to continue reading

[AGENTS.md](AGENTS.md) contains operating boundaries. [Documentation index](docs/INDEX.md)
maps the project. [Context](context.md) retains earlier fork history. The
[six-task roadmap](docs/plans/2026-09-11-six-task-roadmap.md) records the original
scope and frozen work; [feature map](docs/plans/2026-10-07-feature-implementation-status.md)
and [October 8 integration review](docs/plans/2026-10-08-project-review-options-backtest.md)
describe the combined application. Prefer the newest applicable checkpoint;
older notes are preserved as history, not instructions to undo later work.
