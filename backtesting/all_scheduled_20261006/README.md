# All scheduled strategies — 6 October 2026

Open **index.html** for the complete offline report: all 20 strategies, two intraminute paths, strategy charts, trade ledgers, CSV downloads, log evidence and Portfolio status.

## Results

Independent scenarios; do not add these as one portfolio. Options include open-position MTM. Stock scanner membership uses the final ranked basket retrospectively, so selection bias applies. Fees, margin and slippage are modeled, not actual broker bills.

| Strategy | OLHC net / MTM ₹ | OHLC net / MTM ₹ | Open simulated legs |
|---|---:|---:|---:|
| nifty500_fixed | 9,909.03 | 9,651.19 | 0 |
| weekday_fixed | 761.50 | 585.12 | 0 |
| nifty500_trailing | 2,607.88 | 1,635.77 | 0 |
| weekday_trailing | -260.27 | -644.94 | 0 |
| nifty500_fixed_5m | 8,721.43 | 8,622.33 | 0 |
| weekday_fixed_5m | 1,260.32 | 1,274.18 | 0 |
| nifty500_trailing_5m | 3,738.34 | 3,602.09 | 0 |
| weekday_trailing_5m | -419.60 | -412.43 | 0 |
| iron_condor_intraday_current_week | -21,024.41 | -21,024.42 | 0 |
| iron_condor_intraday_next_week | 6,706.02 | 6,706.02 | 0 |
| iron_condor_positional_current_week | 0.00 | 0.00 | 0 |
| iron_condor_positional_next_week | 4,383.52 | 4,383.52 | 4 |
| delta_intraday_current_week | 2,250.24 | 2,250.24 | 0 |
| delta_intraday_next_week | 5,208.91 | 5,208.91 | 0 |
| delta_positional_current_week | 0.00 | 0.00 | 0 |
| delta_positional_next_week | 2,507.39 | 2,507.39 | 2 |
| premium_intraday_current_week | 5,957.07 | 5,957.07 | 0 |
| premium_intraday_next_week | 2,965.49 | 2,965.49 | 0 |
| premium_positional_current_week | 0.00 | 0.00 | 0 |
| premium_positional_next_week | 1,867.50 | 1,867.50 | 1 |

14 positive, 3 negative and 3 no-entry outcomes in each path. The three current-week positional profiles found no contract in their requested premium band at 09:30. These are skipped entries, not evidence of a profitable/flat live strategy.

## Data and checks

- 92 unique stock histories: 77 final scanner symbols and 23 Tuesday watchlist symbols, with overlap. All stock symbol replays eligible.
- All 960 current/next option contracts requested; 366 returned candles and 594 returned no candles. No bars or fills synthesized for empty contracts. NIFTY index history ends at 15:29; option marks extend to 15:39 and equity points label minute-end 15:40.
- Stock ledgers independently reconciled; all 24 option scenarios pass VectorBT closed-leg reconciliation. Next-week positional runs begin flat today and can end with open legs. This is not an overnight carry reconstruction.
- `inputs/` contains source snapshots, raw option responses, normalized archives and source hashes. `options/` and `stocks.json` contain the detailed replay outputs.
- `build_report.py` is the canonical strict builder: missing required results fail instead of silently displaying zero. The separately supplied `build_report_fixed.py` is preserved but was not used for final output.

## Today’s operational findings

- All 12 option runners missed entry while subscriptions remained incomplete. Shared-pool capacity errors explicitly report 3 × 1,000 slots. The scanner previously streamed up to all 2,679 equities alongside the 960-option universe and NIFTY.
- Network/DNS, handshake, HSM and ping/pong failures also occurred. The option fix below addresses capacity and connection bursts; it cannot guarantee network availability.
- Six stock reports remain `running` with 62 trades marked open. Later closing fills exist; the captured Sandbox snapshot has zero remaining nonzero positions and 57 AUTO_SQUARE_OFF orders. Saved P&L is incomplete and was not rewritten. A three-second scheduler termination grace is a possible contributor, not a proven cause.
- An MCX square-off request lacked quantity; subscription-release mismatch errors also remain for separate investigation.
- The retained JSON error log contains only 1,000 entries (15:15:17–17:27:14). Morning evidence is from the 20 dated strategy logs. Counts are log entries, not unique incidents.

## Scheduled option repair

- FYERS scanner streaming capped at 1,000; existing full-universe REST refresh remains. Other brokers and lower configured limits retain their behavior.
- Flat option profiles request the complete required expiry (481 instruments including NIFTY for this catalogue), not both weeks. Active and pending cycle expiries retain their full chains for adjustment/recovery. Held risk can still be managed when a future expiry catalogue is unavailable.
- Independent startup handshakes staggered by 0–11 seconds; carried positions connect immediately. Reconnect attempts are paced. Subscription acknowledgements/retry, fresh-price checks, 09:30–09:31 entry window and risk rules are retained.
- Real pool allocator tested offline with scanner 1,000 + disjoint scheduled equities 500 + options 960 + NIFTY = 2,461 slots, leaving 539 for other tools. This budget is for the observed catalogue; arbitrary additional subscriptions can still exhaust the pool.
- **139 focused tests pass.** In-memory fault injection separately disables the scanner cap, chain filtering and handshake delay; each actual regression test fails at its intended assertion. Scoped Ruff passes.
- Resource review: no new sockets, threads, sessions or global caches in this change. Existing client cleanup stays in `finally`; contract/ack collections remain catalogue-bounded. Included tests exercise 200 real report success/error cycles with stable descriptor counts. No live market-hour soak performed.

## Activation and Portfolio

The user must restart OpenAlgo at a suitable time for the scanner cap to load. Next scheduled strategy processes load the runner changes automatically, but the running scanner retains its old budget until restarted. No process was started/signalled, no production DB/report was written, no schedule changed and no production frontend built. All 20 schedules and 520 protected files matched their captured hashes.

Portfolio Phases 3–5 are implemented and verified locally; no agreed feature remains to build. Deployment and live environment acceptance remain under the existing “combine and launch” gate. See `docs/plans/2026-10-06-portfolio-completion.md`.

## Reproduce offline

```sh
.venv/bin/python backtesting/all_scheduled_20261006/build_report.py
node backtesting/all_scheduled_20261006/verify_report.cjs
```

Historical replay stages `stocks` and `options` in `run.py` use the downloaded inputs and isolated calendar DB under `log/test/day-review-20261006/`. `fetch` is a separate read-only broker network operation. No backtest is published to the application Reports database.

October 7: the combined local application is now built by user request; see `docs/plans/2026-10-07-local-release-readiness.md`. Downloaded stock/option/raw candle caches remain local and are excluded from Git. The HTML and exported results are standalone; regenerating/replaying requires those retained input caches.
