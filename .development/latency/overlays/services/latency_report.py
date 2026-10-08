"""One bounded snapshot for latency cards, distribution, tables and CSV."""

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from database.latency_db import OrderLatency, latency_engine

MAX_ROWS = 10000
ORDER_TYPES = frozenset(
    (
        "PLACE",
        "SMART",
        "MODIFY",
        "CANCEL",
        "CLOSE",
        "CANCEL_ALL",
        "BASKET",
        "SPLIT",
        "OPTIONS",
        "OPTIONS_MULTI",
        "GTT_PLACE",
        "GTT_MODIFY",
        "GTT_CANCEL",
        "OPTIONSORDER",
        "OPTIONSMULTIORDER",
        "PLACE_GTT_ORDER",
        "MODIFY_GTT_ORDER",
        "CANCEL_GTT_ORDER",
        "PLACEORDER",
        "PLACESMARTORDER",
        "MODIFYORDER",
        "CANCELORDER",
        "CLOSEPOSITION",
        "CANCELALLORDER",
        "BASKETORDER",
        "SPLITORDER",
    )
)
IST = ZoneInfo("Asia/Kolkata")


def filters(args):
    result = {
        k: args.get(k, default)
        for k, default in [
            ("kind", "orders"),
            ("period", "today"),
            ("broker", ""),
            ("operation", ""),
            ("status", "all"),
            ("mode", "all"),
        ]
    }
    allowed = {
        "kind": {"orders", "data", "all"},
        "period": {"today", "24h", "7d", "30d", "all"},
        "status": {"all", "SUCCESS", "FAILED", "PARTIAL"},
        "mode": {"all", "live", "sandbox", "unknown"},
    }
    for key, choices in allowed.items():
        if result[key] not in choices:
            raise ValueError("Invalid " + key)
    for key in ("broker", "operation"):
        if len(result[key]) > 50 or any(not (c.isalnum() or c in "_-") for c in result[key]):
            raise ValueError("Invalid " + key)
    return result


def snapshot(selected, now=None):
    now = now or datetime.now(UTC)
    query = select(
        *[
            getattr(OrderLatency, name)
            for name in (
                "id",
                "timestamp",
                "order_id",
                "broker",
                "symbol",
                "order_type",
                "total_latency_ms",
                "status",
                "error",
                "rtt_ms",
                "overhead_ms",
            )
        ],
        OrderLatency.request_body["latency_meta"].label("meta"),
    )
    period = selected["period"]
    if period != "all":
        start = (
            datetime.combine(now.astimezone(IST).date(), time(), IST).astimezone(UTC)
            if period == "today"
            else now - timedelta(hours={"24h": 24, "7d": 168, "30d": 720}[period])
        )
        query = query.where(OrderLatency.timestamp >= start.replace(tzinfo=None))
    query = query.where(OrderLatency.timestamp <= now.replace(tzinfo=None))
    order = func.upper(OrderLatency.order_type).in_(ORDER_TYPES)
    if selected["kind"] == "orders":
        query = query.where(order)
    elif selected["kind"] == "data":
        query = query.where(or_(~order, OrderLatency.order_type.is_(None)))
    for key, column in [("broker", OrderLatency.broker), ("operation", OrderLatency.order_type)]:
        if selected[key]:
            query = query.where(column == selected[key])
    if selected["status"] != "all":
        query = query.where(OrderLatency.status == selected["status"])
    mode = OrderLatency.request_body["latency_meta"]["mode"].as_string()
    if selected["mode"] == "unknown":
        query = query.where(or_(mode.is_(None), mode == "unknown"))
    elif selected["mode"] != "all":
        query = query.where(mode == selected["mode"])
    query = (
        query.add_columns(func.count().over().label("matched_count"))
        .order_by(OrderLatency.timestamp.desc(), OrderLatency.id.desc())
        .limit(MAX_ROWS)
    )
    # A single SELECT is one consistent snapshot. No ORM objects/session held by the response.
    with latency_engine.connect() as connection:
        raw = connection.execute(query).mappings().all()
    logs = []
    for row in raw:
        meta = row["meta"] if isinstance(row["meta"], dict) else {}
        stamp = row["timestamp"]
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        measured = meta.get("version") == 2
        logs.append(
            {
                **{
                    k: row[k]
                    for k in (
                        "id",
                        "order_id",
                        "broker",
                        "symbol",
                        "order_type",
                        "total_latency_ms",
                        "status",
                        "error",
                    )
                },
                "timestamp": stamp.astimezone(IST).isoformat(),
                "mode": meta.get("mode", "unknown"),
                "http_ms": row["rtt_ms"] if measured else None,
                "other_ms": row["overhead_ms"] if measured else None,
                "legacy_rtt_ms": None if measured else row["rtt_ms"],
                "legacy_overhead_ms": None if measured else row["overhead_ms"],
                "http_calls": meta.get("http_calls") if measured else None,
                "timing_basis": "measured HTTP + remaining endpoint time"
                if measured
                else "legacy attribution (may contain only last HTTP call)",
                "category": "order" if (row["order_type"] or "").upper() in ORDER_TYPES else "data",
            }
        )
    return report(logs, selected, raw[0]["matched_count"] if raw else 0, now)


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * q
    lower = math.floor(index)
    return values[lower] + (values[math.ceil(index)] - values[lower]) * (index - lower)


def summary(rows):
    good = [
        r
        for r in rows
        if r["status"] == "SUCCESS"
        and isinstance(r["total_latency_ms"], (int, float))
        and math.isfinite(r["total_latency_ms"])
        and r["total_latency_ms"] >= 0
    ]
    values = [r["total_latency_ms"] for r in good]
    dist = {"excellent": 0, "good": 0, "acceptable": 0, "slow": 0}
    for n in values:
        dist[
            "excellent" if n < 150 else "good" if n < 250 else "acceptable" if n < 400 else "slow"
        ] += 1
    measured = [r for r in good if r["http_ms"] is not None]
    return {
        "total": len(rows),
        "successful": sum(r["status"] == "SUCCESS" for r in rows),
        "failed": sum(r["status"] == "FAILED" for r in rows),
        "partial": sum(r["status"] == "PARTIAL" for r in rows),
        "success_rate": 100 * sum(r["status"] == "SUCCESS" for r in rows) / len(rows)
        if rows
        else None,
        "timed_successes": len(values),
        "invalid_timings": sum(r["status"] == "SUCCESS" for r in rows) - len(values),
        "avg_ms": sum(values) / len(values) if values else None,
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "max_ms": max(values) if values else None,
        "fast_pct": 100 * dist["excellent"] / len(values) if values else None,
        "distribution": dist,
        "http_ms": sum(r["http_ms"] for r in measured) / len(measured) if measured else None,
        "other_ms": sum(r["other_ms"] for r in measured) / len(measured) if measured else None,
        "measured_count": len(measured),
    }


def report(logs, selected, matched, now):
    brokers, operations = defaultdict(list), defaultdict(list)
    for row in logs:
        brokers[row["broker"] or "Unattributed"].append(row)
        operations[row["order_type"] or "Unknown"].append(row)
    errors = Counter((r["error"] or r["status"]) for r in logs if r["status"] != "SUCCESS")
    return {
        "filters": selected,
        "as_of": now.isoformat(),
        "matched_count": matched,
        "sample_count": len(logs),
        "sample_limit": MAX_ROWS,
        "truncated": matched > len(logs),
        "stats": summary(logs),
        "brokers": {k: summary(v) for k, v in sorted(brokers.items())},
        "operations": {k: summary(v) for k, v in sorted(operations.items())},
        "failures": [{"reason": k, "count": v} for k, v in errors.most_common(20)],
        "logs": logs,
        "notice": "Endpoint response time, not exchange fill time. Speed statistics use successful requests only; failures remain in success-rate counts. Legacy Live/Sandbox mode and HTTP breakdown cannot be reconstructed.",
    }
