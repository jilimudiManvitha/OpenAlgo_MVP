import csv
import io
from datetime import datetime

from flask import Blueprint, Response, jsonify, redirect, request

from limiter import limiter
from services.latency_report import filters, snapshot
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)
latency_bp = Blueprint("latency_bp", __name__, url_prefix="/latency")


def safe_cell(value):
    value = str(value or "")
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def generate_csv(logs):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Date & Time (IST)",
            "Broker",
            "Order ID",
            "Symbol",
            "Operation",
            "Mode",
            "Category",
            "Measured HTTP (ms)",
            "Remaining endpoint time (ms)",
            "Total response time (ms)",
            "Status",
            "Error",
            "Timing basis",
            "HTTP calls",
        ]
    )
    for row in logs:
        writer.writerow(
            [
                safe_cell(
                    datetime.fromisoformat(row["timestamp"]).strftime("%d-%m-%Y %I:%M:%S %p")
                ),
                safe_cell(row["broker"]),
                safe_cell(row["order_id"]),
                safe_cell(row["symbol"]),
                safe_cell(row["order_type"]),
                row["mode"],
                row["category"],
                row["http_ms"],
                row["other_ms"],
                row["total_latency_ms"],
                safe_cell(row["status"]),
                safe_cell(row["error"]),
                row["timing_basis"],
                row["http_calls"],
            ]
        )
    return output.getvalue()


@latency_bp.route("/api/dashboard")
@check_session_validity
@limiter.limit("60/minute")
def dashboard_data():
    try:
        data = snapshot(filters(request.args))
        data["recent"] = data.pop("logs")[:100]
        return jsonify(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        logger.exception("Latency snapshot failed")
        return jsonify(error="Latency data unavailable"), 500


@latency_bp.route("/export")
@check_session_validity
@limiter.limit("10/minute")
def export_logs():
    try:
        data = snapshot(filters(request.args))
        response = Response(
            generate_csv(data["logs"]),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=latency_logs.csv"},
        )
        response.headers["X-Latency-Sample-Limit"] = str(data["sample_limit"])
        response.headers["X-Latency-Sample-Truncated"] = str(data["truncated"]).lower()
        return response
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        logger.exception("Latency export failed")
        return jsonify(error="Latency export unavailable"), 500


# Keep old read URLs useful without exposing an unbounded legacy path.
@latency_bp.route("/api/logs")
@check_session_validity
@limiter.limit("60/minute")
def get_logs():
    try:
        limit = int(request.args.get("limit", "100"))
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        return jsonify(snapshot(filters(request.args))["logs"][:limit])
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@latency_bp.route("/api/stats")
@check_session_validity
@limiter.limit("60/minute")
def get_stats():
    try:
        data = snapshot(filters(request.args))
        stats = data["stats"]

        def legacy(s):
            return {
                **s,
                "total_orders": s["total"],
                "failed_orders": s["failed"],
                "avg_total": s["avg_ms"],
                "p50_total": s["p50_ms"],
                "p95_total": s["p95_ms"],
                "p99_total": s["p99_ms"],
                "sla_150ms": s["fast_pct"],
            }

        return jsonify(
            {
                **legacy(stats),
                "broker_stats": {k: legacy(v) for k, v in data["brokers"].items()},
                "sample_count": data["sample_count"],
                "truncated": data["truncated"],
            }
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@latency_bp.route("/")
@check_session_validity
def latency_dashboard():
    return redirect("/logs/latency", code=302)


@latency_bp.route("/api/broker/<broker>/stats")
@check_session_validity
@limiter.limit("60/minute")
def get_broker_stats(broker):
    try:
        selected = filters({**request.args, "broker": broker})
        data = snapshot(selected)
        if broker not in data["brokers"]:
            return jsonify(error="No matching broker records"), 404
        stats = data["brokers"][broker]
        return jsonify(
            {
                **stats,
                "total_orders": stats["total"],
                "failed_orders": stats["failed"],
                "avg_total": stats["avg_ms"],
                "p50_total": stats["p50_ms"],
                "p99_total": stats["p99_ms"],
                "sla_150ms": stats["fast_pct"],
            }
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
