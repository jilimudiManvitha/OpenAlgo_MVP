"""Broker-specific standard retail estimates, never a broker order or ledger debit.

Published tariff snapshot checked 2026-10-07. All rates are fractions of turnover.
Unknown brokers/segments are explicitly unavailable; never substitute FYERS rates.
"""

import math
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

VERSION = "retail-2026-10-07-v1"
COMPONENTS = ("brokerage", "stt", "exchange", "sebi", "stamp", "ipft", "clearing", "gst")
IST = ZoneInfo("Asia/Kolkata")


def rule(rate=0, cap=0, minimum=0, flat=0):
    return {"rate": rate, "cap": cap, "minimum": minimum, "flat": flat}


def profile(name, source, intraday, delivery, futures, options, **extra):
    return dict(
        name=name,
        source=source,
        version=VERSION,
        rules={"intraday": intraday, "delivery": delivery, "futures": futures, "options": options},
        **extra,
    )


PROFILES = {
    "fyers": profile(
        "FYERS standard",
        "https://fyers.in/charges-list",
        rule(0.0003, 20),
        rule(0.003, 20),
        rule(0.0003, 20),
        rule(flat=20),
        clearing={"futures": 0.000005, "options": 0.00009},
    ),
    "zerodha": profile(
        "Zerodha retail",
        "https://zerodha.com/charges",
        rule(0.0003, 20),
        rule(),
        rule(0.0003, 20),
        rule(flat=20),
    ),
    "dhan": profile(
        "Dhan retail",
        "https://dhan.co/pricing/",
        rule(0.0003, 20),
        rule(),
        rule(flat=20),
        rule(flat=20),
    ),
    "groww": profile(
        "Groww retail",
        "https://groww.in/pricing",
        rule(0.001, 20, 5),
        rule(0.001, 20, 5),
        rule(flat=20),
        rule(flat=20),
    ),
    "angel": profile(
        "Angel One Plus",
        "https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges",
        rule(0.001, 20, 5),
        rule(0.001, 20, 5),
        rule(flat=20),
        rule(flat=20),
    ),
    "upstox": profile(
        "Upstox Basic",
        "https://upstox.com/brokerage-charges/",
        rule(0.001, 20),
        rule(flat=20),
        rule(0.0005, 20),
        rule(flat=20),
    ),
    "shoonya": profile(
        "Shoonya standard",
        "https://shoonya.com/pricing",
        rule(0.0003, 5),
        rule(),
        rule(0.0003, 5),
        rule(flat=5),
    ),
    "flattrade": profile(
        "Flattrade zero brokerage",
        "https://flattrade.in/support/knowledge-base/which-segments-have-zero-brokerage/",
        rule(),
        rule(),
        rule(),
        rule(),
    ),
}
ALIASES = {"dhan_sandbox": "dhan", "angelone": "angel", "finvasia": "shoonya"}


def broker_id(value):
    value = str(value or "").strip().lower()
    return ALIASES.get(value, value)


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def tariff(broker):
    return deepcopy(PROFILES.get(broker_id(broker)))


def instrument(trade, report):
    exchange = trade.get("exchange") or report.get("exchange")
    product = trade.get("product") or report.get("product")
    symbol = trade.get("symbol", "")
    # Existing scheduled producer contracts: stock reports are NSE MIS;
    # NIFTY DailyReport uses NFO NRML and preserves numeric long/short side.
    if not exchange and (
        "nifty-options-" in report.get("id", "") or "NIFTY" in report.get("kind", "")
    ):
        exchange, product = "NFO", "NRML"
    if not exchange and (
        report.get("capital_per_trade") == 10000 or report.get("timeframe_minutes")
    ):
        exchange, product = "NSE", "MIS"
    if exchange in ("NSE", "BSE") and product in ("MIS", "CNC"):
        return exchange, "intraday" if product == "MIS" else "delivery"
    if exchange in ("NFO", "BFO"):
        if symbol.endswith(("CE", "PE")):
            return exchange, "options"
        if symbol.endswith("FUT"):
            return exchange, "futures"
    raise ValueError("Exchange/product or instrument type is missing or unsupported.")


def order_cost(turnover, action, exchange, segment, day, rates):
    """One confirmed executed order. Statutory rates follow execution date."""
    if day < "2024-10-01":
        raise ValueError("Statutory rate history before October 2024 is unavailable.")
    if exchange not in ("NSE", "NFO"):
        raise ValueError("Full tax estimates currently support NSE equity and NFO only.")
    r = rates["rules"][segment]
    brokerage = r["flat"] if r["flat"] else min(r["cap"], max(r["minimum"], turnover * r["rate"]))
    if segment in ("intraday", "delivery"):
        brokerage = min(brokerage, turnover * 0.025)  # Statutory cash-market brokerage ceiling.
    modern = day >= "2026-03-01"
    txn = {
        "intraday": 0.000030699 if modern else 0.0000297,
        "delivery": 0.000030699 if modern else 0.0000297,
        "futures": 0.000018299 if modern else 0.0000173,
        "options": 0.000355299 if modern else 0.0003503,
    }[segment]
    stt = {
        "intraday": 0.00025,
        "delivery": 0.001,
        "futures": 0.0005 if day >= "2026-04-01" else 0.0002,
        "options": 0.0015 if day >= "2026-04-01" else 0.001,
    }[segment]
    stamp = {"intraday": 0.00003, "delivery": 0.00015, "futures": 0.00002, "options": 0.00003}[
        segment
    ]
    # NSE rebalance moves IPFT into transaction charges from March 2026.
    ipft = 0.000000001 if modern else (0.000005 if segment == "options" else 0.000001)
    values = {
        "brokerage": brokerage,
        "stt": turnover * stt if action == "SELL" or segment == "delivery" else 0,
        "exchange": turnover * txn,
        "sebi": turnover * 0.000001,
        "stamp": turnover * stamp if action == "BUY" else 0,
        "ipft": turnover * ipft,
        "clearing": turnover * rates.get("clearing", {}).get(segment, 0),
    }
    values["gst"] = 0.18 * sum(
        values[k] for k in ("brokerage", "exchange", "sebi", "ipft", "clearing")
    )
    return {key: rounded(value) for key, value in values.items()}


def estimate_report(report, session_broker="", basis="estimated"):
    """Copy/enrich, preserving raw records and never adding estimates to actual fees.

    Executions sharing an order ID share one brokerage cap. Costs are allocated
    proportionally across those trade rows, preserving the order's rounded total.
    Round-trip realized charges are recognized at closure; open entry costs are
    disclosed separately and never booked again into the next day's realized P&L.
    """
    result = deepcopy(report)
    context = report.get("brokerage_context") or {}
    broker = broker_id(context.get("broker") or report.get("broker") or session_broker)
    rates = context.get("tariff") or tariff(broker)
    inferred = not (context.get("broker") or report.get("broker"))
    result["charge_info"] = {
        "broker": broker,
        "profile": rates.get("name") if rates else None,
        "version": rates.get("version") if rates else None,
        "source": rates.get("source") if rates else None,
        "broker_inferred": inferred,
        "basis": basis,
        "unavailable": 0,
        "notice": "Estimates exclude DP, delivery settlement, exercise/assignment, auto-square-off, call-and-trade, financing and account fees. Published retail tariff snapshot; older untagged reports use the current login broker.",
    }
    if basis == "recorded":
        for trade in result["trades"]:
            trade["charge_status"] = "recorded"
        return result
    orders = defaultdict(list)
    for index, t in enumerate(result["trades"]):
        t["recorded_fees"] = t.get("fees", 0)
        t["recorded_net_pnl"] = t.get("net_pnl", 0)
        if t.get("fees_actual") is True:
            t["charge_status"] = "actual"
            continue
        t["charge_breakdown"] = dict.fromkeys(COMPONENTS, 0.0)
        t["entry_estimated_fees"] = 0.0
        t["charge_status"] = "estimated"
        if t.get("entry_order_state", "complete") != "complete":
            t["charge_status"] = "unfilled"
            continue
        try:
            if not rates:
                raise ValueError(f"No verified standard tariff for {broker or 'unknown broker'}.")
            exchange, segment = instrument(t, report)
            direction = t.get("side", t.get("action"))
            if direction is None and (
                report.get("capital_per_trade") == 10000 or report.get("timeframe_minutes")
            ):
                direction = 1
            if direction not in (1, -1, "BUY", "SELL", "LONG", "SHORT"):
                raise ValueError("Entry side is missing or unsupported.")
            action = "SELL" if direction in (-1, "SELL", "SHORT") else "BUY"
            for phase in ("entry", "exit"):
                ts = t.get(phase + "_ts")
                if ts is None:
                    continue
                price = float(t.get(phase))
                qty = float(t["quantity"])
                if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty <= 0:
                    raise ValueError("Invalid execution price/quantity.")
                day = datetime.fromtimestamp(ts, IST).date().isoformat()
                order_action = (
                    action if phase == "entry" else ("BUY" if action == "SELL" else "SELL")
                )
                orderid = t.get(phase + "_order") or (
                    t.get("orderid") if phase == "entry" else None
                )
                key = (
                    t.get("path"),
                    exchange,
                    segment,
                    day,
                    order_action,
                    orderid or f"row-{index}-{phase}",
                )
                orders[key].append((index, phase, price * qty))
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            t["charge_status"] = "unavailable"
            t["charge_error"] = str(exc)
    for (_, exchange, segment, day, action, _), parts in orders.items():
        turnover = sum(p[2] for p in parts)
        try:
            cost = order_cost(turnover, action, exchange, segment, day, rates)
            remainder = cost.copy()
            for number, (index, phase, value) in enumerate(parts):
                t = result["trades"][index]
                allocation = {
                    k: remainder[k]
                    if number == len(parts) - 1
                    else rounded(v * value / turnover)
                    if turnover
                    else 0
                    for k, v in cost.items()
                }
                for key, value in allocation.items():
                    remainder[key] = rounded(remainder[key] - value)
                    t["charge_breakdown"][key] = rounded(t["charge_breakdown"][key] + value)
                if phase == "entry":
                    t["entry_estimated_fees"] = rounded(sum(allocation.values()))
        except (ValueError, TypeError, KeyError) as exc:
            for index, _, _ in parts:
                result["trades"][index]["charge_status"] = "unavailable"
                result["trades"][index]["charge_error"] = str(exc)
    for t in result["trades"]:
        if t["charge_status"] == "estimated":
            t["fees"] = rounded(sum(t["charge_breakdown"].values()))
            t["net_pnl"] = (
                rounded(t.get("gross_pnl", 0) - t["fees"]) if t.get("exit_ts") is not None else 0
            )
        elif t["charge_status"] == "unavailable":
            result["charge_info"]["unavailable"] += 1
            # Arithmetic can still use recorded values internally; the journal
            # masks net, fees, win counts and streaks when estimates are unknown.
    return result


def capture_context(owner, report, previous=None):
    """Used only by the isolated ReportStore overlay until approved deployment."""
    if previous and previous.get("brokerage_context"):
        report["brokerage_context"] = deepcopy(previous["brokerage_context"])
        return
    if report.get("brokerage_context"):
        return
    broker = report.get("broker")
    if not broker:
        from database.auth_db import Auth, db_session

        try:
            broker = db_session.query(Auth.broker).filter(Auth.name == owner).scalar()
        finally:
            db_session.remove()
    if broker:
        broker = broker_id(broker)
        report["brokerage_context"] = {
            "broker": broker,
            "tariff": tariff(broker),
            "captured_at": datetime.now(IST).isoformat(),
            "version": VERSION,
        }


def charges_csv(report):
    import csv
    import io

    fields = [
        "symbol",
        "path",
        "entry_ts",
        "exit_ts",
        "quantity",
        "entry",
        "exit",
        "gross_pnl",
        "fees",
        "net_pnl",
        "recorded_fees",
        "recorded_net_pnl",
        "charge_status",
        "charge_error",
        "broker",
        "tariff_version",
        *COMPONENTS,
        "reason",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    info = report["charge_info"]
    for trade in report["trades"]:
        row = {
            **trade,
            **trade.get("charge_breakdown", {}),
            "broker": info["broker"],
            "tariff_version": info["version"],
        }
        if trade.get("charge_status") == "unavailable":
            row["fees"] = row["net_pnl"] = ""
        for key, value in row.items():
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                row[key] = "'" + value
        writer.writerow(row)
    return output.getvalue()
