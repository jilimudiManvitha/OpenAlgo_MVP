# April–July options backtest checkpoint

**October 9 16:01 IST latest — daily quota exhausted:** Full-quota collector exited at 15:58:14 with shared usage exactly 5,000 and reserve zero. 2,404 total histories cached (34.5%); 4,558 ranges remain, including four deferred invalid provider responses listed in `download_status.json`. PID 10258 is absent. No restart performed at this status check. Resume after quota reset with valid login and OpenAlgo stopped; malformed ranges still require resolution before full replay/report. The saved reason says “reserve reached,” but this run had no reserve and reached the full daily cap.

**October 9 15:20 IST latest — resumed with invalid-range deferral:** User requested restarting download/backtest and a terminal text progress bar. Initial retry reproduced HTTP 502 / no broker code on `NSE:NIFTY2642123100CE`, April 8–21. Diagnostic response contains one malformed candle at timestamp 1776656700: open 1253.6, high/low/close 1184.7. Raw market-data fields saved to `log/test/options-previous-quarter/invalid-market-data.json`; prices were not altered. Quarter-only fetch hook now defers explicitly invalid provider responses, continues other contracts, records `deferred_ranges`, and withholds full replay/report while any range is missing. Other failures still stop normally; annual runner behavior is unchanged. Five isolated collector tests and critical lint passed. Detached full-quota resume: PID 10258 at launch, log `log/test/options-previous-quarter/full-quota-20261009-151957.log`. Verify live identity before acting on any PID.

Terminal status: `.venv/bin/python .development/options-previous-quarter/status.py --watch` (5-second refresh, Ctrl-C stops only the display). `--seconds 40` provides a bounded watch. User wants text terminal bars, not the earlier visualization. Full-quota, app-stopped and shared-counter guards remain active. Invalid provider range still needs resolution before final results can be published.

**October 9 15:13 IST status check (latest):** Full-quota collector exited at 15:07:29 with `Collection failed: RuntimeError`; process absence verified and OpenAlgo ports remain free. 739 files cached including index, 6,223 ranges remaining, 376 successful requests in this batch. Last recorded shared budget count 3,320 is not the daily ceiling; the generic exception checkpoint does not establish the underlying failure cause. No restart performed during this status-only check. Final report is still pending. Chat progress bar with explicit recheck action: `.development/options-previous-quarter/download-progress.html` (snapshot, not a live feed).

**October 9 14:58 IST — offline full-quota resume (latest):** User explicitly requested OpenAlgo stopped and this quarter resumed using full limits. Verified no app/strategy runners and ports 5000/8765 free; MCP helpers alone remain. One real FYERS history request succeeded, then launched the detached quarter runner with `--full-quota` (PID 8680 at launch, never assume it remains the same process). Log: `log/test/options-previous-quarter/full-quota-20261009-145811.log`; launch/baseline record: `log/test/options-previous-quarter/full-quota-launch.json`. At launch 363 files were cached including index, 6,599 ranges remained, shared daily count 2,944. About 2,056 requests remained of the published Standard 5,000/day; another quota window is necessary. No final report yet.

The offline flag removes the 1,000-request reserve, uses process-local published plan limits and faster serial pacing, and checks ports before every new request so it stops if the app restarts. Production limiter source/settings are unchanged; the shared usage counter is retained. Broker cooldowns/errors still stop collection; no automatic next-day resumption. FYERS also documents a separate Standard expired-intraday restriction; actual history access succeeded, but broker enforcement may stop this batch sooner. Annual collection stays stopped. User starts OpenAlgo; do not start it for research.

Resume while the app is stopped: `.venv/bin/python .development/options-previous-quarter/launch.py` (persistent session, log and sleep prevention). It automatically runs the replay and browser/ledger checks only after complete data, then publishes the final HTML. Four isolated collector tests and critical lint passed. Resource audit was static: socket/file contexts close on all paths, launcher exits and the detached child is adopted by the OS, output goes to a file rather than a pipe. Baseline schedule hash is now `79fdc6d521bc427309ffe9764d5ab207fffc0ff2ea6fdf8296962b9afdfbf3b6`, with all 28 schedules verified read-only; historical hashes below describe older state.

**October 9 latest — foreground quota contention:** User supplied FYERS 429 queue-busy/cooldown errors while OpenAlgo was running. The backtest shares that data quota; its daily reserve and low CPU priority do not isolate short-term API capacity. Stopped only the verified backtest collector; process exit confirmed. 362 total history files cached (including index), 6,600 option ranges remain. Do not automatically resume collection alongside the running app; foreground protection takes priority. Annual download remains stopped. No production process, database, schedule or asset was changed. User log showed MTM recovery to 29/29; local cooldown had expired at inspection.

**October 9 08:49 restart:** The prior collector disappeared without a final error checkpoint; its exit reason is unknown. Cached files were revalidated (175 entries, including index). Restarted in a separate OS session at nice priority 10 with the same shared rate limiter and 1,000-request reserve. Do not claim completion: full replay/HTML remain pending. OpenAlgo was not signalled or restarted. Latest log: `log/test/options-previous-quarter/resume-20261009-detached.log`.

**October 9 current checkpoint:** User restarted/logged into OpenAlgo and requests continued backtesting without affecting it. Leave the running app unchanged. First resume was blocked by daily login expiry; fresh-login resume is now successfully downloading. Log: `log/test/options-previous-quarter/resume-20261009-authenticated.log`. Historical shutdown and quota-stop notes below do not describe the current run. Annual download remains stopped.

**October 8 batch stopped at the configured daily reserve (shared count 3800).** 123 option histories plus the index file are cached; 6,838 option ranges remain. Collector exited normally with pending-report status (code 2). Resume after quota reset with a valid FYERS login. No final HTML has been generated.

Latest user instruction: stop OpenAlgo and backtest the three months before
July 8, 2026. Period chosen: **April 8–July 7, 2026 inclusive**.

OpenAlgo is confirmed stopped (it had already shut down at 16:33). Ports 5000/8765
are free, no strategy processes remain, and the 28 saved schedules are unchanged.
Do not restart the app for this research. The one-year download remains stopped
at the user's explicit request; do not restart that job.

The separate quarter run is authorized and underway. Its catalogue and complete
61-session index history were reused from local files; 6,961 option ranges require
collection under the confirmed FYERS Standard limits. Current progress lives in
`backtesting/nifty_options/2026-04-08_2026-07-07/download_status.json`.

Expected standalone result: **`backtesting/options_3months_2026-07-07.html`**.
**Not generated yet.** Replay and annual-style ledger/browser checks must finish
before publication; do not present partial data as completed results. Preserve
the completed July–October report unchanged.

[Canonical methodology, metrics, app state and resume instructions](../../backtesting/nifty_options/2026-04-08_2026-07-07/README.md).
Use `.development/options-previous-quarter/run.py`, not the stopped annual runner.
Collector uses the shared quota with 1,000-request reserve and does not schedule
automatic future runs. Most October 8 quota was already consumed by the stopped
annual task; additional daily quota windows will be needed.
