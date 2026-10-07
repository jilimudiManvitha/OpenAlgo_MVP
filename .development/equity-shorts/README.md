# Isolated short equity work

**Historical development snapshot:** Integrated production source is now in `strategies/short_equity/`. The evening release installed 28 schedules with 15:15 equity exits. Staged-only statements below describe the earlier isolation checkpoint.

Eight short variants are built and their schedules are prepared, **not active**.
Current production remains at 20 schedules; the staged combined preview has 28.

- Rules: [short_equity/README.md](short_equity/README.md)
- Runtime/order handling: `short_equity/runtime.py`, `short_equity/sandbox_execution.py`
- Eight separate scripts: `launchers/`
- Offline add-only configuration builder: `short_equity/schedule.py`
- Local schedule previews: `schedules/` (regenerate after production stops)
- Canonical handoff: [evening integration plan](../../docs/plans/2026-10-07-short-equity-strategies.md)

From the project root, refresh only the isolated schedule files:

```sh
PYTHONPATH=.development/equity-shorts .venv/bin/python -m short_equity.schedule --project-root . --output-dir .development/equity-shorts/schedules
```

This does not import the scheduler, start jobs or modify installed schedules.
The combined preview contains the existing runtime status at the instant it was
read; **never copy an old preview over production after the user stops the app**.

Verification (uses the repository test isolation):

```sh
.venv/bin/python -m pytest test/test_short_equity_strategies.py test/test_top_gain_volumes.py test/test_four_sandbox_strategies.py test/test_eight_sandbox_strategies.py test/test_python_strategy_config_isolation.py -q
.venv/bin/ruff check .development/equity-shorts/short_equity .development/equity-shorts/launchers test/test_short_equity_strategies.py
```
