"""Offline contract tests; no broker calls, production DB writes or app startup."""

from copy import deepcopy
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
from flask import Flask

from broker.fyers.api import data as http_data
from broker.fyers.api import expired_data as provider
from services import expired_data_service as service

AUTH = {"auth_token": "test-token", "broker": "fyers"}
SYMBOL = "NSE:SBIN25MAR320CE"
HISTORY = {
    "broker_symbol": SYMBOL,
    "interval": "1m",
    "start_date": "2025-03-01",
    "end_date": "2025-03-27",
}
DISCOVERY = {"broker_symbol": "NSE:SBIN-EQ", "start_date": "2025-01-01", "end_date": "2025-03-31"}
CONTRACTS = {"broker_symbol": "NSE:SBIN-EQ", "expiry_date": "2025-03-27"}


def candle(day="2025-03-27", oi=True):
    stamp = int(
        datetime.fromisoformat(day + "T09:15:00")
        .replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        .timestamp()
    )
    return [stamp, 100, 102, 99, 101, 1000] + ([5678] if oi else [])


def history_response(day="2025-03-27", oi=True):
    return {
        "s": "ok",
        "symbol": SYMBOL,
        "resolution": "1",
        "schema_version": 1,
        "columns": provider.BASE_COLUMNS + (["open_interest"] if oi else []),
        "candles": [candle(day, oi)],
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(
        provider, "get_api_response", lambda *a, **kw: pytest.fail("unexpected HTTP")
    )


def fake_api(monkeypatch, response):
    calls = []

    def request(endpoint, auth, **kwargs):
        calls.append((urlsplit(endpoint).path, parse_qs(urlsplit(endpoint).query), auth, kwargs))
        return deepcopy(response)

    monkeypatch.setattr(provider, "get_api_response", request)
    return calls


def test_expiry_discovery_uses_new_endpoint_and_separates_instruments(monkeypatch):
    calls = fake_api(
        monkeypatch,
        {
            "s": "ok",
            "data": {
                "expiry_dates": {"futures": ["2025-03-27", "2025-01-30"], "options": ["2025-01-30"]}
            },
        },
    )
    success, body, status = service.get_expired_data("expiry-dates", DISCOVERY, **AUTH)
    assert success and status == 200
    assert body["data"]["expiry_dates"] == {
        "futures": ["2025-01-30", "2025-03-27"],
        "options": ["2025-01-30"],
    }
    assert calls == [
        (
            provider.BASE + "expiry-dates",
            {
                "symbol": ["NSE:SBIN-EQ"],
                "range_from": ["2025-01-01"],
                "range_to": ["2025-03-31"],
                "date_format": ["1"],
            },
            "test-token",
            {"retry_429": False},
        )
    ]


def test_contract_discovery_keeps_exact_broker_identifiers(monkeypatch):
    values = {"futures": ["NSE:SBIN25MARFUT"], "options": [SYMBOL]}
    calls = fake_api(
        monkeypatch, {"s": "ok", "data": {"expiry_date": "2025-03-27", "contracts": values}}
    )
    success, body, status = service.get_expired_data("contracts", CONTRACTS, **AUTH)
    assert success and status == 200 and body["data"]["contracts"] == values
    assert calls[0][0] == provider.BASE + "underlying-symbols"
    assert calls[0][1] == {"symbol": ["NSE:SBIN-EQ"], "expiry_date": ["2025-03-27"]}


def test_history_does_not_consult_current_master_preserves_oi_and_epoch(monkeypatch):
    monkeypatch.setattr(
        provider, "get_br_symbol", lambda *a: pytest.fail("expired symbol master lookup")
    )
    calls = fake_api(monkeypatch, history_response())
    success, body, status = service.get_expired_data("history", HISTORY, **AUTH)
    assert success and status == 200
    assert body["data"]["candles"] == [
        dict(zip(provider.BASE_COLUMNS + ["oi"], candle(), strict=True))
    ]
    assert calls[0][0] == provider.BASE + "historical-data"
    assert calls[0][1]["include_oi"] == ["1"]
    assert "cont_flag" not in calls[0][1] and "oi_flag" not in calls[0][1]
    assert "include_greeks" not in calls[0][1]


def test_oi_disabled_is_explicit_and_normalizes_to_zero(monkeypatch):
    calls = fake_api(monkeypatch, history_response(oi=False))
    _, body, status = service.get_expired_data("history", {**HISTORY, "include_oi": False}, **AUTH)
    assert status == 200 and body["data"]["candles"][0]["oi"] == 0
    assert body["data"]["oi_included"] is False
    assert calls[0][1]["include_oi"] == ["0"]


def test_common_underlying_symbol_resolves_and_releases_db_session(monkeypatch):
    calls, cleanup = [], []
    monkeypatch.setattr(
        provider, "get_br_symbol", lambda *args: calls.append(args) or "NSE:NIFTY50-INDEX"
    )
    monkeypatch.setattr(provider.symbol_session, "remove", lambda: cleanup.append(True))
    fake_api(monkeypatch, {"s": "ok", "data": {"expiry_dates": {"futures": [], "options": []}}})
    payload = {k: v for k, v in DISCOVERY.items() if k != "broker_symbol"}
    result = service.get_expired_data(
        "expiry-dates", {**payload, "symbol": "NIFTY", "exchange": "NSE_INDEX"}, **AUTH
    )
    assert result[2] == 200 and calls == [("NIFTY", "NSE_INDEX")] and cleanup == [True]


@pytest.mark.parametrize("fails", [False, True])
def test_underlying_lookup_cleanup_on_missing_or_exception(monkeypatch, fails):
    cleanup = []

    def lookup(*args):
        if fails:
            raise RuntimeError("lookup failed")
        return None

    monkeypatch.setattr(provider, "get_br_symbol", lookup)
    monkeypatch.setattr(provider.symbol_session, "remove", lambda: cleanup.append(True))
    payload = {"symbol": "MISSING", "exchange": "NSE", "expiry_date": "2025-03-27"}
    assert service.get_expired_data("contracts", payload, **AUTH)[2] == (500 if fails else 400)
    assert cleanup == [True]


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("history", {**HISTORY, "start_date": "2025-03-28"}),
        ("history", {**HISTORY, "start_date": "2025-02-30"}),
        ("history", {**HISTORY, "interval": "D"}),
        ("history", {**HISTORY, "interval": "10s"}),
        ("history", {**HISTORY, "include_greeks": True}),
        ("history", {**HISTORY, "broker_symbol": "NSE:SBIN-EQ"}),
        ("history", {**HISTORY, "broker_symbol": "NSE:SBIN25MAR320CE&include_oi=0"}),
        (
            "history",
            {
                **HISTORY,
                "broker_symbol": "BSE:SENSEX23JUL60000CE",
                "start_date": "2023-07-01",
                "end_date": "2023-07-20",
            },
        ),
        ("history", {**HISTORY, "interval": "5s", "start_date": "2025-02-01"}),
        ("history", {**HISTORY, "end_date": "2999-01-01"}),
        ("history", {**HISTORY, "symbol": "SBIN"}),
        ("history", {**HISTORY, "start_date": "2023-01-01"}),
        ("expiry-dates", {**DISCOVERY, "symbol": "SBIN", "exchange": "NSE"}),
        ("expiry-dates", {"symbol": "SBIN", "start_date": "2025-01-01", "end_date": "2025-01-31"}),
        ("expiry-dates", {**DISCOVERY, "start_date": "2018-10-09"}),
        ("contracts", {**CONTRACTS, "expiry_date": "2999-01-01"}),
        (
            "contracts",
            {**CONTRACTS, "expiry_date": datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()},
        ),
    ],
)
def test_invalid_requests_fail_before_http(operation, payload):
    assert service.get_expired_data(operation, payload, **AUTH)[2] == 400


def test_366_day_expiry_boundary_and_367_rejection(monkeypatch):
    fake_api(monkeypatch, {"s": "ok", "data": {"expiry_dates": {"futures": [], "options": []}}})
    payload = {**DISCOVERY, "start_date": "2024-01-01", "end_date": "2024-12-31"}
    assert service.get_expired_data("expiry-dates", payload, **AUTH)[2] == 200
    assert (
        service.get_expired_data("expiry-dates", {**payload, "end_date": "2025-01-01"}, **AUTH)[2]
        == 400
    )


@pytest.mark.parametrize("interval,resolution", provider.RESOLUTIONS.items())
def test_supported_resolutions(monkeypatch, interval, resolution):
    response = history_response()
    response["resolution"] = resolution
    calls = fake_api(monkeypatch, response)
    assert service.get_expired_data("history", {**HISTORY, "interval": interval}, **AUTH)[2] == 200
    assert calls[0][1]["resolution"] == [resolution]


def test_history_windows_are_inclusive_nonoverlapping_and_bounded(monkeypatch):
    ranges = []

    def request(endpoint, *args, **kwargs):
        query = parse_qs(urlsplit(endpoint).query)
        start, end = query["range_from"][0], query["range_to"][0]
        ranges.append((start, end))
        return history_response(start)

    monkeypatch.setattr(provider, "get_api_response", request)
    _, body, status = service.get_expired_data(
        "history", {**HISTORY, "start_date": "2024-01-01", "end_date": "2024-12-31"}, **AUTH
    )
    assert status == 200 and len(body["data"]["candles"]) == 4
    assert ranges == [
        ("2024-01-01", "2024-04-09"),
        ("2024-04-10", "2024-07-18"),
        ("2024-07-19", "2024-10-26"),
        ("2024-10-27", "2024-12-31"),
    ]


def test_failure_on_later_window_never_returns_partial_success(monkeypatch):
    calls = []

    def request(endpoint, *args, **kwargs):
        calls.append(endpoint)
        if len(calls) == 1:
            return history_response("2024-01-01")
        return {"s": "error", "code": 503, "message": "unavailable"}

    monkeypatch.setattr(provider, "get_api_response", request)
    ok, body, status = service.get_expired_data(
        "history", {**HISTORY, "start_date": "2024-01-01", "end_date": "2024-12-31"}, **AUTH
    )
    assert not ok and status == 502 and "data" not in body and len(calls) == 2


def test_no_data_is_distinct_and_empty_ranges_are_visible(monkeypatch):
    fake_api(monkeypatch, {"s": "no_data", "candles": []})
    ok, body, status = service.get_expired_data("history", HISTORY, **AUTH)
    assert ok and status == 200 and body["data"]["data_status"] == "no_data"
    assert body["data"]["candles"] == []
    assert body["data"]["empty_ranges"] == [{"start_date": "2025-03-01", "end_date": "2025-03-27"}]


@pytest.mark.parametrize(
    "code,status", [(-16, 401), (401, 401), (-300, 400), (429, 429), (503, 502)]
)
def test_broker_errors_keep_their_meaning(monkeypatch, code, status):
    calls = fake_api(
        monkeypatch, {"s": "error", "code": code, "message": "failed", "retry_after": 65}
    )
    ok, body, result_status = service.get_expired_data("history", HISTORY, **AUTH)
    assert not ok and result_status == status and body["code"] == code and len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"columns": []},
        {"columns": provider.BASE_COLUMNS},
        {"schema_version": 2},
        {"symbol": "NSE:WRONG25MARFUT"},
        {"resolution": "5"},
        {"candles": None},
        {"candles": [[1, 2]]},
        {"candles": [candle("2025-02-28")]},
        {"candles": [[candle()[0], float("nan"), 102, 99, 101, 1000, 5678]]},
        {"candles": [[candle()[0], 100, 98, 99, 101, 1000, 5678]]},
        {"s": "no_data", "candles": [candle()]},
    ],
)
def test_malformed_candles_cannot_be_reported_as_success(monkeypatch, change):
    fake_api(monkeypatch, {**history_response(), **change})
    assert service.get_expired_data("history", HISTORY, **AUTH)[2] == 502


def test_identical_duplicates_collapse_conflicts_fail(monkeypatch):
    response = history_response()
    response["candles"] *= 2
    fake_api(monkeypatch, response)
    assert len(service.get_expired_data("history", HISTORY, **AUTH)[1]["data"]["candles"]) == 1
    response["candles"] = [candle(), candle()]
    response["candles"][1][4] = 100
    fake_api(monkeypatch, response)
    assert service.get_expired_data("history", HISTORY, **AUTH)[2] == 502


def test_auth_required_and_unsupported_broker_is_501():
    assert service.get_expired_data("history", HISTORY)[2] == 403
    assert (
        service.get_expired_data("history", HISTORY, auth_token="test", broker="zerodha")[2] == 501
    )


@pytest.mark.parametrize("raises", [False, True])
def test_api_auth_releases_session_even_on_failure(monkeypatch, raises):
    removed = []

    def auth(key):
        assert key == "invalid"
        if raises:
            raise RuntimeError("lookup failure")
        return None, None

    monkeypatch.setattr(service, "get_auth_token_broker", auth)
    monkeypatch.setattr(service.db_session, "remove", lambda: removed.append(True))
    assert service.get_expired_data("history", HISTORY, api_key="invalid", **AUTH)[2] == (
        500 if raises else 403
    )
    assert removed == [True]


@pytest.fixture
def client(monkeypatch):
    from restx_api import api_v1_bp

    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(api_v1_bp)
    monkeypatch.setattr(
        service,
        "get_auth_token_broker",
        lambda key: ("test-token", "fyers") if key == "valid" else (None, None),
    )
    return app.test_client()


def test_registered_http_workflow(client, monkeypatch):
    fake_api(
        monkeypatch,
        {
            "s": "ok",
            "data": {"expiry_dates": {"futures": ["2025-03-27"], "options": ["2025-03-27"]}},
        },
    )
    dates = client.post("/api/v1/expired/expiry-dates", json={"apikey": "valid", **DISCOVERY})
    assert dates.status_code == 200
    expiry = dates.json["data"]["expiry_dates"]["options"][0]
    fake_api(
        monkeypatch,
        {
            "s": "ok",
            "data": {"expiry_date": expiry, "contracts": {"futures": [], "options": [SYMBOL]}},
        },
    )
    contracts = client.post(
        "/api/v1/expired/contracts",
        json={"apikey": "valid", "broker_symbol": "NSE:SBIN-EQ", "expiry_date": expiry},
    )
    assert contracts.status_code == 200
    fake_api(monkeypatch, history_response())
    result = client.post(
        "/api/v1/expired/history",
        json={
            "apikey": "valid",
            **HISTORY,
            "broker_symbol": contracts.json["data"]["contracts"]["options"][0],
        },
    )
    assert result.status_code == 200 and result.json["data"]["candles"][0]["oi"] == 5678
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "payload,status",
    [
        (None, 400),
        ([], 400),
        ({}, 400),
        ({"apikey": "bad", **HISTORY}, 403),
        ({"apikey": "valid", **HISTORY, "interval": "D"}, 400),
    ],
)
def test_http_invalid_payloads_and_auth(client, payload, status):
    assert client.post("/api/v1/expired/history", json=payload).status_code == status


def test_http_rate_limit_retry_after_header(client, monkeypatch):
    fake_api(monkeypatch, {"s": "error", "code": 429, "retry_after": 61.2})
    result = client.post("/api/v1/expired/history", json={"apikey": "valid", **HISTORY})
    assert result.status_code == 429 and result.headers["Retry-After"] == "62"


def test_expired_http_uses_shared_client_timeout_and_history_budget(monkeypatch):
    calls, budgets = [], []

    class Client:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(200, json={"s": "no_data"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(http_data, "get_httpx_client", lambda: Client())
    monkeypatch.setattr(http_data, "apply_rate_limit", lambda **kwargs: budgets.append(kwargs))
    monkeypatch.setenv("BROKER_API_KEY", "test-client")
    result = http_data.get_api_response(
        provider.BASE + "historical-data?symbol=test", "test-token", retry_429=False
    )
    assert result["s"] == "no_data" and budgets == [{"history": True}]
    assert calls[0][1]["timeout"] == 30.0
    assert calls[0][1]["headers"]["Authorization"] == "test-client:test-token"


@pytest.mark.parametrize(
    "response",
    [
        {"s": "ok", "data": {"expiry_dates": {"futures": None, "options": []}}},
        {"s": "ok", "data": {"expiry_dates": {"futures": ["2025-02-30"], "options": []}}},
        {"s": "ok", "data": {"expiry_dates": {"futures": ["2026-02-28"], "options": []}}},
        {"s": "no_data"},
    ],
)
def test_invalid_discovery_is_not_an_empty_success(monkeypatch, response):
    fake_api(monkeypatch, response)
    assert service.get_expired_data("expiry-dates", DISCOVERY, **AUTH)[2] == 502


@pytest.mark.parametrize(
    "exchange,first", [("NSE", "2018-10-10"), ("BSE", "2023-08-07"), ("MCX", "2018-10-11")]
)
def test_each_exchange_accepts_its_first_available_day(monkeypatch, exchange, first):
    calls = fake_api(
        monkeypatch, {"s": "ok", "data": {"expiry_dates": {"futures": [], "options": []}}}
    )
    payload = {"broker_symbol": f"{exchange}:UNDERLYING", "start_date": first, "end_date": first}
    assert service.get_expired_data("expiry-dates", payload, **AUTH)[2] == 200
    assert calls[0][1]["symbol"] == [f"{exchange}:UNDERLYING"]


@pytest.mark.parametrize(
    "response",
    [
        {
            "s": "ok",
            "data": {"expiry_date": "2025-03-27", "contracts": {"futures": None, "options": []}},
        },
        {
            "s": "ok",
            "data": {
                "expiry_date": "2025-03-27",
                "contracts": {"futures": ["NSE:SBIN-EQ"], "options": []},
            },
        },
        {
            "s": "ok",
            "data": {
                "expiry_date": "2025-03-27",
                "contracts": {"futures": [], "options": ["BSE:WRONG25MAR100CE"]},
            },
        },
        {
            "s": "ok",
            "data": {"expiry_date": "2025-03-26", "contracts": {"futures": [], "options": []}},
        },
    ],
)
def test_invalid_contracts_are_rejected(monkeypatch, response):
    fake_api(monkeypatch, response)
    assert service.get_expired_data("contracts", CONTRACTS, **AUTH)[2] == 502


def test_wrong_symbol_no_data_is_rejected(monkeypatch):
    fake_api(monkeypatch, {"s": "no_data", "symbol": "WRONG", "candles": []})
    assert service.get_expired_data("history", HISTORY, **AUTH)[2] == 502
