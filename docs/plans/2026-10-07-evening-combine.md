# October 7 evening local release

The user explicitly requested all isolated work combined locally, equity exits at
15:15 IST, recent log investigation, and a Git push. OpenAlgo remains stopped;
only the user starts production. This checkpoint supersedes earlier staged-only
and twenty-schedule notes.

## Combined features

- Eight new short equity Sandbox profiles in `strategies/short_equity`: Nifty500
  and weekday watchlists, 1m/5m, fixed 3R/trailing after 3R. Their README describes
  the precise HA/VWAP/lower-Bollinger rules and execution assumptions.
- All sixteen equity runtimes and saved schedules close at **15:15 IST**.
  Entry stops at the cutoff. A bounded Sandbox-only close window permits each
  known strategy to close its own filled quantity even when opposing strategies
  net to zero in the account. Pending covers reserve quantity; previous-day
  orders cannot authorize exits. Account-wide safety square-off resumes at 15:16.
- Twelve NIFTY option schedules and all their saved fields are unchanged.
  Their intraday exit remains 15:20 and process schedule stop remains 15:40.
- Portfolio Live/Sandbox separation and explicit order/GTT review, Reports
  journal/calendar, brokerage estimates, and individual trade charts are in the
  normal frontend build. Short charts show the lower Bollinger band and include
  both stop and target in the price range. Report writers capture broker context.
- Trade Copier dashboard/backend integrated. Local `.env` enables the feature;
  this does not create or arm any child. Credentials and account policy must be
  configured and explicitly reviewed/armed by the user. Bridge stays separately
  opt-in. The environment file and account data are not committed.

## Logs and restart recovery

The supplied FYERS remote-host losses successfully reconnect/authenticate and
resubscribe about five seconds later. Retained logs do not distinguish a broker
disconnect from a network interruption. No speculative FYERS parser/network
change was made. `Unknown data type: 0` cannot be diagnosed without its frame.
Throttle cleanup is routine; thread-count alerts shown auto-resolved. The invalid
Engine.IO session is a browser session event, not evidence of lost positions.

After the local proxy stopped, runners logged connection refusals to 8765. Their
closed WebSocket event loop then caused `disconnect()` to raise and leave a
coroutine unawaited. This local bug is reproduced and fixed: coroutine creation
happens on the running loop, the closing-loop race is handled, pending tasks are
drained, and shutdown joins the dispatcher. Option shutdown independently attempts
state persistence, final report, and resource cleanup even if another step fails.
This fix does not establish that remote FYERS disconnections are solved.

Read-only reconciliation found **six positional variants carrying fifteen legs**,
matching **twelve net NFO NRML Sandbox positions**. The six intraday variants have
no carried legs. Positional state in `db/nifty_options/state.sqlite3` and Sandbox
positions survive application restart. Saved intents/revisions/order tags support
recovery and duplicate protection. Existing stops and strategy rules can close
positions before expiry; restart does not promise holding to expiry.

While OpenAlgo/runners are off, they cannot monitor risk or execute strategy exits.
Clean shutdown marks processes stopped: restoring schedules does not necessarily
restart those runners immediately after a mid-session restart. Check Running
status and start intended runners if the day's scheduled start has already passed.

## Verification and preservation

- 482 focused backend tests; 31 frontend tests; normal TypeScript/Vite build.
- Production frontend bundle checked on isolated port 5011: Reports desktop/mobile,
  filters/trades/charts, Portfolio mode separation and mock order review, Trade
  Copier setup/arming/stop and mode partition. Synthetic data only; no broker orders.
- 100 repeated WebSocket loop/shutdown cycles: descriptors **4 → 4**, threads
  **1 → 1**, RSS approximately 44.7 → 45.1 MB. No accumulating sockets or threads
  measured in that reproduction. SQLite sessions, report handles, bounded copier
  queue/cache, executor shutdown and HTTP timeouts also reviewed statically.
- Original 20 configurations retained; only original eight NSE stop fields change.
  Eight new short configurations added atomically with a private backup under
  `log/test/oct7-combine/schedules-before-*.json`. Total: **28**.
- Sandbox positions/funds, scanner reports, and options state database hashes are
  unchanged from the 15:32 baseline. Five other operational DBs changed through
  15:39 while the installation finished stopping; their mtimes predate this final
  verification. They were not overwritten/restored. Post-stop hashes are recorded
  separately. No trading/portfolio data migration was executed.
- Empty weekday watchlists are preserved; the user supplies symbols before 09:00.
- Evidence is local under `log/test/oct7-combine/`; private snapshots/configs and
  unrelated backtest/image artifacts are excluded from the commit.

## User restart checklist

1. Start OpenAlgo using your normal command and log in to FYERS before trading.
2. Expect **28 restored schedules**. The next weekday start is 09:15 IST; check
   process status, fresh quotes, option recovery and any rejected/pending orders.
3. Confirm sixteen equity stops show 15:15, options schedules 15:40. Inspect the
   carried positional variants after they start; restarting tonight does not
   itself run the scheduled strategies overnight.
4. Open Portfolio, Reports and Trade Copier. Copier requires deliberate child
   setup/arming before copying. The eight new short strategies are paper trades.

Read-only schedule verification (no scheduler or database imports):

```sh
.venv/bin/python .development/oct7-combine/schedules.py
```

The offline migration script's `--apply` mode is for an explicitly authorized,
stopped installation only. Do not run it from tests or against a running instance.
