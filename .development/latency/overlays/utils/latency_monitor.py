import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from threading import BoundedSemaphore
from time import perf_counter as _clock

from flask import g, request
from flask_restx import Resource

from database.auth_db import db_session as auth_db_session
from database.auth_db import get_broker_name
from database.latency_db import OrderLatency, init_latency_db, latency_session, purge_old_data_logs
from utils.logging import get_logger

logger = get_logger(__name__)

# Shared single-worker executor: the latency record commit (SQLite fsync) runs
# off the request thread so it never delays the order response. One worker
# keeps writes serialized and bounds the scoped sessions to a single
# long-lived thread.
_latency_log_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="latency-log")
_pending_slots = BoundedSemaphore(512)
_dropped_logs = 0


def _submit_log(*args):
    """Telemetry saturation/failure must never block or change an order result."""
    global _dropped_logs
    if not _pending_slots.acquire(blocking=False):
        _dropped_logs += 1
        if _dropped_logs == 1 or _dropped_logs % 100 == 0:
            logger.warning("Latency telemetry queue full; dropped %s records", _dropped_logs)
        return

    def persist():
        try:
            _log_latency_async(*args)
        finally:
            _pending_slots.release()

    try:
        _latency_log_executor.submit(persist)
    except Exception:
        _pending_slots.release()
        logger.exception("Latency telemetry unavailable; response preserved")


#: Latency records of these types are kept forever; everything else is a data
#: query and is purged after a week. Must stay in step with the set in
#: ``database.latency_db.purge_old_data_logs``, which does the deleting -- a
#: type here but missing there is purged despite being an order.
#:
#: A GTT is an order instruction, not a data query. It can also rest for a year
#: before firing, so purging its placement latency after a week would discard
#: the record long before the order it describes exists.
KEEP_FOREVER_TYPES = frozenset(
    {
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
    }
)


def _log_latency_async(
    api_key,
    order_id,
    user_id,
    symbol,
    order_type,
    latencies,
    status,
    error,
    broker=None,
    metadata=None,
):
    """Resolve broker name and persist the latency record. Runs on the executor thread.

    ``broker`` is resolved by the caller when the request carried no API key --
    session-authenticated UI routes (the scalping terminal, the Positions close
    buttons) authenticate by cookie and send none, and the Flask session is not
    readable from this thread.
    """
    try:
        broker_name = broker or (get_broker_name(api_key) if api_key else None)
        OrderLatency.log_latency(
            order_id=order_id,
            user_id=user_id,
            broker=broker_name,
            symbol=symbol,
            order_type=order_type,
            latencies=latencies,
            request_body={"latency_meta": metadata} if metadata else None,
            response_body=None,  # Not storing to save database space
            status=status,
            error=error,
        )
    except Exception as e:
        logger.exception(f"Error logging latency asynchronously: {e}")
    finally:
        # Both sessions must be removed on this thread: an unremoved scoped
        # session keeps its read transaction (and SQLite lock) open.
        latency_session.remove()
        auth_db_session.remove()


def _response_payload(response):
    """The JSON body of a view's return value, as a dict.

    Flask views may return any of these, and all of them turn up here:

      - ``make_response(jsonify(d), code)`` -> a Response          (RESTX)
      - ``jsonify(d), code``                -> (Response, int)  (blueprints)
      - ``d, code``                         -> (dict, int)
      - ``send_file(...)``                  -> a Response with no JSON body

    Only the first and third were understood before, so blueprint routes -- the
    scalping terminal's order endpoints and the Positions close buttons -- had
    their payload read as ``{}`` and every record logged an order id of "unknown".
    A file download has a ``.json`` property that resolves to None rather than
    raising, so it still falls through to ``{}``.
    """
    if isinstance(response, tuple):
        response = response[0] if response else None

    if isinstance(response, dict):
        return response

    payload = getattr(response, "json", None)
    return payload if isinstance(payload, dict) else {}


def _session_broker():
    """The logged-in broker, for requests that carry no API key.

    Session-authenticated UI routes have no ``apikey`` in the body, so the record
    would otherwise land with an empty broker and never group under the broker it
    was actually sent to. Read here, on the request thread -- the executor thread
    that writes the record has no session.
    """
    try:
        from flask import session

        return session.get("broker")
    except Exception:  # outside a request context, or no session configured
        return None


class LatencyTracker:
    """Request-local monotonic timing. Sequential HTTP sends accumulate."""

    def __init__(self):
        self.start_time = _clock()
        self.http_seconds = 0.0
        self.http_calls = 0
        self.stage_times = {}
        self.current_stage = None
        self.stage_start = None

    def start_stage(self, stage_name):
        self.current_stage, self.stage_start = stage_name, _clock()

    def end_stage(self):
        if self.current_stage is not None:
            self.stage_times[self.current_stage] = (
                self.stage_times.get(self.current_stage, 0) + (_clock() - self.stage_start) * 1000
            )
            self.current_stage = self.stage_start = None

    def record_http(self, start, end):
        self.http_seconds += max(0, end - start)
        self.http_calls += 1

    def get_total_time(self):
        return max(0, (_clock() - self.start_time) * 1000)

    def get_rtt(self):
        return self.http_seconds * 1000

    def get_overhead(self):
        return max(0, self.get_total_time() - self.get_rtt())


def track_latency(api_type):
    """Measure endpoint completion; response success does not imply exchange fill."""

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Nested instrumentation belongs to the outer API request.
            if getattr(g, "latency_tracker", None) is not None:
                return f(*args, **kwargs)
            tracker = LatencyTracker()
            g.latency_tracker = tracker
            request_data, payload, error = {}, {}, None
            status, mode = "FAILED", "unknown"
            try:
                raw = request.get_json(silent=True) if request.is_json else {}
                request_data = raw if isinstance(raw, dict) else {}
                try:
                    from database.settings_db import get_analyze_mode

                    mode = "sandbox" if get_analyze_mode() else "live"
                except Exception:
                    mode = "unknown"
                response = f(*args, **kwargs)
                payload = _response_payload(response)
                code = (
                    response[1]
                    if isinstance(response, tuple)
                    and len(response) > 1
                    and isinstance(response[1], int)
                    else getattr(
                        response[0] if isinstance(response, tuple) else response, "status_code", 200
                    )
                )
                outcome = str(payload.get("status", "")).lower()
                status = (
                    "FAILED"
                    if code >= 400 or outcome in ("error", "failed", "failure")
                    else "PARTIAL"
                    if outcome == "partial"
                    else "SUCCESS"
                )
                error = payload.get("message") if status != "SUCCESS" else None
                mode = {
                    "analyze": "sandbox",
                    "paper": "sandbox",
                    "sandbox": "sandbox",
                    "live": "live",
                }.get(str(payload.get("mode", "")).lower(), mode)
                return response
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                total = tracker.get_total_time()
                http = min(total, tracker.get_rtt())
                # No request/response bodies or credentials are persisted.
                metadata = {"version": 2, "mode": mode, "http_calls": tracker.http_calls}
                try:
                    _submit_log(
                        request_data.get("apikey"),
                        payload.get("orderid") or payload.get("request_id") or "unknown",
                        g.get("user_id"),
                        request_data.get("symbol"),
                        api_type,
                        {
                            "rtt": http,
                            "validation": 0,
                            "broker_response": 0,
                            "overhead": max(0, total - http),
                            "total": total,
                        },
                        status,
                        error,
                        _session_broker() if not request_data.get("apikey") else None,
                        metadata,
                    )
                finally:
                    g.pop("latency_tracker", None)

        return wrapped

    return decorator


def wrap_resource_methods(resource_class, api_type):
    """Helper function to wrap all methods of a Resource class with latency tracking"""
    for method in ["get", "post", "put", "delete", "patch"]:
        if hasattr(resource_class, method):
            original_method = getattr(resource_class, method)
            if isinstance(original_method, (classmethod, staticmethod)):
                original_method = original_method.__get__(None, resource_class)
            setattr(resource_class, method, track_latency(api_type)(original_method))


def init_latency_monitoring(app):
    """Initialize latency monitoring"""
    # Initialize the latency database
    init_latency_db()

    # Auto-purge old data endpoint logs (keep order logs forever, purge data logs after 7 days)
    purge_old_data_logs(days=7)

    # Import all RESTX API resources
    from restx_api import api

    # Map of endpoint names to their types
    # ORDER endpoints: Keep latency logs forever
    # DATA endpoints: Auto-purge after 7 days
    api_types = {
        # Order execution endpoints (keep forever)
        "place_order": "PLACE",
        "place_smart_order": "SMART",
        "modify_order": "MODIFY",
        "cancel_order": "CANCEL",
        "close_position": "CLOSE",
        "cancel_all_order": "CANCEL_ALL",
        "basket_order": "BASKET",
        "split_order": "SPLIT",
        "options_order": "OPTIONS",
        "options_multiorder": "OPTIONS_MULTI",
        # GTT. These were already being wrapped - an unmapped namespace falls
        # back to its uppercased name - but as PLACE_GTT_ORDER etc, which does
        # not match the ORDER_TYPES set below, so GTT latency was being purged
        # after 7 days as though it were a data query.
        "place_gtt_order": "GTT_PLACE",
        "modify_gtt_order": "GTT_MODIFY",
        "cancel_gtt_order": "GTT_CANCEL",
        # Data/Account endpoints (auto-purge after 7 days)
        "quotes": "QUOTES",
        "history": "HISTORY",
        "depth": "DEPTH",
        "intervals": "INTERVALS",
        "funds": "FUNDS",
        "orderbook": "ORDERBOOK",
        "tradebook": "TRADEBOOK",
        "positionbook": "POSITIONBOOK",
        "holdings": "HOLDINGS",
        "orderstatus": "STATUS",
        "openposition": "POSITION",
        "instruments": "INSTRUMENTS",
        "search": "SEARCH",
        "symbol": "SYMBOL",
        "expiry": "EXPIRY",
        "margin": "MARGIN",
        "option_greeks": "GREEKS",
        "multi_option_greeks": "MULTI_GREEKS",
        "option_symbol": "OPTION_SYMBOL",
        "synthetic_future": "SYNTHETIC",
        "ticker": "TICKER",
        "ping": "PING",
        "analyzer": "ANALYZER",
        "chart": "CHART",
        "market/holidays": "MARKET_HOLIDAYS",
        "market/timings": "MARKET_TIMINGS",
    }

    # Wrap all API endpoints with latency tracking
    for namespace in api.namespaces:
        api_type = api_types.get(namespace.name, namespace.name.upper())
        api_type = {
            "OPTIONSORDER": "OPTIONS",
            "OPTIONSMULTIORDER": "OPTIONS_MULTI",
            "PLACE_GTT_ORDER": "GTT_PLACE",
            "MODIFY_GTT_ORDER": "GTT_MODIFY",
            "CANCEL_GTT_ORDER": "GTT_CANCEL",
        }.get(api_type, api_type)

        # Get all resources in the namespace
        for resource in namespace.resources:
            # Get the actual resource class
            resource_class = resource.resource

            # Wrap all methods of the resource
            wrap_resource_methods(resource_class, api_type)
