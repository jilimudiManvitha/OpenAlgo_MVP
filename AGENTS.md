# Agent handoff

**October 7 evening checkpoint:** User authorized combining all isolated features and pushing Git after stopping OpenAlgo. Eight shorts are integrated; **28 schedules** are now saved (16 equity 09:15–15:15, 12 options unchanged). Read [evening release handoff](docs/plans/2026-10-07-evening-combine.md) first. Only the user starts production. Schedule installation for this release was explicitly authorized; older 20-schedule/install holds below are historical. Future tests must retain isolation. Read-only schedule check: `.venv/bin/python .development/oct7-combine/schedules.py`.

**October 7 local release checkpoint:** The user explicitly requested the scheduled strategies and completed Portfolio combined for local use, then pushed to Git. This authorizes the normal frontend build and reviewed commit/push, superseding the older deployment hold below. The normal build and isolated browser checks are complete; [release readiness and morning checklist](docs/plans/2026-10-07-local-release-readiness.md). Only the user starts production. All twenty schedules and production data are preserved. Wed/Thu watchlists are currently empty; do not populate without supplied symbols. Older “not deployed / no push requested” notes are historical.

**October 6 portfolio checkpoint:** The user resumed with “complete that portifolio section remaing” and “limit reseted continue.” Remaining phases are now implemented and verified in lane D; [completion handoff](docs/plans/2026-10-06-portfolio-completion.md). They are **not deployed**. The standing order below still applies, and deployment still requires “combine and launch.” Older “not started / stopped” implementation notes below are historical.

## STOP AND READ FIRST — parallel-development standing order (October 4, evening)

The user runs OpenAlgo for real trading **while** the Investment Portfolio feature is
developed in this same repository. **Never affect the running OpenAlgo.** Section 0 of
[the readiness/portfolio handoff](docs/plans/2026-10-04-readiness-portfolio-handoff.md)
is the authoritative rule set; read it before any work. The short form:

- **Do not signal any OpenAlgo process.** No `kill`, `pkill`, `killall`, no Ctrl-C into
  someone else's terminal. PIDs recorded in documents are stale, never targets. Only
  stop processes you started yourself.
- **Do not start the production app** (`uv run --no-sync app.py` or any `caffeinate`/
  `uv` wrapper). Port **5000/8765 belongs to the user**. Development uses the isolated
  fixture server on **5011** (`.development/investment/browser_server.py`).
- **Do not write to production databases** — no `db/*.db`, `db/scanner*`,
  `db/nifty_options/*`. Development databases live under `log/test/`.
- **Do not run pytest without its isolation.** `test/conftest.py` forces a temporary
  `PYTHON_STRATEGY_DATA_DIR`; never override it toward `strategies/`, never run the
  schedule installer. Verify schedules read-only with
  `.venv/bin/python .development/monday-readiness/check_saved.py`. Fewer than 20
  schedules means something overwrote them: restore from
  `db/nifty_options/schedules-before-*.json` and tell the user.
- **Do not run destructive git commands** (`reset`, `checkout --`, `restore`, `clean`,
  `stash`) or blind `git add -A`: 262 local `frontend/dist` paths are half-staged Vite
  churn. Preserve all local changes.
- **Do not rebuild `frontend/dist`** while the user's instance serves it. Vitest and
  lint are safe; a Vite `build` waits for a user-approved stop.
- **No broker orders from any lane.** Read-only quotes only.
- **Do not re-ask answered questions:** ATHER baseline accepted, existing sandbox
  integration chosen, FIFO alongside weighted average, categorized paper GTT examples
  only, empty weekday watchlists, twenty schedules preserved.

The user restarts the production instance themselves. Portfolio code reaches
production only when the user says "combine and launch" (handoff §0.4).

## Other handoffs

For the October 3 NIFTY options request, read
`docs/plans/2026-10-03-nifty-options-strategies.md`. It is separate authorized
work. Latest user instruction: backtest **only the last three months**, replacing
five years. Save all new/future backtest output under `backtest/`; do not publish
backtests into the application Reports database/page. Preserve existing reports.

Before resuming the user's six tasks from 2026-09-11, read
[`docs/plans/2026-09-11-six-task-roadmap.md`](docs/plans/2026-09-11-six-task-roadmap.md).
It is the canonical task plan, status checklist, repository boundary and restart memory.

The user requested planning first. The planning session changed documentation only.
Do not assume the six planned features or backtests have been implemented.
The 2026-09-12 request authorized Task 2 scanner integration into this project.
Task 2 is now integrated locally; consult the current checkpoint for verification
and pending live operational checks. Task 1 and Tasks 3-5 are frozen. Take the
user's strategy update before resuming Task 1. The original Crypto tree and code
outside Task 2 remain protected by the earlier boundary instruction.

**2026-10-02: Task 6 is unfrozen.** The user requested a broader Investment Portfolio
section — ten asset classes with full read/write, a transaction ledger, nine reports,
portfolio scoring and charts. Read
[`docs/plans/2026-10-02-portfolio-section-plan.md`](docs/plans/2026-10-02-portfolio-section-plan.md)
before starting. It supersedes the Task 6 scope in the six-task roadmap and records the
locked decisions (weighted-average cost basis, manual price entry plus CSV import for
non-stock assets, `investment` namespace to avoid the portfolio backtester's names, and
Phase 1 = ledger + Dashboard + Stocks before widening).

**October 4 current checkpoint:** initial investment ledger + Dashboard/Stocks are
implemented and deployed. Read the [complete readiness/portfolio handoff](docs/plans/2026-10-04-readiness-portfolio-handoff.md)
before resuming. User confirmed existing sandbox integration/preserve holdings,
FIFO alongside weighted average, and categorized paper GTT orders (examples only).
FYERS returned zero holdings; user explicitly **accepted the verified ATHER baseline**
and authorized continuation. The old three-stock reconciliation gate is resolved.
Phase 3, the full report suite and paper GTT integration have not started.

**Latest instruction: parallel development, then stop.** Work is stopped. The user then
asked for **all OpenAlgo processes to be stopped** so they can restart from a clean state:
the `caffeinate`/`uv` wrapper (15964/15963), the app server (15965) and the MCP helpers
(82809, 88903) are terminated and ports 5000/8765 are free. **The user restarts it.** All
Portfolio Phase 3–5 development continues in lane D only, per the standing order above,
without touching the production instance, its databases, its schedules or its frontend
build. Do not restart work until requested; do not ask the answered
acceptance/sandbox/FIFO questions again. Scheduler tests now use an isolated data
directory after a caught-and-repaired configuration overwrite; preserve that isolation
fix. See handoff for evidence and frontend generated-asset staging cautions. No commit
or push was requested.
Scheduler tests now use an isolated data directory after a caught-and-repaired
configuration overwrite; preserve that isolation fix. See handoff for evidence and
frontend generated-asset staging cautions. No commit or push was requested.

Also read `context.md` for historical work/remote configuration and `docs/INDEX.md`
for documentation navigation. Historical task numbers in `context.md` are not the
task numbers in the new six-task plan. Preserve unrelated local changes.
Update the canonical plan when work progresses so a new agent can resume.
