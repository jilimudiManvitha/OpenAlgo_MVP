# Previous three-month options backtest — April 8–July 7, 2026

**October 9 16:01 IST latest:** Collection stopped at 15:58:14 after exhausting the full 5,000-request daily budget (zero reserve). 2,404 histories cached (34.5%), 4,558 ranges remain including four invalid provider ranges. Process exited; final backtest/report pending complete valid data. Resume after quota reset and valid login, keeping OpenAlgo stopped.

**October 9 15:20 IST latest:** Download resumed at user request. Failure diagnosed as a malformed provider candle (open above high); invalid ranges are recorded separately and remain missing while other contracts download. Full replay and final report stay blocked until all required history is valid. Latest log: `log/test/options-previous-quarter/full-quota-20261009-151957.log`. Terminal progress: `.venv/bin/python .development/options-previous-quarter/status.py --watch`. See handoff for evidence and five passing isolated tests.

**October 9 15:13 IST latest status:** Collector exited at 15:07:29 after a generic `RuntimeError`. 739 files cached (10.6%), 6,223 ranges remaining; last shared count 3,320. Underlying cause not established. OpenAlgo remains stopped; no automatic restart. Final report pending. See the latest handoff for details.

**Latest, October 9 14:58 IST:** User requested the app stopped and full-quota collection. App/strategy runners were absent and ports 5000/8765 free. A live history check succeeded and the detached `--full-quota` run started: 363 cached files including index, 6,599 ranges remaining, 2,944 shared requests already used today. Zero foreground reserve; process-local published Standard cap 5,000/day and serial pacing below 50/minute, retaining shared counts and broker cooldown handling. The runner checks for an app restart before each new request and stops if detected. Another quota window is needed. Annual collection remains stopped; final HTML remains pending. These instructions supersede the older reserve/running-app notes below.

Current log: `log/test/options-previous-quarter/full-quota-20261009-145811.log`.
Persistent offline resume: `.venv/bin/python .development/options-previous-quarter/launch.py`.
See [latest handoff](../../../docs/plans/2026-10-08-options-previous-quarter.md) for verification and limits. No automatic next-day restart.

**October 9 latest — foreground quota contention:** User supplied FYERS 429 queue-busy/cooldown errors while OpenAlgo was running. The backtest shares that data quota; its daily reserve and low CPU priority do not isolate short-term API capacity. Stopped only the verified backtest collector; process exit confirmed. 362 total history files cached (including index), 6,600 option ranges remain. Do not automatically resume collection alongside the running app; foreground protection takes priority. Annual download remains stopped. No production process, database, schedule or asset was changed. User log showed MTM recovery to 29/29; local cooldown had expired at inspection.

**October 9: downloading after refreshed FYERS login.** User is now running OpenAlgo and requires it remain unchanged. The separate downloader uses a private authentication snapshot, shared Standard rate limits and the 1,000-request daily reserve. The earlier app-stopped notes below are historical. No completed quarter report yet; annual collection remains stopped.

**October 8 batch stopped at the configured daily reserve (shared count 3800).** 123 option histories plus the index file are cached; 6,838 option ranges remain. Collector exited normally with pending-report status (code 2). Resume after quota reset with a valid FYERS login. No final HTML has been generated.

**In progress: option data collection. No completed backtest or final HTML yet.**

The user requested stopping OpenAlgo and backtesting the three months immediately
before the completed July 8–October 7 report. This is a separate request; the
one-year download remains explicitly stopped.

Final output: **`backtesting/options_3months_2026-07-07.html`**.
Existing `backtesting/options_3months_2026-10-07.html` remains unchanged.

## Period and comparison rules

- April 8–July 7, 2026 inclusive: **61 exchange sessions**, verified against the
  cached FYERS NIFTY index observations and exchange calendar.
- All 12 current options variants with 200-point same-expiry protective wings.
- Same strategy engine, profiles, policy, selection, Greeks, hedge rules, state
  logic and brokerage module as the frozen July–October report: byte equality checked.
- Both OLHC and OHLC modeled minute paths, reported separately. No parameter fitting.
- ₹20 lakh allocated independently per strategy, 65-unit near-week NIFTY lots,
  standard FYERS retail estimated charges using actual modeled execution dates.
- Overall and per-strategy gross/net P&L, charge components, completed trades,
  wins/losses/breakeven, win rate, capital used, drawdown, open trades, monthly
  performance and per-option-contract leg grouping.
- Winning/losing cycles are classified by net P&L after fees. Win rate includes
  breakeven completed cycles in the denominator and excludes open cycles.
- Prior-close signals and next-open fills with ₹0.05 adverse slippage and tick
  rounding. Margins and Greeks are estimates. No synthetic candles or forced final exits.

## Data status and limits

The annual request had already discovered the actual FYERS option catalogue and
downloaded index data. Those are reused without resuming the annual job. The new
manifest contains **6,961 option contract/range entries** plus one cached index
file. No complete option-range files for this window were initially available;
partial cached ranges are reused where possible.

`download_status.json` is the current progress checkpoint. The collector uses the
shared **Standard** quota, reserves 1,000 of the internal 4,800 daily requests,
and stays below 30 requests/minute. The previous downloads have used most of
October 8's allocation, so completion needs additional daily quota windows and
a valid FYERS login. It stops at the reserve or on errors; there is no automatic
next-day resumption. No partial-period profit or win-rate figures are published.

## App state

OpenAlgo was already stopped when checked: no listeners on 5000/8765 and no app
or strategy-runner processes. The prior app log records graceful shutdown at
16:33 on October 8. All **28 saved schedules** remain unchanged, SHA256
`79593c33ba051796fec66ca8068e4b691ba5ef0e83bc376577bbd32382d588fe`.
Keep OpenAlgo stopped. Backtesting uses a private authentication DB snapshot,
read-only broker history, and files under `backtesting/`/`log/test/`; it does not
place orders or write to application Reports.

## Resume / verification

Run from the repository root after quota becomes available:

```bash
.venv/bin/python .development/options-previous-quarter/run.py
```

The script reuses validated cache, collects missing histories, runs both replay
paths only when complete, checks ledgers/source hashes/fees and all 24 strategy/path
variants, runs the offline browser verifier, then publishes the exact final HTML.
Incomplete collection returns exit code 2 with `report: pending` and no final HTML.

Local preparation only:

```bash
.venv/bin/python .development/options-previous-quarter/run.py --prepare-only
```

Replay already completed data:

```bash
.venv/bin/python .development/options-previous-quarter/run.py --report-only
```

Evidence: `calendar_preflight.json`, `manifest.json`, `download_status.json` and
`log/test/options-previous-quarter/run.log`. The reused collector's four behavior
tests passed after adding annual-cache reuse; critical lint passed. Full replay
and result/browser verification remain pending data completion.
