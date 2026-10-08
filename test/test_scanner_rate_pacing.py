"""Scanner retries have one owner and bulk REST calls leave quota headroom."""

from datetime import datetime
from threading import Event
from unittest.mock import Mock

import httpx
import pytest

from broker.fyers.api import data
from services.market_scanner_provider import FyersScannerProvider, ScannerError
from services.market_scanner_service import IST, ScannerManager


@pytest.fixture(autouse=True)
def isolated_budget(monkeypatch, tmp_path):
    # Each 429 case must exercise its own response, not a previous case's cooldown.
    monkeypatch.setenv("FYERS_DATA_BUDGET_DIR", str(tmp_path))


@pytest.mark.parametrize(
    "headers, expected_delay",
    [({"Retry-After": "180"}, 180), ({"X-Retry-After-Ms": "90000"}, 90), ({}, 60)],
)
def test_scanner_http_429_returns_once_without_short_nested_retries(
    monkeypatch, headers, expected_delay
):
    client = Mock()
    client.get.return_value = httpx.Response(
        429,
        request=httpx.Request("GET", "https://api-t1.fyers.in/data/quotes"),
        headers=headers,
    )
    monkeypatch.setattr(data, "get_httpx_client", lambda: client)
    monkeypatch.setattr(data, "apply_rate_limit", lambda **kwargs: None)
    sleep = Mock()
    monkeypatch.setattr(data.time, "sleep", sleep)
    with pytest.raises(ScannerError) as failure:
        FyersScannerProvider("fixture")._request("/data/quotes?symbols=NSE:ABC-EQ")
    assert failure.value.status_code == 429
    assert failure.value.retry_after == expected_delay
    client.get.assert_called_once()
    sleep.assert_not_called()


def job():
    return {
        "cancel": Event(),
        "session_date": "2026-10-01",
        "phase": "quotes",
        "rate_limit_retries": 0,
    }


def test_bulk_calls_are_spaced_across_quote_and_history_batches(monkeypatch):
    from services import market_scanner_service as service

    clock = [1000.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])
    manager = ScannerManager(clock=lambda: datetime(2026, 10, 1, 8, 50, tzinfo=IST))
    monkeypatch.setattr(
        manager, "_wait_for_retry", lambda job, delay: clock.__setitem__(0, clock[0] + delay)
    )
    provider = FyersScannerProvider("fixture")
    calls = []
    monkeypatch.setattr(
        provider,
        "_request",
        lambda endpoint: calls.append(clock[0]) or {"s": "ok", "d": [], "candles": []},
    )
    state = job()
    for _ in range(54):
        manager._call_broker(state, provider.quotes, [{"broker_symbol": "NSE:ABC-EQ"}])
    assert len(calls) == 54
    assert all(b - a >= 1.25 for a, b in zip(calls, calls[1:], strict=False))
    # A new method on the same provider shares the same manager pacing state.
    manager._call_broker(
        state, provider.history, {"broker_symbol": "NSE:ABC-EQ"}, datetime(2026, 10, 1).date()
    )
    assert calls[-1] - calls[-2] >= 1.25


def test_scanner_cooldown_honors_longer_server_delay(monkeypatch):
    manager = ScannerManager(clock=lambda: datetime(2026, 10, 1, 8, 50, tzinfo=IST))
    waits = []
    monkeypatch.setattr(manager, "_wait_for_retry", lambda job, delay: waits.append(delay))
    limited = ScannerError("rate limit", 429)
    limited.retry_after = 180
    request = Mock(side_effect=[limited, "recovered"])
    assert manager._call_broker(job(), request) == "recovered"
    assert waits == [180]


def test_cancel_during_pacing_prevents_next_http_call(monkeypatch):
    manager = ScannerManager(clock=lambda: datetime(2026, 10, 1, 8, 50, tzinfo=IST))
    provider = FyersScannerProvider("fixture")
    request = Mock(return_value={"s": "ok", "d": []})
    monkeypatch.setattr(provider, "_request", request)
    state = job()
    instruments = [{"broker_symbol": "NSE:ABC-EQ"}]
    manager._call_broker(state, provider.quotes, instruments)
    monkeypatch.setattr(manager, "_wait_for_retry", lambda job, delay: job["cancel"].set())
    with pytest.raises(ScannerError) as failure:
        manager._call_broker(state, provider.quotes, instruments)
    assert failure.value.status_code == 499
    request.assert_called_once()


def test_non_data_fyers_callers_keep_existing_http_retries(monkeypatch):
    client = Mock()
    request = httpx.Request("GET", "https://api-t1.fyers.in/api/v3/orders")
    client.get.side_effect = [
        httpx.Response(429, request=request),
        httpx.Response(200, request=request, json={"s": "ok", "d": []}),
    ]
    monkeypatch.setattr(data, "get_httpx_client", lambda: client)
    monkeypatch.setattr(data, "apply_rate_limit", lambda **kwargs: None)
    sleep = Mock()
    monkeypatch.setattr(data.time, "sleep", sleep)
    assert data.get_api_response("/api/v3/orders", "fixture")["s"] == "ok"
    assert client.get.call_count == 2
    sleep.assert_called_once_with(1)
