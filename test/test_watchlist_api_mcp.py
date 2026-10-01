"""Real temporary DB/Flask/MCP tests for batch watchlist management."""

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from flask import Flask
from sqlalchemy.orm import scoped_session, sessionmaker

from database import watchlist_db as store
from database.engine_factory import create_db_engine
from services import watchlist_service as service
from utils import mcp_tool_registry as registry


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    engine = create_db_engine("sqlite:///" + str(tmp_path / "watchlists.db"))
    store.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(store, "db_session", session)
    monkeypatch.setattr(service, "db_session", session)
    monkeypatch.setattr(
        service, "verify_api_key", lambda key: {"alice-key": "alice", "bob-key": "bob"}.get(key)
    )
    monkeypatch.setattr(
        service,
        "get_tokens_bulk",
        lambda pairs: [None if symbol == "INVALID" else "1" for symbol, _ in pairs],
    )
    yield session
    session.remove()
    engine.dispose()


def call(action, name="Research", **kwargs):
    return service.manage_watchlist({"action": action, "name": name, **kwargs}, api_key="alice-key")


def test_pasted_list_add_remove_same_browser_store(isolated):
    assert call("create")[2] == 200
    ok, body, status = call("add", symbols="sbin, TCS\nNSE:INFY; BSE:RELIANCE SBIN")
    assert ok and status == 200 and body["data"]["changed_items"] == 4
    browser = store.get_watchlists("alice")[0]
    assert [(i["symbol"], i["exchange"]) for i in browser["items"]] == [
        ("SBIN", "NSE"),
        ("TCS", "NSE"),
        ("INFY", "NSE"),
        ("RELIANCE", "BSE"),
    ]
    _, body, _ = call("add", symbols="SBIN TCS")
    assert body["data"]["changed_items"] == 0
    assert body["data"]["already_present"] == ["NSE:SBIN", "NSE:TCS"]
    _, body, _ = call("remove", symbols="TCS INVALID")
    assert body["data"]["changed_items"] == 1
    assert body["data"]["not_present"] == ["NSE:INVALID"]
    assert [i["symbol"] for i in store.get_watchlists("alice")[0]["items"]] == [
        "SBIN",
        "INFY",
        "RELIANCE",
    ]


def test_unknown_symbols_do_not_create_or_partially_edit(isolated):
    result = call("add", symbols="SBIN INVALID", create_if_missing=True)
    assert result[2] == 400 and result[1]["invalid_symbols"] == ["NSE:INVALID"]
    assert store.get_watchlists("alice") == []
    call("create", symbols="TCS")
    assert call("replace", symbols="SBIN INVALID")[2] == 400
    assert [i["symbol"] for i in store.get_watchlists("alice")[0]["items"]] == ["TCS"]


def test_replace_preserves_ids_reorders_and_clear_is_explicit(isolated):
    _, before, _ = call("create", symbols="SBIN TCS")
    ids = {i["symbol"]: i["id"] for i in before["data"]["items"]}
    _, after, status = call("replace", symbols="TCS SBIN INFY")
    assert status == 200
    assert [i["symbol"] for i in after["data"]["items"]] == ["TCS", "SBIN", "INFY"]
    assert after["data"]["items"][0]["id"] == ids["TCS"]
    assert call("add", symbols="")[2] == 400
    assert call("remove", symbols="")[2] == 400
    assert call("replace", symbols="")[1]["data"]["items"] == []


def test_names_and_ownership_are_enforced(isolated):
    assert call("create")[2] == 200
    assert call("create")[2] == 409
    for action in ("get", "add", "remove", "delete", "rename", "replace"):
        payload = {"action": action, "name": "Research"}
        if action in ("add", "remove", "replace"):
            payload["symbols"] = "SBIN"
        if action == "rename":
            payload["new_name"] = "stolen"
        assert service.manage_watchlist(payload, api_key="bob-key")[2] == 404
    assert call("rename", new_name="Thursday")[2] == 200
    assert call("get")[2] == 404
    assert call("delete", name="Thursday")[2] == 200
    assert store.get_watchlists("alice") == []


def test_api_key_required_and_user_id_cannot_be_supplied(isolated):
    for key in (None, "", "wrong"):
        assert service.manage_watchlist({"action": "list"}, api_key=key)[2] == 403
    assert call("create", user_id="bob")[2] == 400


def test_caps_are_atomic_and_duplicate_add_at_cap_succeeds(isolated, monkeypatch):
    monkeypatch.setattr(service, "MAX_ITEMS_PER_LIST", 2)
    call("create", symbols="SBIN TCS")
    assert call("add", symbols="SBIN")[2] == 200
    assert call("add", symbols="INFY RELIANCE")[2] == 409
    assert len(store.get_watchlists("alice")[0]["items"]) == 2
    monkeypatch.setattr(service, "MAX_LISTS_PER_USER", 1)
    assert call("create", name="Second")[2] == 409


def test_missing_list_creation_requires_explicit_flag(isolated):
    assert call("add", symbols="SBIN")[2] == 404
    assert call("add", symbols="SBIN", create_if_missing=True)[2] == 200


def test_batch_rollback_on_commit_error(isolated, monkeypatch):
    call("create", symbols="SBIN")
    session_type = isolated.session_factory.class_
    original = session_type.commit

    def fail_commit(self):
        self.flush()
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(session_type, "commit", fail_commit)
    assert call("add", symbols="TCS INFY")[2] == 500
    monkeypatch.setattr(session_type, "commit", original)
    assert [i["symbol"] for i in store.get_watchlists("alice")[0]["items"]] == ["SBIN"]


def test_concurrent_clients_preserve_additions(isolated):
    call("create")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda symbol: call("add", symbols=symbol), ["SBIN", "TCS", "INFY", "SBIN"])
        )
    assert all(result[2] == 200 for result in results)
    assert {i["symbol"] for i in store.get_watchlists("alice")[0]["items"]} == {
        "SBIN",
        "TCS",
        "INFY",
    }


@pytest.mark.parametrize(
    "symbols",
    [
        None,
        1,
        [None],
        "NSE:SBIN:EQ",
        "BAD:TCS",
        "SBIN!",
        [{"symbol": "TCS", "user_id": "bob"}],
        ["SBIN"] * 251,
    ],
)
def test_invalid_batches_fail_without_changes(isolated, symbols):
    assert call("create", symbols=symbols)[2] == 400
    assert store.get_watchlists("alice") == []


@pytest.fixture
def client(isolated):
    from restx_api import api_v1_bp

    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(api_v1_bp)
    return app.test_client()


def test_registered_api(client):
    assert client.post("/api/v1/watchlist", json=[]).status_code == 400
    assert client.post("/api/v1/watchlist", json={"action": "list"}).status_code == 400
    response = client.post(
        "/api/v1/watchlist",
        json={
            "apikey": "alice-key",
            "action": "add",
            "name": "Thu",
            "symbols": "SBIN, TCS",
            "create_if_missing": True,
        },
    )
    assert response.status_code == 200 and len(response.json["data"]["items"]) == 2
    assert response.headers["Cache-Control"] == "no-store"
    lists = client.post("/api/v1/watchlist", json={"apikey": "alice-key", "action": "list"}).json[
        "data"
    ]
    assert lists[0]["name"] == "Thu" and lists[0]["item_count"] == 2


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("OPENALGO_MCP_HTTP_BOOT", "1")
    return registry._load_mcpserver_module()


def payload(value):
    return json.loads(value)["data"]


def test_mcp_tools_reach_real_service_and_browser_store(server, client, monkeypatch):
    class SDK:
        def _post(self, endpoint, data):
            return client.post("/api/v1/" + endpoint, json=data).json

    monkeypatch.setattr(server, "client", SDK())
    monkeypatch.setattr(server, "api_key", "alice-key")
    assert payload(server.create_watchlist("MCP", "SBIN TCS"))["status"] == "success"
    assert payload(server.add_watchlist_symbols("MCP", "INFY"))["status"] == "success"
    assert payload(server.remove_watchlist_symbols("MCP", "TCS"))["status"] == "success"
    result = payload(server.get_watchlist("MCP"))
    assert [i["symbol"] for i in result["data"]["items"]] == ["SBIN", "INFY"]
    assert store.get_watchlists("alice")[0]["name"] == "MCP"


def test_watchlist_timeout_verifies_list_not_orders(server, monkeypatch):
    class SDK:
        def _post(self, *args):
            return {"status": "error", "error_type": "timeout_error", "message": "timeout"}

    monkeypatch.setattr(server, "client", SDK())
    error = payload(server.add_watchlist_symbols("Thu", "SBIN"))["error"]
    assert error["verify_with"] == "get_watchlist" and error["retry_safe"] is False


def test_watchlist_write_scope_cannot_trade(server):
    reads = registry.list_tools_for_scopes([registry.SCOPE_READ_ACCOUNT])
    assert "get_watchlist" in reads and "add_watchlist_symbols" not in reads
    writes = registry.list_tools_for_scopes([registry.SCOPE_WRITE_WATCHLISTS])
    assert "add_watchlist_symbols" in writes and "place_order" not in writes
    assert all(not server.TOOL_META[name].read_only for name in writes)


def test_remote_dispatch_requires_watchlist_scope(server, monkeypatch):
    from blueprints import mcp_http

    calls = []
    monkeypatch.setattr(
        registry, "get_tool_callable", lambda name: lambda **kw: calls.append(name) or "{}"
    )
    monkeypatch.setattr(mcp_http, "_within_scope_quota", lambda **kw: True)
    monkeypatch.setattr(mcp_http, "_audit_log", lambda event: None)
    app = Flask(__name__)
    with app.test_request_context("/mcp"):
        for scopes, name, allowed in (
            ([registry.SCOPE_READ_ACCOUNT], "add_watchlist_symbols", False),
            ([registry.SCOPE_WRITE_ORDERS], "add_watchlist_symbols", False),
            ([registry.SCOPE_WRITE_WATCHLISTS], "place_order", False),
            ([registry.SCOPE_WRITE_WATCHLISTS], "add_watchlist_symbols", True),
        ):
            response = mcp_http._dispatch_tool_call(
                rpc_id=1,
                params={"name": name, "arguments": {"name": "Thu", "symbols": "SBIN"}},
                granted_scopes=scopes,
                client_id="test",
                jti="test",
            )
            if isinstance(response, tuple):
                response = response[0]
            assert ("result" in response.get_json()) is allowed
    assert calls == ["add_watchlist_symbols"]


def test_database_sessions_released_on_success_and_failure(isolated, monkeypatch):
    from sqlalchemy import event

    engine = isolated.session_factory.kw["bind"]
    checked_out = set()
    event.listen(engine, "checkout", lambda connection, record, proxy: checked_out.add(id(record)))
    event.listen(engine, "checkin", lambda connection, record: checked_out.discard(id(record)))
    for _ in range(100):
        assert call("add", symbols="SBIN TCS", create_if_missing=True)[2] == 200
        assert call("remove", symbols="TCS")[2] == 200
        assert call("get", name="missing")[2] == 404
        assert not isolated.registry.has() and not checked_out

    def fail_serialize(row):
        raise RuntimeError("simulated response failure")

    monkeypatch.setattr(service, "_serialize", fail_serialize)
    assert call("get")[2] == 500
    assert not isolated.registry.has() and not checked_out


def test_expired_history_mcp_limits_payload(server, monkeypatch):
    class SDK:
        def _post(self, endpoint, data):
            assert endpoint == "expired/history" and data["broker_symbol"] == "NSE:SBIN25MARFUT"
            return {"status": "success", "data": {"candles": [{"timestamp": i} for i in range(5)]}}

    monkeypatch.setattr(server, "client", SDK())
    data = payload(
        server.get_expired_historical_data(
            "NSE:SBIN25MARFUT", "5m", "2025-03-27", "2025-03-27", bars=2
        )
    )["data"]
    assert data["count"] == 5 and data["returned"] == 2 and data["truncated"] is True
    assert data["candles"] == [{"timestamp": 3}, {"timestamp": 4}]
