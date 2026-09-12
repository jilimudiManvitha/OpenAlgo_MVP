"""Session-authenticated live scanner and legacy Fyers snapshot APIs."""

from functools import wraps

from flask import Blueprint, jsonify, request, session

from services.market_scanner_provider import ScannerError, get_fyers_token, load_universe
from services.market_scanner_service import scanner_manager
from utils.logging import get_logger
from utils.session import is_session_valid


def live_endpoint(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            if not is_session_valid() or not session.get("user") or not session.get("broker"):
                raise ScannerError("Log in to OpenAlgo to use the scanner.", 401)
            from services.market_scanner_provider import credentials

            credentials(session["user"], session["broker"])
            return function(*args, **kwargs)
        except ScannerError as exc:
            return jsonify(status="error", message=str(exc)), exc.status_code
        except Exception:
            logger.exception("Live scanner API failed")
            return jsonify(status="error", message="Unable to load live scanner."), 500

    return wrapped


logger = get_logger(__name__)
market_scanner_bp = Blueprint("market_scanner", __name__, url_prefix="/market-scanner/api")


def scanner_endpoint(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            if not is_session_valid() or not session.get("user"):
                raise ScannerError("Log in to OpenAlgo to use the scanner.", 401)
            if session.get("broker") != "fyers":
                raise ScannerError("The stock scanner requires a Fyers broker session.", 403)
            get_fyers_token(session["user"])
            return function(*args, **kwargs)
        except ScannerError as exc:
            return jsonify(status="error", message=str(exc)), exc.status_code
        except Exception:
            logger.exception("Stock scanner API failed")
            return jsonify(status="error", message="Unable to process the scanner request."), 500

    return wrapped


@market_scanner_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@market_scanner_bp.get("/universe")
@scanner_endpoint
def universe():
    items = load_universe()
    return jsonify(
        status="success",
        data={"exchange": "NSE", "series": "EQ", "count": len(items), "symbols": items},
    )


@market_scanner_bp.post("/scan")
@scanner_endpoint
def start_scan():
    data = request.get_json(silent=True)
    result, reused = scanner_manager.start(session["user"], data)
    return jsonify(status="success", data=result, reused=reused), 202


@market_scanner_bp.get("/results")
@scanner_endpoint
def results():
    return jsonify(
        status="success", data=scanner_manager.results(session["user"], request.args.to_dict())
    )


@market_scanner_bp.post("/cancel")
@scanner_endpoint
def cancel():
    return jsonify(status="success", data=scanner_manager.cancel(session["user"]))


@market_scanner_bp.before_app_request
def attach_live_scanner():
    # Normal authenticated app navigation attaches automatically after login.
    if request.path.startswith(("/assets/", "/static/")) or request.method != "GET":
        return
    if not session.get("user") or not session.get("broker") or not is_session_valid():
        return
    from services.market_scanner_live import coordinator

    try:
        live = coordinator()
        live.store.configure(session["user"], session["broker"])
    except Exception:
        logger.exception("Could not attach live scanner")


@market_scanner_bp.get("/live")
@live_endpoint
def live_results():
    import json
    from pathlib import Path

    from services.market_scanner_live import coordinator, import_categories, view_snapshot
    from services.market_scanner_service import validate_options

    live = coordinator()
    account = live.store.configure(session["user"], session["broker"])
    record = next(r for r in live.store.accounts() if r["account"] == account)
    categories = live.store.categories()
    if not categories:
        categories = live.store.categories(import_categories(Path("stock_symbols_CSVs")))
    filters = request.args.to_dict()
    category = filters.pop("category", "all")
    if set(filters) - {"min_rvol", "min_price", "max_price", "min_volume", "limit"}:
        raise ScannerError("Unknown live scanner filter.")
    options = validate_options({**json.loads(record["options"]), **filters})
    result = view_snapshot(
        json.loads(record["snapshot"]) if record["snapshot"] else None,
        options,
        categories,
        category,
    )
    result.update(
        enabled=bool(record["enabled"]),
        broker=record["broker"],
        categories=[
            dict(id=k, **{n: v for n, v in item.items() if n != "symbols"})
            for k, item in categories.items()
        ],
        timestamp_support="native"
        if record["broker"] in {"fyers", "zerodha"}
        else "provider dependent",
    )
    return jsonify(status="success", data=result)


@market_scanner_bp.post("/live")
@live_endpoint
def live_control():
    from services.market_scanner_live import coordinator

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {"enabled", "options"}:
        raise ScannerError("Send enabled and/or scanner options.")
    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        raise ScannerError("enabled must be true or false.")
    coordinator().store.configure(
        session["user"], session["broker"], payload.get("options"), payload.get("enabled")
    )
    return jsonify(status="success")


@market_scanner_bp.post("/categories/refresh")
@live_endpoint
def refresh_categories():
    from services.market_scanner_live import coordinator, import_categories

    coordinator().store.categories(import_categories("stock_symbols_CSVs"))
    return jsonify(status="success")
