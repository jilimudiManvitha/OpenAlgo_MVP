"""Offline reproductions for broker paths found by the October project review."""

import ast
import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask, has_request_context, session

ROOT = Path(__file__).resolve().parents[1]
BROKERS = ("compositedge", "fivepaisaxts", "ibulls", "iifl", "jainamxts", "rmoney", "wisdom")


@pytest.mark.parametrize("broker", BROKERS)
def test_depth_uses_request_credentials_without_shadowing_sql_session(broker):
    # Execute the actual method without importing broker-specific optional SDKs.
    path = ROOT / "broker" / broker / "api/data.py"
    tree = ast.parse(path.read_text())
    method = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "get_market_depth"
    )
    db = MagicMock()
    db.return_value.__enter__.return_value.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        token="123"
    )
    namespace = dict(
        session=session,
        flask_session=session,
        has_request_context=has_request_context,
        logger=MagicMock(),
        db_session=db,
        SymToken=MagicMock(),
        get_br_symbol=lambda *a: "SBIN",
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    obj = SimpleNamespace(
        user_id=None,
        feed_token=None,
        _fetch_market_data=MagicMock(return_value={"Touchline": {}, "Bids": [], "Asks": []}),
    )
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/"):
        session.update(marketdata_userid="fixture-user", marketdata_token="fixture-feed")
        namespace["get_market_depth"](obj, "SBIN", "NSE")
    obj._fetch_market_data.assert_called()


def test_dhan_reconnect_failure_reaches_bounded_backoff(monkeypatch):
    mod = importlib.import_module("broker.dhan_sandbox.streaming.dhan_websocket")
    obj = mod.DhanWebSocket.__new__(mod.DhanWebSocket)
    obj.running = True
    obj.connected = False
    obj.on_error = MagicMock()
    obj._close_connection = AsyncMock()
    obj._connect = AsyncMock(side_effect=OSError("offline"))

    async def stop(_):
        obj.running = False

    monkeypatch.setattr(mod.asyncio, "sleep", stop)
    asyncio.run(obj._reconnect())
    obj._close_connection.assert_awaited_once()
    obj._connect.assert_awaited_once()
    assert obj.running is False


def test_pocketful_updates_use_real_socket_and_shared_channel(monkeypatch):
    mod = importlib.import_module("broker.pocketful.api.pocketfulwebsocket")
    socket = MagicMock()
    monkeypatch.setattr(mod, "websock", socket)
    obj = mod.PocketfulSocket("fixture", "unused")
    for method, action in [
        ("subscribe_order_update", "subscribe"),
        ("subscribe_trade_update", "subscribe"),
        ("unsubscribe_order_update", "unsubscribe"),
        ("unsubscribe_trade_update", "unsubscribe"),
    ]:
        assert getattr(obj, method)({"client_id": "child"})
        assert json.loads(socket.send.call_args.args[0]) == {
            "a": action,
            "v": ["child", "web"],
            "m": "updates",
        }
    socket.send.side_effect = OSError("disconnected")
    assert obj.subscribe_order_update() is False


def test_replay_charges_apply_sell_stt_and_execution_date():
    from datetime import datetime

    from strategies.nifty_options.engine import IST
    from strategies.nifty_options.replay import execution_fill

    before = datetime(2026, 3, 31, 10, tzinfo=IST)
    after = datetime(2026, 4, 1, 10, tzinfo=IST)
    buy, buyfee = execution_fill(100, 1, 65, after, "fyers")
    sell, oldfee = execution_fill(100, -1, 65, before, "fyers")
    _, newfee = execution_fill(100, -1, 65, after, "fyers")
    assert buy >= 100.05 and sell <= 99.95
    assert newfee > oldfee > buyfee
    assert newfee - oldfee == pytest.approx(round(sell * 65 * 0.0005, 2), abs=0.011)


def test_groww_convenience_order_uses_existing_rest_adapter(monkeypatch):
    mod = importlib.import_module("broker.groww.api.order_api")
    expected = {"groww_order_id": "fixture-id"}
    adapter = MagicMock(return_value=(SimpleNamespace(status=200), expected, "fixture-id"))
    monkeypatch.setattr(mod, "direct_place_order_api", adapter)
    assert (
        mod.direct_place_order(
            "fixture-token", "SBIN", 2, 100, "LIMIT", "SELL", "MIS", "fixture-ref"
        )
        == expected
    )
    adapter.assert_called_once_with(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "quantity": 2,
            "price": 100,
            "pricetype": "LIMIT",
            "action": "SELL",
            "product": "MIS",
            "order_reference_id": "fixture-ref",
        },
        "fixture-token",
    )


@pytest.mark.parametrize("kind", ["regular", "expired"])
def test_history_retry_respects_broker_cooldown(monkeypatch, kind):
    from strategies.nifty_options import data_probe, history

    sleeper = MagicMock()
    if kind == "regular":
        from broker.fyers.api import data

        fetch = MagicMock(
            side_effect=[
                {"s": "error", "code": 429, "retryable": False, "retry_after": 60},
                {"s": "no_data", "candles": []},
            ]
        )
        monkeypatch.setattr(data, "get_api_response", fetch)
        monkeypatch.setattr(history.time, "sleep", sleeper)
        assert (
            history.regular_history("fixture", "NSE:SBIN-EQ", "2026-10-01", "2026-10-01")["candles"]
            == []
        )
    else:
        from services import expired_data_service

        fetch = MagicMock(
            side_effect=[
                (False, {"retry_after": 60}, 429),
                (True, {"data": {"candles": []}}, 200),
            ]
        )
        monkeypatch.setattr(expired_data_service, "get_expired_data", fetch)
        monkeypatch.setattr(data_probe.time, "sleep", sleeper)
        assert data_probe.expired_call("fixture", "history", {}) == {"candles": []}
    sleeper.assert_called_once_with(60.1)
    assert fetch.call_count == 2
