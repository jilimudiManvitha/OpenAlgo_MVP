# Investment verification helpers

Read the [complete handoff](../../docs/plans/2026-10-04-readiness-portfolio-handoff.md) before running anything.

- `browser_server.py`: isolated Flask/CSRF/SQLite server on **5011**, resets only `log/test/investment-browser.db` at startup. Never use the production DB URL here.
- `verify_ui.cjs`: headless Chrome against that fixture. Create/buy/value/sell/error/history/reload/chart/desktop/mobile checks; artifacts in `artifacts/`. Restart the fixture server before rerunning, because this workflow creates records.
- `verify_regression.py`: proves the real ownership test fails when the predicate is removed in memory. The nested pytest failure is expected; the script succeeds only when detected.
- `read_fyers.py`: read-only FYERS holdings fetch using existing OpenAlgo authentication. No order/import. Private JSON output under `db/` is ignored and must not be committed.

The test server was stopped at handoff. The production app on 5000/8765 was left running.

Release verification can serve the normal built frontend with `browser_server.py --production-bundle`; database isolation and port 5011 remain unchanged.
