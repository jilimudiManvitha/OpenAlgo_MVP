# Agent handoff

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

Phase 0 (decisions and plan) is complete. **Implementation has not started** — no
investment files exist yet. Four questions in section 12 of that plan still need the
user's answer, the first being whether paper trading wires into the existing
`database/sandbox_db.py` engine. Do not begin Phase 3 before Phase 2's numbers reconcile
against the user's own figures.

Also read `context.md` for historical work/remote configuration and `docs/INDEX.md`
for documentation navigation. Historical task numbers in `context.md` are not the
task numbers in the new six-task plan. Preserve unrelated local changes.
Update the canonical plan when work progresses so a new agent can resume.
