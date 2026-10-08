"""No network: count real adapter requests, shared quotas and MTM price-only flow."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from broker.fyers.api import data
from broker.fyers.api import data_budget as budget


@pytest.fixture
def clock(monkeypatch, tmp_path):
    now = [1800000000.0]
    monkeypatch.setenv("FYERS_DATA_BUDGET_DIR", str(tmp_path))
    monkeypatch.setenv("BROKER_API_KEY", "fixture-key")
    monkeypatch.setenv("FYERS_API_PLAN", "standard")
    monkeypatch.setattr(budget.time, "time", lambda: now[0])
    monkeypatch.setattr(budget.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(budget.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    return now


@pytest.mark.parametrize("plan,minute,interval", [("standard", 45, 0.22), ("prime", 450, 0.13)])
def test_plan_quota_is_bounded_and_window_reopens(clock, monkeypatch, plan, minute, interval):
    monkeypatch.setenv("FYERS_API_PLAN", plan)
    sent = []
    for _ in range(minute):
        budget.acquire()
        sent.append(clock[0])
    assert all(b - a >= interval - 1e-6 for a, b in zip(sent, sent[1:], strict=False))
    with pytest.raises(budget.DataRateLimited) as err:
        budget.acquire()
    assert err.value.retry_after > 0
    clock[0] = sent[0] + 60.01
    budget.acquire()
    state = json.loads(budget.state_path().read_text())
    assert state["count"] == minute + 1
    assert len(state["calls"]) <= minute


def test_cooldown_shared_restarts_daily_budget_and_no_token(clock):
    budget.acquire()
    assert budget.cooldown(2) == 60
    with pytest.raises(budget.DataRateLimited):
        budget.acquire()
    state = json.loads(budget.state_path().read_text())
    state["count"] = 4800
    budget.write(budget.state_path(), state)
    clock[0] += 61
    with pytest.raises(budget.DataRateLimited, match="daily budget"):
        budget.acquire()
    clock[0] = (state["day"] + 1) * 86400 - 19800 + 1
    budget.acquire()
    assert json.loads(budget.state_path().read_text())["count"] == 1
    assert "fixture-key" not in budget.state_path().read_text()


def test_corrupt_state_fails_closed(clock):
    budget.state_path().write_text("invalid")
    with pytest.raises(ValueError):
        budget.acquire()


@pytest.mark.parametrize("http_status,body", [(429, {}), (200, {"s": "error", "code": -429})])
def test_429_prevents_other_symbol_requests(clock, monkeypatch, http_status, body):
    calls = []

    def get(url, **kw):
        calls.append(url)
        return httpx.Response(
            http_status, request=httpx.Request("GET", url), json=body, headers={"Retry-After": "2"}
        )

    monkeypatch.setattr(data, "get_httpx_client", lambda: SimpleNamespace(get=get))
    for symbol in ("CE", "PE", "HEDGE"):
        result = data.get_api_response("/data/depth?symbol=" + symbol, "fixture-token")
        assert result["code"] == 429 and result["retry_after"] >= 60
    assert len(calls) == 1
    clock[0] += 61
    data.get_api_response("/data/depth?symbol=CE", "fixture-token")
    assert len(calls) == 2


def test_twelve_mtm_quotes_make_one_http_call_and_no_depth(clock, monkeypatch):
    from services import quotes_service

    symbols = [{"symbol": f"NIFTY13OCT26{23000 + i * 50}CE", "exchange": "NFO"} for i in range(12)]
    monkeypatch.setattr(quotes_service, "validate_symbol_exchange", lambda *a: (True, None))
    monkeypatch.setattr(data, "get_br_symbol", lambda symbol, exchange: "NSE:" + symbol)
    calls = []

    def get(url, **kw):
        calls.append(url)
        assert "/data/quotes?" in url
        names = parse_qs(urlsplit(url).query)["symbols"][0].split(",")
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "s": "ok",
                "d": [{"s": "ok", "n": s, "v": {"lp": 50, "bid": 49, "ask": 51}} for s in names],
            },
        )

    monkeypatch.setattr(data, "get_httpx_client", lambda: SimpleNamespace(get=get))
    ok, response, status = quotes_service.get_multiquotes(
        symbols, auth_token="fixture", broker="fyers", include_oi=False
    )
    assert ok and status == 200 and len(response["results"]) == 12
    assert all(r["data"]["ltp"] == 50 for r in response["results"])
    assert len(calls) == 1


def test_position_manager_requests_price_only(monkeypatch):
    import database.auth_db as auth
    import sandbox.position_manager as positions

    manager = positions.PositionManager.__new__(positions.PositionManager)
    monkeypatch.setattr(
        auth,
        "ApiKeys",
        SimpleNamespace(
            query=SimpleNamespace(first=lambda: SimpleNamespace(api_key_encrypted="fixture"))
        ),
    )
    monkeypatch.setattr(auth, "decrypt_token", lambda _: "fixture")
    # The manager uses module-level helpers; isolate the actual lookup below.
    calls = []
    monkeypatch.setattr(
        positions, "get_multiquotes", lambda **kw: calls.append(kw) or (True, {"results": []}, 200)
    )
    manager._fetch_quotes_batch([("NIFTY13OCT2624000CE", "NFO")])
    assert calls and calls[0]["include_oi"] is False


def test_quota_is_shared_across_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("FYERS_DATA_BUDGET_DIR", str(tmp_path))
    monkeypatch.setenv("BROKER_API_KEY", "multiprocess-fixture")
    monkeypatch.setenv("FYERS_API_PLAN", "standard")
    # All workers get the same logical time. Only one may reserve its slot.
    script = """from broker.fyers.api import data_budget as b
b.time.time=lambda:1800000000.0
b.time.sleep=lambda _:None
try:
 b.acquire()
 print("admitted")
except b.DataRateLimited:
 print("limited")
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        for _ in range(4)
    ]
    try:
        output = [p.communicate(timeout=10) for p in children]
        assert all(p.returncode == 0 for p in children), output
        assert sum(out.strip() == b"admitted" for out, err in output) == 1
        assert json.loads(budget.state_path().read_text())["count"] == 1
    finally:
        for p in children:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)
