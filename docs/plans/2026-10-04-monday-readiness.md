# Monday readiness — October 4, 2026

Premarket checks passed; market-hour quotes, execution and fills remain unverified.
OpenAlgo is running; leave it running. After portfolio deployment the latest verified PID is
**15965**, started at 21:35 IST, with all twenty schedules restored. See the
[final handoff](2026-10-04-readiness-portfolio-handoff.md) for current state and later verification.
PID 11869 at 17:54 IST was the earlier readiness instance and has been stopped.

- Backend: 5,932 passed, 28 skipped, 1 expected failure, 12 warnings. Manual broker/order/Telegram diagnostic scripts are excluded from automatic collection. Optional OpenScript native engine and eventlet are absent on this Mac; their skipped checks are not passes.
- Frontend: 194 files / 2,956 tests pass; TypeScript + production build pass. Lint exits zero with four existing warnings and two infos.
- Scheduled strategy families: 114 focused tests pass. All 20 launchers parse and all 20 enabled schedules next start Monday October 5 at 09:15 IST. Eight originals remain 09:15–15:00 NSE; twelve NIFTY schedules remain 09:15–15:40 NFO (entry 09:30, intraday exit 15:20).
- Restart log confirms **Restored 20 scheduled strategies**. HTTP 200 and listeners 5000/8765 verified. Quote proxy authenticates and accepts a read-only subscription; 960 NIFTY contracts, Oct 6/13 expiries; sample broker basket margin ₹294,105.07.
- Four operational SQLite databases pass quick_check. Nifty500 universe has 500 symbols. User explicitly left weekday lists empty and will populate them before 09:00. Empty lists cause those four strategies to have no candidate stocks.
- Sandbox capital ₹5 crore, available ₹50,000,265.28, margin zero, realized ₹265.28; reset Never. No orders submitted by verification.

## Fixes and isolation incident

Fixed Node native storage shadowing jsdom in frontend tests, stale navigation expectations, macOS symlink-safe Historify export paths, missing OpenScript route registration, repeated shutdown signals, and missing Polars requirements entries. Updated stale/date-dependent tests to their actual contracts and made optional-engine skips explicit.

A scheduler test called real save_configs and replaced the operator's schedule file with a fixture. Restart verification caught it (only one schedule restored). Stopped the verification instance, restored the 20-entry backup, reapplied approved NIFTY schedule values, and compared the eight original definitions. Sandbox funds remained unchanged and no orders were recorded October 4. The scheduler now accepts an explicit data directory; pytest forces a per-process temporary directory for scripts/configs and logs. A real-save regression passes; pointing it at production makes it fail before any write. The entire suite was then rerun with the production configuration byte-for-byte unchanged:
`fdb25622f3a22a6e9a88aff0472aa224065c48d33e7511efbb40405a7586cc76`.
Final restart restored all 20, with read-only live checks passing.

## Evidence

- `log/test/readiness-backend.log` and `.xml` — complete automated backend suite.
- `log/test/frontend-readiness.log`, `frontend-build-readiness.log`, `frontend-lint-readiness.log`.
- `log/test/readiness-strategies.log` — 114 strategy cases.
- `log/test/readiness-isolation.log` — 41 scheduler/isolation cases.
- `log/monday-readiness-startup.log` — final application startup.
- `.development/monday-readiness/check_saved.py` and `saved_checks.json` — repeatable read-only persisted-state verification.
- `backtest/nifty_options/verification/live_checks.json` — read-only broker/proxy checks.

Before Monday: populate weekday list by 09:00 as planned; keep the Mac awake and OpenAlgo running, with a valid FYERS session before 09:15. Sunday checks cannot guarantee Monday broker availability or order fills. No live trading mode was enabled. Other frozen roadmap tasks remain untouched.
