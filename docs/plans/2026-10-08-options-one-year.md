# Annual options backtest handoff — October 8, 2026

**Stopped at user request, October 8 at 22:59 IST.** Collector confirmed exited; 6,733 histories cached and 19,351 remaining. Annual replay/report incomplete. Do not resume without a new user request. Earlier running-status notes below are historical.

User superseded the completed three-month request with a one-year replay of all
options strategies, then explicitly required trade count, wins/losses and win rate.
Latest filename instruction: **`backtesting/options_1yearBacktest.html`**.

**Not complete.** Data collection is resumable and running in a separate read-only
process. The configured Standard FYERS data quota prevents collecting all missing
contract histories in one day. Do not fabricate, shorten the period, or publish
the three-month numbers as one-year results.

See the [annual archive README](../../backtesting/nifty_options/2025-10-09_2026-10-08/README.md)
for methodology, sources, output semantics and resume commands. Machine checkpoint:
`backtesting/nifty_options/2025-10-09_2026-10-08/download_status.json`.

## Implementation / verification

- Catalogue discovered: 26,080 option ranges; four index chunks downloaded.
- Index calendar verified for 247 sessions. Research-only holiday corrections
  cover 2025 Q4, Muhurat hours and the 2026 Budget Sunday. The production DB remains
  unchanged and strategy entry rules remain unchanged.
- First collection saved 473 new histories, then failed due to OS networking/DNS.
  Resumed via `.development/options-year/collect.py`, cached files validated/reused.
- Uses actual FYERS listed symbols and observed candles. Conflicting cached prices
  abort. Empty broker `no_data` remains distinguishable from an absent file.
- Reserves 1,000 internal daily requests for the app; bounded pacing/retries,
  exclusive process lock, checkpoint on stop/error, shared persistent quota retained.
- Authentication copied read-only into private mode-600 DB; each resume refreshes
  the snapshot. Files/SQLite/lock use context managers; shared HTTP client closes
  in `finally`. Source index bounded by manifests; candle rows held one range at
  a time. Static resource review completed. Across another 110 downloaded ranges,
  collector descriptors stayed at 9 and RSS went from 165.8 to 140.3 MiB; this is
  a bounded sample, not a full leak soak test.
- 127 focused strategy/calendar/hedge/brokerage tests passed. Two calendar regressions
  reproduced before the fix (375 fictitious daytime Muhurat bars and date mismatch).
- Four collector tests passed: reserve and request caps prevent broker requests,
  cached resume avoids repeat requests, expired-contract routing after a multi-day
  resume, 100-day chunking, conflicting prices rejected. The stale-expiry routing
  case failed before its fix and passed afterward.
  Disabling the reserve guard in memory made the corresponding regression fail.
- Report template made period-independent, added explicit winning/losing/breakeven
  detail cards and pooled breakeven counts. CSV names use actual start/end dates.
- Offline browser preview using the old report's explicitly unchanged three-month
  data passed 24 strategy/path scenarios, six charts, totals, filters, sorting,
  CSV filename/content, desktop/mobile overflow, zero JS errors/network requests.
  This validates the template, **not annual performance**.
- Annual publication runner checks full data status, runs replay/ledger verification,
  checks 24 variants/dates and browser verification, then atomically publishes the
  exact requested HTML filename. No annual HTML exists before those gates pass.
  `run.py --report-only` was exercised against the incomplete archive: exit code 2,
  report pending, no final HTML created. The previous three-month HTML retains
  SHA256 `24a27c3f2faf85933c59743d407822bdd0a55a8cc7c9e2d9d3e8c879bcda0dd2`.

## Resume boundary

The app was already running at user request. This work does not signal it, place
orders, alter schedules, rebuild frontend assets or write app reports. The previous
Git push was completed before this annual task; these new changes are not pushed.
`task.txt` has an unrelated local user edit; preserve it.

After enough quota windows and a valid login:

```bash
.venv/bin/python .development/options-year/run.py
```

Check actual process state rather than using saved PIDs as kill targets. The
collector stops on daily reserve/network failures; it does not silently schedule
future runs or change the account's data plan. The user confirmed **Standard / No
Prime**. Keep Standard data limits; do not ask this again or change to Prime limits.
