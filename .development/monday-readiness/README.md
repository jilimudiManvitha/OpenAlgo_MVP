# October 5 Monday readiness verification

See the [readiness report](../../docs/plans/2026-10-04-monday-readiness.md) and [complete handoff](../../docs/plans/2026-10-04-readiness-portfolio-handoff.md).

`check_saved.py` is read-only against operational tables and saved schedules. It writes only its local `saved_checks.json` evidence. It checks twenty launchers/schedules, October 5 start times, API-key ownership without printing the key, Nifty500 membership, the deliberately empty Monday watchlist, database integrity and sandbox funds/reset settings.

Its Monday date is deliberately fixed to **2026-10-05**. Update intentionally for a different session. It neither launches strategies nor submits orders; passing it does not prove market-hour fills.
