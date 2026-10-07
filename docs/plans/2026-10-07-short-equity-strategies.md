# Eight short equity strategies — isolated implementation and evening handoff

**Evening integration:** Combined into the normal local build with user authorization. [Current release and restart checklist](2026-10-07-evening-combine.md) supersedes the staged-only status below.

## Authorization and current state

October 7 user request: mirror the non-options equity long strategies into
shorts, including signal/entry OHLC below VWAP and lower-Bollinger breakdown;
build and schedule in isolation, then combine locally in the evening after
15:30 without affecting the running OpenAlgo.

**Implementation and isolated schedule preparation complete. Not deployed.**
Original eight equity longs and twelve options schedules remain installed:
20 active configurations, with eight additional shorts prepared in a separate
28-entry preview. No process was signaled, no app/strategy was started, no broker
request/order was made, and no production database or serving frontend was edited.
Other existing dirty/untracked work is preserved. No commit/push requested.

## Delivered

The separate package and eight launchers are under
[`.development/equity-shorts/`](../../.development/equity-shorts/README.md).
[Exact strategy rules](../../.development/equity-shorts/short_equity/README.md).

| Universe | Fixed 3R | Trail after 3R |
|---|---|---|
| Nifty500 scanner, 1m | `nifty500_short_fixed` | `nifty500_short_trailing` |
| Weekday watchlist, 1m | `weekday_short_fixed` | `weekday_short_trailing` |
| Nifty500 scanner, 5m | `nifty500_short_fixed_5m` | `nifty500_short_trailing_5m` |
| Weekday watchlist, 5m | `weekday_short_fixed_5m` | `weekday_short_trailing_5m` |

All new schedules: NSE, Monday–Friday, 09:15 start / 15:00 stop IST, ₹10,000
per trade, Sandbox-only MIS. The stock universe and watchlist storage are reused.
Negative scanner ranking mirrors positive ranking, including volume tie-breaks.

Short signal: completed red/no-upper-wick HA candle, low below lower BB, entire
HA OHLC below VWAP. Entry: immediately following forming red/no-upper-wick HA
candle, entire observed HA OHLC below VWAP, observed price below signal low and
forming lower BB. Intrabar entry matches the existing equity strategy timing.
Stop: 0.03% above signal HA high, rounded up. Target: 3R below confirmed entry,
rounded down. Trailing arms at 3R, then covers above forming middle BB with
original stop retained. SELL entry and BUY cover, short P&L sign and order-state
fields are handled independently from the long implementation.

The strict VWAP condition applies to **all eight** new variants per the user's
wording; it is stronger than the legacy fixed-long VWAP guard. Both runtimes
interpret OHLC as HA, consistent with the reference strategies. The existing
signal band-cross rule is mirrored; there is no additional close-only condition.

## Verification

- **109 focused backend tests passed**, including 39 new short tests and 70
  existing long/scheduler regressions. JUnit: `log/test/equity-shorts/results.xml`.
- All eight intrabar entries; 1m/5m candles; signal/entry full-OHLC VWAP;
  lower-BB gate; stale/gapped/rewound data; negative selection before ranking;
  stop/target rounding; fixed/trailing/clock exits; signed P&L/report persistence.
- Real Sandbox `OrderManager`/`ExecutionEngine` round trips in isolated test
  DBs: SELL creates a negative position, BUY returns it to zero, bid/ask fills
  and positive short P&L verified. Both immediate and delayed status paths pass.
- Pending entry/exit and unknown dispatch do not duplicate; cutoff cancels an
  unfilled sell; clock-based cover uses a fresh cached quote. Mutating either
  VWAP guard or the SELL entry-order mapping makes its regression fail.
- Prepared schedules merge additively and idempotently, reject conflicts,
  preserve all 20 existing entries, and cannot write to production directories.
  Weekday Cron timing checked across a weekend. NSE metadata retains the
  existing scheduler's holiday behavior; no live scheduler was exercised.
- Read-only hash comparison: **575 protected files unchanged**, including all
  existing equity/options source, saved schedules and `frontend/dist` assets.
  Installed schedule SHA-256 at verification:
  `0bf5128a5974f20a7410183bbc8518a02b5196adf786418624a016a4e95710c3`.
  The running app may legitimately update this file later; compare semantics
  against the then-current file at integration.
- Ruff passes for staged Python source/launchers/tests. Scheduler test teardown
  emits an existing Colorama closed-capture-stream logging error after the pass
  summary; process exit is zero and the protected schedule/source checks pass.

Resource audit: short order calls retain `finally` session cleanup and the shared
owner lock's context-managed handle, including pending/error/retry paths. The
copied feed/history worker teardown retains disconnect, callback removal,
executor shutdown, report disposal and shared HTTP cleanup. New runtime report
store creation is inside its managed execution lifetime. Buffers remain bounded
(20 closes, 390 candles, 20,000 queued ticks, 10,000 latency samples, eight pending
warmups, one worker); symbol maps are limited by the loaded universe. Static
review plus **120 repeated short entry/cover cycles** stayed within the two-FD
tolerance. This is not a full-session RSS/market-feed soak.

No new historical backtest was requested or run. Live market-hour operation,
broker/feed availability and an actual scheduler launch remain unverified until
the user's later activation. Existing Sandbox netting is per owner/symbol/product,
so concurrent long/short strategy positions can offset at account level even
though reports retain independent fills. Chart data includes `bb_lower`; the
existing report UI's upper/middle/VWAP plot is unchanged in this task.

## Evening integration — deferred, not performed

1. Resume when the user is ready after **15:30 IST**. The user stops OpenAlgo;
   verify both 5000/8765 and all scheduled strategy workers have exited. Never
   signal the user's processes. Options schedules run through 15:40, so do not
   infer they have stopped merely because equity trading has ended.
2. Review `source-baseline.json` against the current original runtime/execution
   source and reconcile any later fixes into the staged package. Preserve the
   Portfolio/Reports work already pending in this checkout.
3. Copy the new `short_equity/` directory to `strategies/short_equity/` and the
   eight `launchers/*.py` files into `strategies/`. Refuse to overwrite unexpected
   existing files. Do not replace `top_gain_volumes` or any old wrapper.
4. Regenerate the preview using the README command against the **current saved
   configuration after shutdown**. Back up that current file. Verify the manifest
   source hash still matches before an atomic installation of the fresh combined
   configuration. Preserve every old entry exactly and verify 28 entries with
   eight `Short10K_` IDs; do not run the old eight/twelve schedule installers.
   `merge_configurations()` is the tested add-only operation.
5. Update any readiness tooling that assumes exactly 20 schedules: the old
   `.development/monday-readiness/check_saved.py` explicitly asserts 20. Its old
   check must not be mistaken for schedule loss after this intentional expansion.
6. Re-run the focused checks, verify all configured source paths exist, and
   include any separately authorized Portfolio/Reports changes in the user's
   combined release. These new strategy scripts alone require no frontend build.
7. The user starts production. Check restoration of all 28 schedules, the eight
   NSE start/stop jobs and holiday gating. Do not start short strategies late in
   the current session or submit verification orders. No watchlists are seeded.

The isolated schedule files have already been generated, but are deliberately
ignored by Git because they contain a point-in-time copy of runtime status.
They are not the running app's scheduler configuration.
