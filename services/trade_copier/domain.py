"""Strict canonical orders and child policy validation."""

import hashlib
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo


class CopierError(ValueError):
    pass


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(*values):
    return hashlib.sha256(packed(values).encode()).hexdigest()


def today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def number(value, name, minimum=0, maximum=1e12, integer=False):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise CopierError(f"Invalid {name}") from None
    if isinstance(value, bool) or not math.isfinite(n) or not minimum <= n <= maximum:
        raise CopierError(f"Invalid {name}")
    if integer and n != int(n):
        raise CopierError(f"{name} must be an integer")
    return int(n) if integer else n


def order(data):
    if not isinstance(data, dict):
        raise CopierError("Order must be an object")
    result = {
        k: str(data.get(k, "")).strip()
        for k in ("orderid", "symbol", "exchange", "action", "pricetype", "product", "order_status")
    }
    result["product"] = {"INTRADAY": "MIS", "MARGIN": "NRML"}.get(
        result["product"], result["product"]
    )
    if (
        not result["orderid"]
        or len(result["orderid"]) > 100
        or not result["symbol"]
        or len(result["symbol"]) > 100
    ):
        raise CopierError("Missing or invalid order identity")
    if result["action"] not in ("BUY", "SELL") or result["exchange"] not in (
        "NSE",
        "BSE",
        "NFO",
        "BFO",
        "CDS",
        "BCD",
        "MCX",
    ):
        raise CopierError("Unsupported side or exchange")
    if result["pricetype"] not in ("MARKET", "LIMIT", "SL", "SL-M") or result["product"] not in (
        "CNC",
        "MIS",
        "NRML",
    ):
        raise CopierError("Unsupported order type or product")
    if result["order_status"] not in (
        "open",
        "trigger pending",
        "complete",
        "cancelled",
        "rejected",
        "expired",
    ):
        raise CopierError("Unsupported order status")
    for key in ("quantity", "filled_quantity"):
        result[key] = number(data.get(key, 0), key, maximum=10000000, integer=True)
    if result["quantity"] <= 0 or result["filled_quantity"] > result["quantity"]:
        raise CopierError("Invalid filled quantity")
    for key in ("price", "trigger_price", "average_price"):
        result[key] = number(data.get(key, 0), key)
    if result["pricetype"] in ("LIMIT", "SL") and result["price"] <= 0:
        raise CopierError("Limit price required")
    if result["pricetype"] in ("SL", "SL-M") and result["trigger_price"] <= 0:
        raise CopierError("Trigger price required")
    return result


def policy(data):
    p = {
        "copy_mode": data.get("copy_mode", "fill"),
        "multiplier": number(data.get("multiplier", 1), "multiplier", 0.01, 100),
        "max_quantity": number(data.get("max_quantity", 1000), "max quantity", 1, 1000000, True),
        "max_order_value": number(data.get("max_order_value", 100000), "max order value", 1),
        "max_daily_value": number(data.get("max_daily_value", 500000), "max daily value", 1),
        "max_daily_loss": number(data.get("max_daily_loss", 5000), "max daily loss", 1),
        "max_position_quantity": number(
            data.get("max_position_quantity", 2000), "max position", 1, 10000000, True
        ),
    }
    if p["copy_mode"] not in ("fill", "fast", "hybrid"):
        raise CopierError("Select fill, fast or hybrid copying")
    for key in ("symbols", "fast_symbols"):
        values = data.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 100
            or any(not isinstance(x, str) or not x or len(x) > 100 for x in values)
        ):
            raise CopierError(f"Invalid {key}")
        p[key] = sorted(set(values))
    # An explicit allowlist prevents accidentally copying discretionary/unrelated trades.
    import re

    if any(
        not re.fullmatch(r"(?:NSE|BSE|NFO|BFO|CDS|BCD|MCX):[A-Z0-9&._-]+", x) for x in p["symbols"]
    ):
        raise CopierError("Use EXCHANGE:SYMBOL, for example NSE:SBIN")
    if not p["symbols"]:
        raise CopierError("Add at least one allowed symbol (for example NSE:SBIN)")
    if not set(p["fast_symbols"]).issubset(p["symbols"]):
        raise CopierError("Hybrid fast symbols must also be allowed symbols")
    return p
