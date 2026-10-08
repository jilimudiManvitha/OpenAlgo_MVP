"""Real isolated SQL/Flask and mock HTTP tests; never import the production app."""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from flask import Flask, g, jsonify
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]


def production_module(name):
    """Fresh instance of the integrated source, with fixture teardown restoring imports."""
    spec = importlib.util.spec_from_file_location(name, ROOT / (name.replace(".", "/") + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def modules(monkeypatch, tmp_path):
    from database.latency_db import LatencyBase

    originals = {
        name: sys.modules.get(name)
        for name in (
            "services.latency_report",
            "utils.latency_monitor",
            "utils.httpx_client",
            "blueprints.latency",
        )
    }
    report = production_module("services.latency_report")
    monitor = production_module("utils.latency_monitor")
    client = production_module("utils.httpx_client")
    engine = create_engine("sqlite:///" + str(tmp_path / "latency.db"), poolclass=NullPool)
    LatencyBase.metadata.create_all(engine)
    monkeypatch.setattr(report, "latency_engine", engine)
    import database.settings_db as settings

    monkeypatch.setattr(settings, "get_analyze_mode", lambda: False)
    app = Flask(__name__)
    app.secret_key = "test-only"
    yield SimpleNamespace(report=report, monitor=monitor, http=client, engine=engine, app=app)
    monitor._latency_log_executor.shutdown(wait=True)
    engine.dispose()
    for name, original in originals.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def insert(m, rows):
    from database.latency_db import OrderLatency

    with m.engine.begin() as conn:
        for i, row in enumerate(rows):
            conn.execute(
                OrderLatency.__table__.insert().values(
                    order_id=str(i),
                    broker="fyers",
                    timestamp=row.get("timestamp", datetime(2026, 10, 8, 5)),
                    order_type=row.get("operation", "PLACE"),
                    total_latency_ms=row.get("total", 100),
                    rtt_ms=9,
                    overhead_ms=91,
                    status=row.get("status", "SUCCESS"),
                    error=row.get("error"),
                    request_body=row.get("body"),
                )
            )


def snap(m, **kw):
    return m.report.snapshot(
        m.report.filters({"period": "all", **kw}), datetime(2026, 10, 8, 12, tzinfo=UTC)
    )


def test_orders_and_legacy_aliases_exclude_reads_and_fast_failures(modules):
    m = modules
    insert(
        m,
        [
            {"operation": "PLACE", "total": 600},
            {"operation": "OPTIONSMULTIORDER", "total": 2, "status": "FAILED"},
            {"operation": "HISTORY", "total": 10},
            {"operation": "POSITIONBOOK", "total": 5},
        ],
    )
    a = snap(m)
    assert a["sample_count"] == 2
    assert a["stats"]["success_rate"] == 50
    assert a["stats"]["avg_ms"] == 600
    assert a["stats"]["fast_pct"] == 0
    assert a["stats"]["distribution"] == {"excellent": 0, "good": 0, "acceptable": 0, "slow": 1}
    assert a["brokers"]["fyers"]["total"] == 2
    assert snap(m, kind="data")["sample_count"] == 2


def test_one_snapshot_distribution_is_not_recent_100(modules):
    m = modules
    insert(m, [{"total": 100}] * 105 + [{"total": 800}] * 20)
    a = snap(m)
    assert a["stats"]["distribution"]["excellent"] == 105
    assert a["stats"]["distribution"]["slow"] == 20
    assert a["stats"]["fast_pct"] == 84
    assert a["brokers"]["fyers"]["fast_pct"] == 84


def test_boundaries_empty_percentiles_and_partial(modules):
    m = modules
    insert(
        m,
        [{"total": v} for v in (149, 150, 249, 250, 399, 400)]
        + [{"total": 1, "status": "PARTIAL"}],
    )
    a = snap(m)["stats"]
    assert a["distribution"] == {"excellent": 1, "good": 2, "acceptable": 2, "slow": 1}
    assert a["partial"] == 1 and a["successful"] == 6
    assert a["p50_ms"] == 249.5
    assert snap(m, broker="missing")["stats"]["avg_ms"] is None


def test_filters_mode_legacy_and_ist_midnight(modules):
    m = modules
    insert(
        m,
        [
            {"timestamp": datetime(2026, 10, 7, 18, 29)},
            {
                "timestamp": datetime(2026, 10, 7, 18, 30),
                "body": {"latency_meta": {"version": 2, "mode": "sandbox", "http_calls": 1}},
            },
            {
                "timestamp": datetime(2026, 10, 8, 3),
                "body": {"latency_meta": {"version": 2, "mode": "live", "http_calls": 2}},
            },
        ],
    )
    assert snap(m, period="today")["sample_count"] == 2
    assert snap(m, mode="sandbox")["sample_count"] == 1
    assert snap(m, mode="unknown")["sample_count"] == 1
    assert snap(m, mode="live")["logs"][0]["http_ms"] == 9
    assert snap(m, mode="unknown")["logs"][0]["http_ms"] is None
    for bad in ({"kind": "bad"}, {"period": "forever"}, {"status": "xxx"}, {"broker": "x;sql"}):
        with pytest.raises(ValueError):
            m.report.filters(bad)


def test_capped_snapshot_single_query_disclosed(modules, monkeypatch):
    m = modules
    insert(m, [{"total": 100}] * 6)
    monkeypatch.setattr(m.report, "MAX_ROWS", 3)
    statements = []
    event.listen(
        m.engine, "before_cursor_execute", lambda c, cu, s, p, ctx, many: statements.append(s)
    )
    a = snap(m)
    assert a["truncated"] and a["matched_count"] == 6 and a["sample_count"] == 3
    assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT")


def test_http_multiple_calls_accumulate_and_helper_does_not_double_count(modules, monkeypatch):
    m = modules
    records = []
    monkeypatch.setattr(m.monitor, "_submit_log", lambda *a: records.append(a))
    clock = iter([1.0, 1.01, 1.03, 1.04, 1.07, 1.1])
    monkeypatch.setattr(m.monitor, "_clock", lambda: next(clock))
    monkeypatch.setattr(m.http, "_clock", lambda: next(clock))
    client = m.http.TimedClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": 1}))
    )
    monkeypatch.setattr(m.http, "_httpx_client", client)

    @m.monitor.track_latency("PLACE")
    def endpoint():
        m.http.get("https://broker.test/one")
        client.get("https://broker.test/two")
        return {"status": "success", "orderid": "X", "mode": "analyze"}, 200

    with m.app.test_request_context("/test", json={"apikey": "secret", "symbol": "SBIN"}):
        endpoint()
        assert not hasattr(g, "latency_tracker")
    client.close()
    assert records[0][5]["rtt"] == pytest.approx(50)
    assert records[0][5]["total"] == pytest.approx(100)
    assert records[0][5]["overhead"] == pytest.approx(50)
    assert records[0][-1] == {"version": 2, "mode": "sandbox", "http_calls": 2}


def test_local_fast_error_not_broker_confirmation_nested_and_exception(modules, monkeypatch):
    m = modules
    records = []
    monkeypatch.setattr(m.monitor, "_submit_log", lambda *a: records.append(a))

    @m.monitor.track_latency("HISTORY")
    def inner():
        return jsonify(status="error", message="Invalid API key"), 200

    @m.monitor.track_latency("PLACE")
    def outer():
        return inner()

    with m.app.test_request_context("/test", json=[]):
        outer()
    assert len(records) == 1 and records[0][6] == "FAILED"
    assert records[0][5]["rtt"] == 0

    @m.monitor.track_latency("PLACE")
    def boom():
        raise ValueError("original exception")

    with m.app.test_request_context("/test", json={}):
        with pytest.raises(ValueError, match="original exception"):
            boom()
        assert not hasattr(g, "latency_tracker")
    assert records[-1][6] == "FAILED"


def test_failed_http_attempt_is_measured(modules, monkeypatch):
    m = modules
    records = []
    monkeypatch.setattr(m.monitor, "_submit_log", lambda *a: records.append(a))

    def transport(r):
        raise httpx.ReadTimeout("timeout", request=r)

    with m.http.TimedClient(transport=httpx.MockTransport(transport)) as client:

        @m.monitor.track_latency("HISTORY")
        def endpoint():
            return client.get("https://broker.test/test")

        with m.app.test_request_context("/test", json={}):
            with pytest.raises(httpx.ReadTimeout):
                endpoint()
    assert records[0][-1]["http_calls"] == 1 and records[0][5]["rtt"] >= 0


def test_logging_saturation_or_shutdown_does_not_change_response(modules, monkeypatch):
    from threading import BoundedSemaphore

    m = modules
    slot = BoundedSemaphore(1)
    slot.acquire()
    monkeypatch.setattr(m.monitor, "_pending_slots", slot)

    @m.monitor.track_latency("PLACE")
    def endpoint():
        return {"status": "success", "orderid": "keep"}, 200

    with m.app.test_request_context("/test", json={}):
        assert endpoint()[0]["orderid"] == "keep"
    assert m.monitor._dropped_logs == 1
    slot.release()
    m.monitor._latency_log_executor.shutdown(wait=True)
    with m.app.test_request_context("/test", json={}):
        assert endpoint()[0]["orderid"] == "keep"
    assert slot.acquire(blocking=False)


def test_real_flask_csv_and_auth_filters(modules, monkeypatch):
    m = modules
    import utils.session as auth

    monkeypatch.setattr(auth, "is_session_valid", lambda: True)
    blueprint = production_module("blueprints.latency")
    monkeypatch.setattr(
        blueprint, "snapshot", lambda f: m.report.snapshot(f, datetime(2026, 10, 8, 12, tzinfo=UTC))
    )
    m.app.register_blueprint(blueprint.latency_bp)
    insert(
        m,
        [
            {"operation": "PLACE", "total": 500, "error": "=FORMULA", "status": "FAILED"},
            {"operation": "HISTORY", "total": 100},
        ],
    )
    c = m.app.test_client()
    r = c.get("/latency/api/dashboard?kind=data&period=all")
    assert r.status_code == 200 and r.json["stats"]["total"] == 1
    assert len(r.json["recent"]) == 1 and "logs" not in r.json
    r = c.get("/latency/export?period=all")
    assert r.status_code == 200 and "'=FORMULA" in r.text and "HISTORY" not in r.text
    assert c.get("/latency/api/dashboard?kind=invalid").status_code == 400
    assert c.get("/latency/api/logs?limit=-1").status_code == 400
    monkeypatch.setattr(auth, "is_session_valid", lambda: False)
    monkeypatch.setattr(auth, "revoke_user_tokens", lambda: None)
    assert (
        c.get("/latency/api/dashboard", headers={"Accept": "application/json"}).status_code == 401
    )
