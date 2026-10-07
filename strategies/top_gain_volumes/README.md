# Eight ₹10,000 Sandbox strategies

**October 7 update:** All eight equity profiles now square off at 15:15 IST. See the [combined release](../../docs/plans/2026-10-07-evening-combine.md); older run examples below are historical.

Updated September 30 evening, 2026. The user authorized fixing the September 30
failures and adding four 5-minute HA variants to the four existing 1-minute
variants. All eight use **09:15–15:00 IST, Monday–Friday**, subject to the NSE
exchange calendar. Keep OpenAlgo and its Quote proxy running, FYERS logged in,
and the Mac awake. These are local schedules, not a hosted service.

Deployment verified at 19:55:49 IST: OpenAlgo startup restored all **8** schedules,
FYERS order updates reconnected, and the Reports page returned HTTP 200. All eight
next starts are October 1 at 09:15 and stops at 15:00. The app runs under the
user's `caffeinate -i uv run --no-sync app.py` command (PID 88539).

Tomorrow is Thursday, October 1. `Thu` is currently empty; the user confirmed
that they will populate it before 09:15. Empty watchlists wait without trading.

### September 30 incident and fixes

All four original processes stopped at 09:16–09:24 because Sandbox accepted an
order but deferred its immediate fill after an inconsistent quote (LTP outside
the reported daily range). Those orders later filled; strategy reports remain
interrupted. Inspection after the session found no nonzero Sandbox positions or
pending orders. Historical reports/logs are preserved, not rewritten as success.

The runtime now skips incoherent entry quotes without consuming the signal,
retains accepted pending orders, polls the same order IDs, and manages confirmed
fills. It never blindly redispatches an unknown outcome. Pending/uncertain orders
pause new entries while other positions remain managed. At cutoff it cancels
known pending entries and reconciles the resulting status; fresh cached quotes
allow clock-driven square-off without requiring another tick. Missing quotes or
unknown outcomes remain explicitly unresolved, never fabricated fills.

Warmup uses one worker per strategy and a shared, process-locked history cache
with 1.25-second request pacing, a 60-second failure cooldown, session expiry,
and a 2,048-row bound. Completed history is reused; live-session history expires
after five seconds. Each request uses the existing broker HTTP client. All
strategies share 1-minute source data; seven prior calendar days seed indicators.
No API credentials are cached. Other application workloads may still cause
broker rate limits; this is not a guarantee of uninterrupted market data.

After feed gaps, invalid candle histories are rebuilt even for open positions.
Local proxy reconnects restore subscriptions. FYERS HSM retries continue with
capped, interruptible backoff instead of giving up after ten attempts. Order
updates reset their retry delay after a successful connection. Old sockets close
before replacement. Refreshed logins are picked up on subsequent warmups.

## Separate entry files

| Universe | Exit | Entry file |
|---|---|---|
| Nifty500 scanner | Fixed 3R | [Top_Gain_Volumes_Live_1L_stategy.py](../Top_Gain_Volumes_Live_1L_stategy.py) |
| Weekday watchlist | Fixed 3R | [Weekday_Watchlist_Fixed_3R_10K.py](../Weekday_Watchlist_Fixed_3R_10K.py) |
| Nifty500 scanner | Trail after 3R | [Nifty500_Scanner_Trail_3R_10K.py](../Nifty500_Scanner_Trail_3R_10K.py) |
| Weekday watchlist | Trail after 3R | [Weekday_Watchlist_Trail_3R_10K.py](../Weekday_Watchlist_Trail_3R_10K.py) |

The four new 5-minute wrappers are:

- [Nifty500 fixed 5m](../Nifty500_Scanner_Fixed_3R_10K_5m.py)
- [Nifty500 trailing 5m](../Nifty500_Scanner_Trail_3R_10K_5m.py)
- [Weekday fixed 5m](../Weekday_Watchlist_Fixed_3R_10K_5m.py)
- [Weekday trailing 5m](../Weekday_Watchlist_Trail_3R_10K_5m.py)

The legacy `1L` filename is preserved, but its capital is now **₹10,000**.
The wrappers use this shared package; transfer the project, not just one file.

## Rules and execution

The original four use 1-minute candles; the four `_5m` profiles use 5-minute
candles aligned 09:15–09:20, 09:20–09:25, etc. Real 1-minute OHLCV is aggregated
before Heikin Ashi, BB(20, 2 population standard deviations), and session VWAP.
Missing source minutes cannot become apparently complete 5-minute candles. The original breakout rules remain: a qualifying
completed HA signal is followed by a green/no-lower-wick forming entry candle
during the next candle of the selected timeframe, breaking above the signal high, forming upper BB and
VWAP. Entry does not wait for that candle's close.

The trailing variants additionally require **all HA OHLC prices of both signal
and forming entry above VWAP**. Forming-candle checks use only prices observed
so far, never a future final low. Stop is **0.03% below signal HA low**:
`signal_low * 0.9997`, rounded down to the instrument tick. Fixed
variants exit at 3R; trailing variants arm at 3R, then exit on the first observed
price below the forming BB middle band. The original stop remains; reaching 3R
does not partially close the trade or move its stop.

Sizing is whole shares with up to ₹10,000 entry notional, not ₹10,000 loss risk.
One position per symbol per strategy; fresh-signal reentry is allowed after exit.
No extra portfolio/trade-count cap is imposed; Sandbox funds and acceptance
still apply. A symbol can qualify in several strategies, increasing exposure.

Forward execution submits **actual OpenAlgo Sandbox orders only**, using the
authenticated owner and local Sandbox service. It never calls the live broker
order router or changes global analyzer mode. Actual Sandbox order IDs, complete
fills and dispatch latency samples are recorded. Forward fees are zero because
this integration does not book actual brokerage/taxes.

At 15:00 entries stop and positions are closed using fresh observed quotes.
Stale feed, overflow or incomplete warmup suppresses entries. Missing exit
quotes or uncertain order outcomes remain unresolved, not invented fills.
Existing same-day runs cannot be overwritten/restarted automatically: inspect
reports and Sandbox orders/positions and reconcile first.

An owner-level cross-process lock serializes these eight strategies' Sandbox
updates. Sandbox positions still net by account/symbol, not separate strategy
accounts. Avoid unrelated manual Sandbox trades in those symbols; the lock does
not coordinate arbitrary external orders. Reports retain their own order IDs.

## Watchlists and scanner

In [Trading](http://127.0.0.1:5000/trading), select the exact weekday list
`Mon`, `Tue`, `Wed`, `Thu` or `Fri`, and add **NSE** symbols. The four
watchlist strategies reread today's list every two seconds. New stocks need
valid warmup; removals block new entries but existing positions remain managed.
An empty list waits, with no scanner fallback. Chg% min/max and ASC/DESC sorting
are **display-only**, not saved-membership or strategy filters. Reset restores
manual display order.

On September 30 morning Tue has 16 NSE stocks. With explicit approval, only its
WIPRO exchange was changed from BSE to NSE, retaining item ID 16 and position 15.
At the evening check Wed has 18 stocks and Thu is empty; the user will populate Thu.

Scanner profiles restrict to the imported Nifty500 category **before ranking**:
the union of top 50 positive gainers and top 50 positive volume shockers with
current volume / previous five completed sessions' average > 1. Membership is
rechecked at entry using fresh quotes. Watchlist variants use all eligible
stocks in their daily list, without the scanner ranking restriction.

## September 30 eight-strategy backtest

Completed all eight current profiles with both modeled minute paths, current
0.03% stop, and 09:15–15:00 cutoff. See the
[results, CSVs, assumptions and reproduction](../../backtesting/eight_scheduled_20260930/README.md)
and [offline interactive report](../../backtesting/eight_scheduled_20260930/index.html).
Coverage is 76/76 scanner and 16/18 Wednesday watchlist; GANESHBE/STLTECH are
outside the scheduled EQ-only universe. All eight ledgers and 61 focused tests
pass. These historical simulations do not replace today's interrupted forward
reports or establish tomorrow's operational reliability.

## Reports and September 29 replay

Open [Strategy Reports](http://127.0.0.1:5000/strategy-reports). Choose a report,
scenario and trade for raw/HA candles, BB upper/middle, VWAP, metrics and CSV.
Forward reports update during execution and save at shutdown for EOD review.
Manage schedules in **Python Strategies**; Reports can reinstall all eight.

These replays are for **September 29**, the originally requested session, not
September 30. After FYERS reconnection, non-overlapping epoch-range requests
resolved the watchlist history overlaps without fabricated candles.

**Historical rule:** the saved September 29 results below used the previous
₹0.10 stop offset. They have not been rerun for the September 30 change to a
0.03% offset. New forward runs/replays use the percentage stop; 3R is calculated
from that new stop. Existing reports are preserved, not relabeled.

| Strategy | Eligible stocks | OLHC trades / net | OHLC trades / net |
|---|---:|---:|---:|
| Nifty500 fixed 3R | 74/75 | 255 / ₹2,350.93 | 272 / ₹1,945.60 |
| Weekday fixed 3R | 16/16 | 35 / −₹1,222.97 | 40 / −₹1,430.71 |
| Nifty500 trail after 3R | 74/75 | 209 / ₹1,391.14 | 227 / ₹575.31 |
| Weekday trail after 3R | 16/16 | 28 / −₹60.86 | 34 / −₹324.81 |

ANTHEM is excluded for invalid OHLCV. All saved ledgers pass sizing/stop/target/
trailing checks and all modeled trades close. Fixed-scanner peak simultaneous
notional is approximately ₹5.40–5.48 lakh: per-trade capital is not a portfolio cap.

OLHC/OHLC are **alternative modeled intraminute paths**, eight steps per leg
and uniform modeled volume. Do not add results or interpret them as actual ticks
or rigorous best/worst bounds. Replays include 5 bps adverse slippage per side
and illustrative 5 bps charges per fill, not actual taxes. Afternoon scanner
selection and retrospectively edited watchlists create selection bias; historical
dynamic membership and tick ordering were not recorded. Realized drawdown omits
intratrade equity. One session does not establish future performance.

Storage: `db/scanner_strategy_reports.db`; inputs and hashes:
`db/scanner_backtest_cache/`. September 28 reports remain historical runs with
different capital/cutoffs, not results for these four variants.

## Go/Rust acceleration and checks

Cold FYERS daily-volume baseline downloads use a bounded three-worker Go HTTP
pool, connection reuse, pacing and a rolling request limit. Warm scans reuse
cache. Rust provides an allocation-free BB kernel; Python orchestrates and
provides fallbacks when native binaries are unavailable. Rebuild per platform.

Measured on this Mac: five real daily-history responses matched Python exactly;
Go **0.690 s** versus Python **0.893 s**. A 20-value Rust BB call took **1.901 µs**
versus **12.615 µs** for prior NumPy. These limited component benchmarks are not
order-latency guarantees. Network/feed latency, DB contention and warmup remain;
broker Quote observations are not guaranteed exchange tick-by-tick data.
The first forward session on September 30 was interrupted as described above;
no successful full-session soak or end-to-end latency guarantee is claimed.

Earlier verification: 114 focused Python tests, 19 watchlist UI tests, frontend type
check/build, Go race tests and Rust tests passed. Browser fixtures exercised all
four reports/eight scenarios, indicator lines and mobile layout with no page
errors. Browser authentication was mocked, not a live authenticated operational
check. Real Sandbox order/fill tests used isolated DBs; no production orders
were submitted during verification.

The approved cleanup fix ensures all teardown callbacks are attempted despite
errors: final reporting, feed unregister/disconnect, worker shutdown and DB/HTTP
cleanup. Failure-injection and mutant tests cover the fix. 120 worker/lock cycles
stay within the descriptor bound; queues, latency samples and chart buffers are
bounded. This is not a full-session memory soak.

Developer commands, from the project root:

```sh
.venv/bin/python -m strategies.top_gain_volumes.build_native
.venv/bin/python -m strategies.top_gain_volumes.benchmark_native --network
.venv/bin/python -m strategies.top_gain_volumes.replay_four --day 2026-09-29 --fetch-missing --retry-invalid
.venv/bin/python -m strategies.top_gain_volumes.schedule --install
```

The CLI installer verifies all eight persisted configurations and scheduler jobs;
an already-running app needs a restart after CLI changes. The optional
`--backtest-day` additionally requires verified replays for **all eight** profiles.
The older September 29 reports cover the original four only; September 30 reports
now cover all eight. Runtime regressions cover actual 5m bar/HA construction,
missing minutes, delayed fills, duplicate prevention, and reconnection. Start `uv run app.py` or `.venv/bin/python app.py` in a
terminal: this local Werkzeug configuration rejects detached non-TTY launches.
Do not enable a public debugger to bypass that guard.

September 30 evening verification: **136 focused tests passed**, including delayed
real Sandbox status/fill handling in isolated databases, 5-minute aggregation/HA,
missing-minute exclusion, reconnection/subscription recovery and repeated cache
FD measurements. The exact original pending-fill implementation fails the new
regression test with today's RuntimeError. Updated frontend type check/build pass.
History connections/locks close on exceptions and success; cache row count,
worker queue, tick queue, chart buffers and latency samples are bounded. Existing
HSM Ruff findings (four) are unchanged from HEAD. Historical 5m simulations are
now available above; live full-session behavior remains to be observed.
