# OpenAlgo Documentation Map

**October 8 after-hours latency:** [Mock order timings, running-app probes and FYERS throttle fix](plans/2026-10-08-after-hours-latency.md). OpenAlgo is running; 300 mock/paper orders passed, no real orders sent. Market-closed measurements do not establish live execution latency.

**October 8 options backtest:** [Single offline HTML](../backtesting/options_3months_2026-10-07.html), [all 12 strategy results and assumptions](../backtesting/nifty_options/2026-07-08_2026-10-07/README.md) — July 8–October 7, current hedged rules, standard FYERS charges.

**October 8 current review:** [Main integration, whole-project checks and three-month options backtest](plans/2026-10-08-project-review-options-backtest.md). User authorized direct development and app start/stop. Main source and normal frontend are combined; app smoke passed and OpenAlgo is stopped with 28 schedules preserved.

**October 8 latency monitor:** [CSV diagnosis, consistent request metrics and accurate HTTP timing](plans/2026-10-08-latency-monitor.md). Now merged and verified in the normal build; earlier isolated-phase notes are historical.

**Current feature implementation:** [Portfolio, Reports/calendar, brokerage, Screener, Trade Copier and all 28 schedules](plans/2026-10-07-feature-implementation-status.md). Includes integration status, usage and remaining limits; the earlier backtest pause is superseded by the completed October 8 review above.

**October 7 evening:** [Combined release: 28 schedules, equity 15:15 exits, restart recovery, Reports/Portfolio/Copier integration](plans/2026-10-07-evening-combine.md). User starts OpenAlgo.

**October 7 Trade Copier:** [Local master/child copier handoff](plans/2026-10-07-trade-copier.md) — native FYERS/Zerodha/Dhan, bridge for other OpenAlgo brokers, separate Sandbox children, durable copy state/risk/stop controls. Integrated locally; children require configuration and deliberate arming. No real orders sent.

**October 7 equity shorts:** [Eight short counterparts and evening schedule handoff](plans/2026-10-07-short-equity-strategies.md) — 1m/5m Nifty500 and weekday-watchlist fixed/trailing variants, 109 checks passed; eight schedules installed alongside the original 20; 28 total. Equity exits at 15:15.

**October 7 Live/Sandbox follow-up:** [Portfolio, Reports, brokerage and Screener modes](plans/2026-10-07-live-sandbox-features.md) — separate ledgers, explicit real/simulated order paths, confirmed strategy-fill reporting and isolation evidence; integrated in the local build.

**October 7 brokerage follow-up:** [Broker-dependent report fee estimates](plans/2026-10-07-report-brokerage.md) — standard retail profiles, Sandbox/live-report parity, adjusted net results, sources and integrated broker-context writer hook.

**October 7 Reports update:** [Daily report journal and performance calendar](plans/2026-10-07-report-journal.md) — combined day/strategy/stock metrics, FY calendar and streaks; verified in isolation and integrated in the local build.


**Latest local release:** [October 7 combined Portfolio/strategy readiness](plans/2026-10-07-local-release-readiness.md) — production frontend built by request, 407 backend / 20 frontend checks plus browser verification, all schedules preserved, user startup checklist.

The entry point for humans and AI agents. This file is a **map, not a copy** —
it points at the canonical docs that already live under `docs/`. Edit a source
doc once; everything that reads through this map sees the change immediately.

**How to use (progressive disclosure):** read this map → open the one area you
need → drill into the specific file. Don't load everything at once.

---

## Using OpenAlgo (product, API, SDK)

October 6 session review: [All 20 scheduled strategies — single HTML](../backtesting/all_scheduled_20261006/index.html), [results and evidence](../backtesting/all_scheduled_20261006/README.md), [option capacity repair](plans/2026-10-03-nifty-options-strategies.md#october-6--capacity-repair-and-all-schedule-daily-backtest). 139 focused checks pass; scanner budget activation requires the user's restart. All schedules preserved; no production mutation.

October 6: [Investment Portfolio completion and deployment handoff](plans/2026-10-06-portfolio-completion.md) — all remaining asset classes, nine reports, categorized watchlists and existing-Sandbox paper GTT integration implemented and verified in development. Production deployment awaits “combine and launch.”

October 5: [Scheduled NIFTY option startup repair and daily Reports](plans/2026-10-03-nifty-options-strategies.md#october-5--scheduled-startup-repair-and-daily-reports) — subscription retries, 109 passing checks, twenty schedules preserved; future backtest outputs under `backtesting/`. Running OpenAlgo untouched.

October 4 final: [Complete readiness and Investment Portfolio handoff](plans/2026-10-04-readiness-portfolio-handoff.md) — what changed, architecture, verification, scheduler recovery, accepted decisions, running app state and remaining phases. Work stopped at user request; OpenAlgo left running.

October 4: [Monday readiness checks](plans/2026-10-04-monday-readiness.md) — verified restart of 20 schedules, full automated checks and operational limits.

October 4: [Combined NIFTY three-month dashboard](../backtest/nifty_options/2026-07-03_2026-10-01/results/combined_dashboard.html) — all 12 strategies, cycle win rates, profit factors, trade counts and six comparison charts.

October 4 (evening): [Parallel-development standing order](plans/2026-10-04-readiness-portfolio-handoff.md#0-standing-order--develop-in-parallel-never-affect-the-users-openalgo)
— **read before any work in this repository.** The user trades with OpenAlgo while
Portfolio work continues. Never signal an OpenAlgo process, never start the production
app, never write production databases, never run pytest without its data-directory
isolation, never rebuild `frontend/dist` while the instance serves it. Development uses
port 5011 and `log/test/` databases. Portfolio code ships only on "combine and launch".
Also mirrored at the top of the root `AGENTS.md`.

October 3: [Twelve NIFTY options strategies — active checkpoint](plans/2026-10-03-nifty-options-strategies.md)
— persistent sandbox strategies; completed three-month backtest, verified ledgers and local dashboards.

October 1: [Today's eight scheduled strategy backtests](../backtesting/eight_scheduled_20261001/README.md)
— 73 scanner stocks, 20 Thu stocks, both modeled paths, full coverage and verified
trade ledgers; interactive offline report and CSVs.

October 1: [MCP local desktop setup](../mcp/README.md) and
[watchlist API](api/symbol-services/watchlist.md) — Codex/ChatGPT desktop/OpenCode,
paste stock lists to add/remove from saved watchlists, plus expired F&O tools.

October 1: [Expired F&O discovery and historical data](api/market-data/expired-fno.md)
— three authenticated API endpoints, FYERS support, intraday candles/OI,
date limits, error handling and a Python workflow.

September 29: [Stock symbols and category database](../Stock_Symbols/README.md)
— supplied index/sector lists, industry groups, SQL queries and repeatable import.

September 30: [Eight Nifty500/weekday-watchlist Sandbox strategies and app reports](../strategies/top_gain_volumes/README.md)
— ₹10,000 per trade, four 1m + four 5m HA fixed/trailing 3R variants, active NSE schedules, September 29
replays, display-only Chg% controls and measured Go/Rust acceleration.

September 30: [Completed backtest of all eight scheduled strategies](../backtesting/eight_scheduled_20260930/README.md)
— 1m/5m results, modeled path assumptions, coverage, interactive report and trade CSVs.

September 30: [Four-strategy chart guide](../strategies/FOUR_STRATEGIES_CHART_GUIDE.md)
— separate signal/entry/exit diagrams, sizing examples and offline interactive
charts explaining fixed 3R versus BB-middle trailing, using illustrative prices.

Current cross-project work: [Portfolio section plan (2026-10-02)](plans/2026-10-02-portfolio-section-plan.md)
— a new Investment Portfolio section: ten asset classes (Stocks, Mutual Funds, ULIPs, Fixed Income,
Bullion, Property, Loans, Other Assets, Other Borrowings) with full read/write, a timestamped
transaction ledger, nine reports, portfolio scoring and charts. This unfreezes Task 6 of the
six-task roadmap and supersedes its scope. The initial ledger + Dashboard/Stocks slice is
implemented and deployed. User accepted the ATHER reconciliation baseline. Remaining classes, nine reports, categorized watchlists and existing-Sandbox paper GTT are now complete in development; deployment is pending.
Work is stopped at user request; all OpenAlgo processes were stopped so the user can restart
clean, and further development stays in an isolated lane per the standing order above.

Current cross-project work: [Six-task roadmap and agent handoff (2026-09-11)](plans/2026-09-11-six-task-roadmap.md)
— all-stock backtesting, live scanner, AlgoMirror crypto calculator, themes,
mobile parity and sandbox investment portfolios. Task 2 is integrated at `/market-scanner`, with backend/browser/build/resource checks passing. The subsequent strategy update and September 11 CSV comparison of all 404 HA/BB/VWAP V1 versions are complete. The separately authorized all-stock DuckDB runner and dashboard are implemented and verified with synthetic tests; historical execution has been launched and remains incomplete. Other Task 1 work and Tasks 3-5 remain frozen; Task 6 was unfrozen on 2026-10-02 and now follows the Portfolio section plan above. Market-hours and broader broker operational verification remain documented follow-up.

| Read this when you need… | Entry point |
|---|---|
| The REST API (`/api/v1/`) — orders, market data, options, account, streaming | [api/README.md](api/README.md) |
| Personal holdings — investment ledger, valuation, scoring and reports | [Portfolio section plan](plans/2026-10-02-portfolio-section-plan.md) |
| The Python SDK — install, client, data/order/account calls | [<prompt/openalgo python sdk.md>](<prompt/openalgo python sdk.md>) |
| Symbol format across exchanges (equity/futures/options) | [prompt/symbol-format.md](prompt/symbol-format.md) |
| Order constants (exchange / product / price-type / action codes) | [prompt/order-constants.md](prompt/order-constants.md) |
| Contract lot sizes | [prompt/LotSize.md](prompt/LotSize.md) |
| WebSocket subscription & message format | [prompt/websockets-format.md](prompt/websockets-format.md) · [prompt/websockets-verbose-control.md](prompt/websockets-verbose-control.md) |
| Service-layer functions & Flow JSON import | [prompt/services_documentation.md](prompt/services_documentation.md) · [prompt/flow-import-format.md](prompt/flow-import-format.md) |
| Strategy module & risk engine (multi-leg options, signal mode, RMS) | [prompt/strategy_rms_documentation.md](prompt/strategy_rms_documentation.md) · [api/strategy-services/](api/strategy-services/) · [prd/strategy-module-rms.md](prd/strategy-module-rms.md) · [bdd/strategy_module_rms.feature](bdd/strategy_module_rms.feature) |
| Technical indicators (`ta` library) | [<prompt/indicators/openalgo indicators - introduction.md>](<prompt/indicators/openalgo indicators - introduction.md>) |
| September 12 HA/BB/VWAP buy/sell strategy definitions, variants and code-only contract | [Strategy package](../strategies/ha_bb_vwap_v1/README.md) |
| September 25 fixed HA1m buy / BB / VWAP / 3R strategy: completed five-year available Nifty 50 DuckDB replay, HA candles and charts | [New-PC results and commands](../narasimha_pc_backtest/README.md) · [Exact strategy rules](../narasimha_pc_backtest/STRATEGY.md) |
| September 25 only: volume shockers/top gainers replay and local paper deployment status | [Scanner basket results and paper package](../narasimha_pc_backtest/today_20260925/README.md) |
| September 11 CSV comparison of all 404 HA/BB/VWAP V1 versions, reports and every trade chart | [Backtest report](../backtesting/ha_bb_vwap_v1_20260911/results/index.html) · [Method and reproduction](../backtesting/ha_bb_vwap_v1_20260911/README.md) |
| All-stock DuckDB HA/BB/VWAP backtest, run/resume commands and interactive historical dashboard | [Runner and dashboard guide](../backtesting/ha_bb_vwap_allstocks/README.md) |
| Four selected September 11 leaders on full DuckDB history; stopped by user September 15, incomplete | [Selection, run and resume guide](../backtesting/ha_bb_vwap_allstocks/SELECTED_FOUR.md) |
| Four selected versions on January-June 2026 Nifty 50 data; 49 available stocks, BAJAJ-AUTO missing | [Six-month run and coverage](../backtesting/ha_bb_vwap_allstocks/NIFTY50_2026_H1.md) |
| Completed ETHFUT 24/7 replay of all 404 versions on supplied April-May 2024 trade archives | [Interactive report](../backtesting/ethfut_404/results/index.html) · [ETH runner and assumptions](../backtesting/ethfut_404/README.md) |
| Portable BTC/ETH/SOL/XAUT trade-to-HA conversion and S029/S104/S232/S344 replay code for the new PC | [Transfer package and Windows commands](../backtesting/crypto_four_portable/README.md) |
| The charting terminal at `/trading`, its order dock and its shortcuts | [userguide/32-charting-terminal](userguide/32-charting-terminal/README.md) |
| Position calculator, brokerage estimates and automatic exit watches | [Position calculator](userguide/32-charting-terminal/position-calculator.md) |
| Planned Fyers historical backfill: 1,500 stocks, 5-minute candles, nine years | [Fyers download plan](plans/2026-09-08-fyers-historical-data-download-plan.md) |
| Writing your own chart indicators for `/trading` | [custom-indicators.md](custom-indicators.md) |
| Step-by-step user guide (setup → first order → integrations) | [userguide/README.md](userguide/README.md) |
| MCP tool reference (Claude Desktop / Cursor / Windsurf) | [mcp-tool-reference.md](mcp-tool-reference.md) |

## Install, deploy & operate

September 29 target repository and Mac setup:
[OpenAlgo_MVP clone, encrypted restore and macOS commands](installation-guidelines/macos-local-fork.md).
This supersedes the old sole-remote destination in the historical migration guide.

For this private installation's new-laptop move and sole Git remote, start with [migration.md](../migration.md).

| Topic | Entry point |
|---|---|
| Ubuntu server install | [installation-guidelines/getting-started/ubuntu-server-installation.md](installation-guidelines/getting-started/ubuntu-server-installation.md) |
| Docker | [docker/README.md](docker/README.md) |
| Upgrade / SMTP / TOTP / forgot-password | https://docs.openalgo.in/installation-guidelines/getting-started/ |
| Broker integration (36 plugins) | [broker-integration-guide.md](broker-integration-guide.md) |
| Release notes & changelog | [releases/](releases/) · [CHANGELOG.md](CHANGELOG.md) |

## Feature surfaces

| Feature | Entry point |
|---|---|
| Agent (`/agent`) | [design/55-agent/README.md](design/55-agent/README.md) |
| Scalping Terminal (`/scalping`) | [scalping/PRD.md](scalping/PRD.md) |
| Scanner architecture | [scanner-architecture.md](scanner-architecture.md) |
| Live stock scanner: volume shockers, gainers/losers, filters and sparklines | [api/market-scanner.md](api/market-scanner.md) |
| Selected stock/crypto Bollinger crossing alerts: isolated dashboard, setup and exact rules | [Bollinger alerts](../.development/bollinger-alerts/README.md) |
| WhatsApp alerts | [whatsapp.md](whatsapp.md) |
| Telegram chart rendering | [telegram-chart-rendering.md](telegram-chart-rendering.md) |
| Health monitoring | [HEALTH_MONITORING_IMPLEMENTATION.md](HEALTH_MONITORING_IMPLEMENTATION.md) · [HEALTH_MONITOR_REACT_FRONTEND.md](HEALTH_MONITOR_REACT_FRONTEND.md) |

## Architecture, design & specs (contributors)

| Topic | Entry point |
|---|---|
| First-time contributor setup (devsprint prep) | [devsprint/README.md](devsprint/README.md) |
| System design (frontend, backend, DB, UI) | [design/README.md](design/README.md) |
| Product requirements — Flow, Python strategies, Strategy module & RMS, Sandbox, Historify, MCP, event bus, websocket proxy | [prd/README.md](prd/README.md) · [prd/PRD.md](prd/PRD.md) |
| BDD feature specs (Gherkin `.feature`) | [bdd/README.md](bdd/README.md) |
| WebSocket architecture & quote feed | [websocket-architecture.md](websocket-architecture.md) · [websocket-quote-feed.md](websocket-quote-feed.md) |
| Security audits | [audit/README.md](audit/README.md) |
| CI/CD | [prd/ci-cd.md](prd/ci-cd.md) |
| Benchmarks | [benchmarks/](benchmarks/) |
| Migration plans | [migration/](migration/) |
| Implementation plans | [plans/](plans/) |
| Testing guides | [test/](test/) |
| XTS API | [xtsapi.md](xtsapi.md) |

---

## Governance

- User responsibilities & risk ownership: https://docs.openalgo.in/responsibilities
- Repository: https://github.com/marketcalls/openalgo · Docs: https://docs.openalgo.in
