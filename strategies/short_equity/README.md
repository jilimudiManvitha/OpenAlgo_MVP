# Eight short equity Sandbox strategies

Integrated locally October 7, 2026 after the user stopped OpenAlgo. Eight short
schedules are installed alongside the original twenty. All sixteen equity
profiles square off at **15:15 IST**; twelve option schedules remain unchanged.
Only the user starts production. See [release handoff](../../docs/plans/2026-10-07-evening-combine.md).

These are the short counterparts of the eight equity profiles in
`strategies/top_gain_volumes/`. Twelve NIFTY option profiles are outside this work.

| Universe | Candle interval | Exit variants | Count |
|---|---|---|---|
| Nifty500 scanner | 1 minute | Fixed 3R / trail after 3R | 2 |
| Weekday NSE watchlist | 1 minute | Fixed 3R / trail after 3R | 2 |
| Nifty500 scanner | 5 minutes | Fixed 3R / trail after 3R | 2 |
| Weekday NSE watchlist | 5 minutes | Fixed 3R / trail after 3R | 2 |

## Rules

- Use Heikin Ashi, matching the existing equity strategies. Aggregate real
  one-minute OHLCV before constructing five-minute HA candles. BB uses 20 HA
  closes and two population standard deviations; VWAP uses real-session
  typical price and volume, as in the long runtime.
- A completed signal must be red, have no upper HA wick, and have HA low
  strictly below the lower BB. **Every signal HA OHLC must be below VWAP**.
  This retains the long counterpart's band-break condition with reversed
  direction; a separate close-only signal rule is not introduced.
- During the **immediately following** candle, require red/no-upper-wick HA,
  all observed forming HA OHLC below forming VWAP, and observed price strictly
  below both the signal low and the forming lower BB. Submit intrabar; do not
  wait for the entry candle's close. Touching a level is insufficient. Future
  candle OHLC is never used to authorize an earlier entry.
- The strict all-OHLC VWAP rule applies to all eight new shorts, including
  fixed-exit profiles, as explicitly requested. Existing fixed long profiles
  have a weaker VWAP rule; they are unchanged.
- **SELL MARKET / NSE MIS** entry; **BUY MARKET** cover. Sandbox only, through
  the existing `OrderManager`, with confirmed order IDs and fills. Global
  Analyzer mode is not changed and no live broker order router is called.
- Whole-share sizing up to ₹10,000 entry notional, not ₹10,000 loss risk.
  Initial stop = signal HA high × 1.0003, rounded **up** to the tick.
  Risk = confirmed entry stop distance; target = entry − 3 × risk, rounded
  **down**. Reject an entry with invalid stop geometry or nonpositive target.
- Fixed variants cover at 3R. Trailing variants arm at 3R, then cover when
  observed price rises strictly above forming BB middle. They retain the
  original stop; no partial exit or break-even stop movement is introduced.
- Stop new entries at 15:15 IST and cover using fresh quotes, including cached
  quotes when no new tick arrives. Preserve the existing 60-second shutdown
  reconciliation grace; missing quotes/unknown order outcomes remain unresolved.
- One active trade per symbol per strategy; a fresh signal may re-enter after
  exit. No added portfolio-wide trade-count limit.

## Selection and scheduling

Scanner shorts select only imported Nifty500 members with fresh, negative
change%, then take the union of the top 50 losers and top 50 negative volume
shockers with relative volume > 1. The five-completed-session volume baseline
is unchanged. Ranking is mirrored before applying limits, including tie-breaks.
Membership is rechecked at entry.

Watchlist shorts reuse today's exact `Mon`, `Tue`, `Wed`, `Thu` or `Fri` list
and its NSE stocks, with the existing two-second refresh. Empty lists wait;
there is no scanner fallback. No list was populated or changed.

All eight installed schedules use **09:15–15:15 IST, Monday–Friday, exchange NSE**,
which retains the existing scheduler's exchange-calendar gate. IDs start with
`Short10K_`, and report IDs include each unique short profile ID. Reports retain
`side=SELL`, `direction=SHORT`, and lower/upper/middle BB values. Existing report
P&L metrics consume the signed short P&L directly; the fee estimator can identify
SELL entries from this side field. The integrated report chart draws lower/middle/VWAP for short trades and
includes the short stop and target in its price range.

## Isolation and integration

The installed package lives in `strategies/short_equity/`; root strategy scripts
are scheduler entry points. It reuses history, the native BB kernel,
watchlist/category access, and owner dispatch locking from `top_gain_volumes`.
Tests exercise the installed package using isolated databases and synthetic quotes.
The earlier `.development/equity-shorts/` snapshot remains guarded against running
and is historical. Read-only schedule verification is available through
`.development/oct7-combine/schedules.py`.

The shared Sandbox still nets positions by owner/symbol/product, **not by
strategy**. Simultaneous long and short orders can offset in the account position;
each strategy report retains its own fills and P&L. A separate paper account per
strategy has not been introduced. Actual forward prices can move between sizing
and execution; the ₹10,000 bound is calculated at dispatch, not guaranteed under
an arbitrary delayed fill. A full-market-session soak/backtest is not claimed.

See [evening release verification](../../docs/plans/2026-10-07-evening-combine.md). Only the user stops and starts production.
