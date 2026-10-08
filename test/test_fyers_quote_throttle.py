"""Expected FYERS throttling must survive adapter/service/HTTP boundaries."""

import importlib
from unittest.mock import MagicMock

import pytest
from flask import Flask


@pytest.mark.parametrize("kind", ["quotes", "depth"])
@pytest.mark.parametrize("code", [429, -429])
def test_fyers_rate_limit_reaches_service_and_http_with_retry_delay(monkeypatch, kind, code):
    from broker.fyers.api import data

    service = importlib.import_module("services." + kind + "_service")
    endpoint = importlib.import_module("restx_api." + kind)
    monkeypatch.setattr(data, "get_br_symbol", lambda *a: "NSE:SBIN-EQ")
    request = MagicMock(
        return_value={
            "s": "error",
            "code": code,
            "retry_after": 61,
            "message": "FYERS data budget/cooldown active",
        }
    )
    monkeypatch.setattr(data, "get_api_response", request)
    monkeypatch.setattr(service, "validate_symbol_exchange", lambda *a: (True, None))
    monkeypatch.setattr(service, "import_broker_module", lambda *a: data)
    result = getattr(service, "get_" + kind + "_with_auth")("fake", None, "fyers", "SBIN", "NSE")
    assert result == (
        False,
        {
            "status": "error",
            "message": "FYERS data budget/cooldown active",
            "code": 429,
            "retry_after": 61,
        },
        429,
    )
    request.assert_called_once()
    monkeypatch.setattr(endpoint, "get_" + kind, lambda **k: result)
    app = Flask(__name__)
    with app.test_request_context(
        "/quotes", json={"apikey": "fixture", "symbol": "SBIN", "exchange": "NSE"}
    ):
        cls = getattr(endpoint, kind.title())
        # Rate limiter is tested separately; exercise the real endpoint response.
        response = cls.post.__wrapped__(cls())
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "61"
        assert response.json["retry_after"] == 61


@pytest.mark.parametrize("kind", ["quotes", "depth"])
def test_unrelated_broker_errors_remain_errors(monkeypatch, kind):
    from broker.fyers.api import data

    service = importlib.import_module("services." + kind + "_service")
    monkeypatch.setattr(data, "get_br_symbol", lambda *a: "NSE:SBIN-EQ")
    monkeypatch.setattr(
        data,
        "get_api_response",
        lambda *a: {"s": "error", "code": 500, "message": "upstream unavailable"},
    )
    monkeypatch.setattr(service, "validate_symbol_exchange", lambda *a: (True, None))
    monkeypatch.setattr(service, "import_broker_module", lambda *a: data)
    ok, body, status = getattr(service, "get_" + kind + "_with_auth")(
        "fake", None, "fyers", "SBIN", "NSE"
    )
    assert not ok and status == 500 and "retry_after" not in body
