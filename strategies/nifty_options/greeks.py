"""Model-derived Black-76 delta from contemporaneous prices and put-call parity.

Historical Greeks are estimates, never broker-observed Greeks. No theoretical
fallback is accepted when the IV inversion fails.
"""

import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .selection import DataUnavailable, Option

IST = ZoneInfo("Asia/Kolkata")


def session_close(day):
    # NSE/FAOP/74467: derivatives extend to 15:40 from August 3, 2026.
    return time(15, 40) if day >= date(2026, 8, 3) else time(15, 30)


def chain_options(contracts, prices, spot, timestamp, lot_sizes):
    from services.option_greeks_service import calculate_chain_greeks

    if not math.isfinite(spot) or spot <= 0:
        raise DataUnavailable("Invalid contemporaneous NIFTY price")
    deltas = {}
    for expiry in sorted({c["expiry"] for c in contracts}):
        selected = [
            c for c in contracts if c["expiry"] == expiry and prices.get(c["symbol"], 0) > 0
        ]
        ladder = {}
        for c in selected:
            ladder.setdefault(c["strike"], {})[c["kind"]] = c
        pairs = [strike for strike, pair in ladder.items() if "CE" in pair and "PE" in pair]
        if not pairs:
            continue
        strike = min(pairs, key=lambda k: abs(k - spot))
        forward = (
            strike + prices[ladder[strike]["CE"]["symbol"]] - prices[ladder[strike]["PE"]["symbol"]]
        )
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        years = (
            datetime.combine(expiry_date, session_close(expiry_date), IST) - timestamp
        ).total_seconds() / (365 * 86400)
        if years <= 0:
            continue
        strikes = sorted(ladder)

        def values(kind, ladder=ladder, strikes=strikes):
            return [
                prices[ladder[s][kind]["symbol"]] if kind in ladder[s] else None for s in strikes
            ]

        ce, pe = calculate_chain_greeks(
            strikes, values("CE"), values("PE"), forward, years, interest_rate=0
        )
        for index, strike in enumerate(strikes):
            for kind, greek in (("CE", ce[index]), ("PE", pe[index])):
                if kind not in ladder[strike] or not greek or greek["iv"] <= 0:
                    continue
                contract = ladder[strike][kind]
                deltas[contract["symbol"]] = greek["delta"]
    # Price-only strategies must not depend on IV inversion. None explicitly
    # means unknown delta; delta-based selectors and held-risk checks reject it.
    return [
        Option(
            c["symbol"],
            date.fromisoformat(c["expiry"]),
            c["strike"],
            c["kind"],
            prices[c["symbol"]],
            deltas.get(c["symbol"]),
            lot_sizes[c["symbol"]],
            timestamp,
        )
        for c in contracts
        if prices.get(c["symbol"], 0) > 0
    ]


def historical_lot_size(expiry, trade_day):
    """NIFTY near-week contracts only. Sources and transition limitations in README."""
    if trade_day.isoformat() < "2021-10-03":
        raise DataUnavailable("Historical lot table begins 2021-10-03")
    if trade_day.isoformat() < "2024-04-26":
        return 50
    if expiry.isoformat() <= "2024-12-26" or expiry.isoformat() == "2025-01-30":
        return 25
    if expiry.isoformat() <= "2025-12-30":
        return 75
    return 65


def historical_margin(profile, selected, spot):
    """Illustrative conservative reserve, NOT historical SPAN/exposure margin.

    Naked pair: 15% underlying notional per short. Condor: full wing width plus
    3% underlying notional plus long premium. Neither claims a broker guarantee.
    """
    lot = selected[0][0].lot_size
    long_premium = sum(o.price for o, side in selected if side > 0)
    if profile.family == "iron_condor":
        return lot * (profile.hedge_width + 0.03 * spot + long_premium)
    return lot * 0.15 * spot * sum(side < 0 for _, side in selected)
