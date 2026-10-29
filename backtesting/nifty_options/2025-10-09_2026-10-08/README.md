# One-year NIFTY options backtest — collection in progress

**Stopped at user request — October 8, 22:59 IST.** 6,733 histories cached; 19,351 remain. No annual results generated. Do not run the resume commands below unless the user requests resumption.

Requested output: **`backtesting/options_1yearBacktest.html`**.
The final report has **not** been published: the annual option archive is incomplete.
Do not interpret the previous three-month report, or the report-template test fixture,
as annual results.

## Scope and metrics

- October 9, 2025–October 8, 2026, inclusive; October 8 session was closed when requested.
- All 12 current NIFTY option strategies with 200-point same-expiry wings.
- Both OLHC and OHLC minute-path simulations, shown separately, never added together.
- ₹20 lakh separately allocated per strategy (₹2.4 crore arithmetic combined allocation).
- Overall and per strategy: gross/net P&L, estimated charge components, winning profit,
  losing loss, total completed trades, wins, losses, breakeven trades, win rate,
  open trades/legs, modeled capital used, drawdown, monthly performance and trade details.
- A trade is a completed strategy basket cycle, including its adjustments. Wins/losses
  use net P&L after estimated fees. Win rate = wins / all completed cycles × 100;
  breakeven cycles stay in the denominator and open cycles are excluded. Zero completed
  trades produces N/A. Individual option-contract legs have separate counts.
- Standard FYERS retail estimated charges use each execution's date. Near-week NIFTY
  contracts expiring through December 30, 2025 use 75 units/lot; later expiries use 65.
  Margin and Greeks are models, not historical SPAN or broker Greeks. No synthetic
  option candles or forced year-end liquidation.

## Current evidence

- Listed contract catalogue: **26,080** contract/range entries, obtained from FYERS.
- Four index history chunks are downloaded. The index dates reconcile to **247 sessions**.
- Initial validated cache: 5,661 entries including the oldest-expiry probe.
- First network batch downloaded 473 histories, then stopped on network/DNS errors.
- Collection resumed from those files. `download_status.json` is the current checkpoint;
  its `completed`/`remaining` counts include the four index chunks.
- The user confirmed **Standard / No Prime**. The collector shares the application's real
  persistent budget, leaves 1,000 requests of the internal 4,800/day budget reserved,
  and paces requests below 30/minute. It stops at that reserve, at a broker cooldown,
  or on an error. It does not reset quota, change subscription, or auto-start tomorrow.
- Full-year replay, ledger verification, annual browser verification and publication
  remain pending. No annual profit, trade counts or win rates are claimed yet.

## Calendar correction

The legacy 2025 database seed incorrectly closes November 14 and has incorrect
October/November holiday records. Research-only corrections in
`strategies/nifty_options/replay_calendar.py` close October 22 and November 5, open
November 14, and include October 21 Muhurat (13:45–14:45) and February 1, 2026 Budget
Sunday (09:15–15:30). The production holiday database is untouched.

The original weekday 09:30 initial-entry rule remains unchanged. It does not gain
new initial entries during Muhurat or on Budget Sunday; carried positions are
monitored/marked during available exchange sessions. This is a strategy simulation,
not a reproduction of the local scheduler's actual historical uptime.

Sources: [2025 holidays](https://nsearchives.nseindia.com/content/circulars/FAOP65588.pdf),
[Muhurat timings](https://nsearchives.nseindia.com/content/circulars/FAOP70320.pdf),
[Budget Sunday](https://nsearchives.nseindia.com/content/circulars/FAOP72352.pdf),
[2026 holidays](https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf),
[NIFTY lot revision](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf),
[FYERS data limits](https://support.fyers.in/portal/en/kb/articles/what-are-the-fyers-api-rate-limits-for-standard-and-prime-plans).

## Resume and publish

Run from the repository root with a valid FYERS login and network connectivity:

```bash
.venv/bin/python .development/options-year/run.py
```

This takes a private authentication database snapshot, resumes validated cached
data, then runs both replay paths only after the archive is complete. The replay
reconciles cash flows and fees, verifies ledgers and data/source hashes, and runs
offline browser checks. Only after all checks pass does it publish
`backtesting/options_1yearBacktest.html`. Incomplete collection returns exit code 2
without publishing a report. The collector lock prevents concurrent collectors.

For collection alone:

```bash
.venv/bin/python .development/options-year/collect.py
```

For already downloaded data:

```bash
.venv/bin/python .development/options-year/run.py --report-only
```

The standalone browser check may need local OS permission to launch headless Chrome.
Private DB snapshots and logs remain under ignored `log/test/options-year/`.
No production orders, schedule changes, app restarts, or application Reports writes.
The previously completed three-month report remains unchanged.
