# Options capital check — October 8, 2026

Read-only inspection at approximately 07:04 IST. The latest persisted executions
are October 7. No orders, schedule changes, fund adjustments or process actions
were performed. This note concerns installed code and saved execution evidence,
not a fresh broker margin quote or a backtest.

## Finding

The strategy sizing budget and Sandbox displayed used margin use different
calculations. The difference is material for options, particularly option shorts.

- Each profile has ₹20,00,000 capital. `policy.json` has `lots: null`, allowing
  automatic whole-lot sizing rather than fixing one lot.
- The runtime queries FYERS for the selected one-lot basket, sizes against 90%
  of the capital, then checks the full-quantity basket against ₹18,00,000. It
  assigns the same quantity to each leg. Twelve nominal allocations sum to
  ₹2.4 crore; their 90% sizing budgets sum to ₹2.16 crore before whole-lot rounding.
- These allocations are sizing limits, not twelve cash reservations in the
  shared Sandbox funds table.
- `sandbox/fund_manager.py:calculate_margin_required` instead blocks
  `abs(quantity) × option price / leverage`. Both configured option leverages
  are 1. This is a premium-based model for BUY and SELL, not the FYERS basket
  requirement used by the strategy. The daily Reports capital statistics also
  describe premium turnover, not broker margin.
- Identical contracts share account positions. Opposite actions may reduce or
  offset those positions across strategies, further affecting displayed margin.

## Actual October 7 opening orders

All twelve initial baskets have complete fills. Quantities were equal across
their initial legs, using lot size 65. The hedge update was installed after these
entries, so the Delta/Premium entries below originally had two short legs.

| Family | Intraday current | Intraday next | Positional current | Positional next |
|---|---:|---:|---:|---:|
| Iron condor — lots per leg | 9 | 10 | 10 | 12 |
| Delta — lots per leg | 9 | 9 | 10 | 11 |
| Premium — lots per leg | 9 | 10 | 10 | 11 |

Sum of gross opening leg premiums: ₹7,37,925.50. Sum of margin blocked by the
32 initial option orders: **₹7,22,306.00**. The difference of ₹15,619.50 is in
the current-week intraday condor orders that interacted with existing account
positions. These are opening-order totals, not a reconstructed simultaneous
account-wide peak, and exclude equity strategies.

Example: positional current-week condor, ten lots per leg = 650 units each.
Entry premiums were ₹4.35 + ₹6.45 for long wings and ₹9.60 + ₹11.45 for shorts.
The Sandbox blocked `650 × (4.35 + 6.45 + 9.60 + 11.45) = ₹20,702.50` across
those four orders, although the strategy's sizing allocation was ₹20 lakh.

At inspection, all six intraday variants had closed. Six positional variants
held fifteen attributed legs, aggregated into twelve net NFO NRML positions.
Sandbox used margin was **₹1,76,926.75**, exactly matching the sum of open-position
blocked margin and their absolute quantity times average entry price. There were
zero pending orders and zero active GTTs. This reconciles the current funds value
under the existing Sandbox formula; it does not validate that formula as broker
margin. The user's roughly ₹10 lakh intraday observation was not supplied with a
timestamp, so the precise account snapshot cannot be matched.

## Limits and next correction

The saved intents and twelve October 7 strategy logs do not retain the FYERS
one-lot/full-basket response amounts used at entry. Therefore this audit confirms
equal lot sizes and the model mismatch, but cannot certify the exact broker-margin
utilization percentage for each historical basket. A fresh quote would describe
current prices/positions, not reconstruct that entry response.

The runtime takes the larger of `margin_total` and `margin_new_order`. If a response
includes unrelated account positions, sizing can be conservative. This possibility
is not established as the cause of these fills without the original responses.

To make capital utilization auditable, persist and report the allocation,
deployable budget, both raw broker margin fields, selected lots and full-basket
check separately from Sandbox blocked premium. Broker-style Sandbox fund
reservation would be a distinct accounting change requiring coherent handling
of netting, adjustments, restarts and release; changing lot counts merely to make
the premium-based display reach ₹20 lakh would use a different sizing rule.

The installed hedge update requires four equal-quantity legs for all new baskets.
Seven legacy Delta/Premium short legs are still awaiting hedge recovery when
updated runners next start with fresh quotes. The existing recovery preserves
their quantities; it does not resize carried baskets to spend the allocation.

Relevant code: `strategies/nifty_options/runtime.py:broker_margin` and its open
action, `engine.py:lots_for_margin`, `sandbox/fund_manager.py:calculate_margin_required`,
and `strategies/nifty_options/daily_reports.py:DailyReport.save`.
