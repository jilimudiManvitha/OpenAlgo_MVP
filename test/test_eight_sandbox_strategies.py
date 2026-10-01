"""Incident regressions: delayed fills, shared warmup and actual 5m HA bars."""

import json
import sqlite3
from datetime import datetime
from unittest.mock import Mock

import pytest

from strategies.top_gain_volumes.history import aggregate_minutes, shared_request
from strategies.top_gain_volumes.profiles import PROFILES
from strategies.top_gain_volumes.runtime import (
    IST,
    TickCandles,
    enter,
    entries_blocked,
    maintain_positions,
)
from strategies.top_gain_volumes.sandbox_execution import SandboxExecution


def sink_fixture(tmp_path):
    sink = SandboxExecution.__new__(SandboxExecution)
    sink.lock_path = tmp_path / "dispatch.lock"
    sink.strategy = "Four10K_fixture"
    sink.persist = Mock()
    sink.manager = Mock()
    sink.manager.place_order.return_value = (True, {"mode": "analyze", "orderid": "one"}, 200)
    return sink


def status(state, price=100, qty=100):
    return (
        True,
        {
            "data": {
                "order_status": state,
                "average_price": price,
                "filled_quantity": qty if state == "complete" else 0,
            }
        },
        200,
    )


def trade_fixture():
    return {
        "symbol": "ABC",
        "quantity": 100,
        "entry": 100,
        "stop": 99,
        "target": 103,
        "exit_ts": None,
        "entry_ts": 1000,
        "path": "PAPER",
    }


def test_pending_entry_is_retained_and_confirmed_without_duplicate(tmp_path):
    sink = sink_fixture(tmp_path)
    sink.manager.get_order_status.return_value = status("open")
    trade = trade_fixture()
    assert sink.enter(trade, {"ltp": 100, "high": 101, "low": 99}, 0.05)
    assert trade["entry_order_state"] == "pending"
    assert entries_blocked({"ABC": trade})
    assert not sink.exit(trade, 1001, {"ltp": 101}, "TARGET")
    assert sink.reconcile(trade, 1002) == "pending"
    sink.manager.get_order_status.return_value = status("complete", 100.5)
    assert sink.reconcile(trade, 1003) == "open"
    assert trade["entry"] == 100.5 and trade["target"] == 105
    assert not entries_blocked({"ABC": trade})
    assert sink.manager.place_order.call_count == 1


def test_pending_exit_polled_once_and_never_resubmitted(tmp_path):
    sink = sink_fixture(tmp_path)
    trade = trade_fixture()
    trade["entry_order_state"] = "complete"
    sink.manager.get_order_status.return_value = status("open")
    assert not sink.exit(trade, 1001, {"ltp": 103}, "TARGET")
    assert not sink.exit(trade, 1002, {"ltp": 103}, "TARGET")
    sink.manager.get_order_status.return_value = status("complete", 103)
    assert sink.reconcile(trade, 1003) == "closed"
    assert trade["exit"] == 103 and trade["net_pnl"] == 300
    assert sink.manager.place_order.call_count == 1


def test_incoherent_quote_does_not_dispatch_or_disable_stale_guard(tmp_path):
    sink = sink_fixture(tmp_path)
    trade = trade_fixture()
    assert not sink.enter(trade, {"ltp": 233.49, "low": 230.29, "high": 233.41}, 0.05)
    sink.manager.place_order.assert_not_called()


def test_unknown_dispatch_pauses_entries_but_does_not_throw_or_duplicate(tmp_path):
    sink = sink_fixture(tmp_path)
    sink.manager.place_order.return_value = (False, {"mode": "analyze"}, 500)
    trade = trade_fixture()
    assert sink.enter(trade, {"ltp": 100}, 0.05)
    assert entries_blocked({"ABC": trade})
    assert sink.reconcile(trade, 1003) == "pending"
    assert sink.place(trade, "BUY", {"ltp": 100}) is None
    assert sink.manager.place_order.call_count == 1


def test_clock_squareoff_uses_fresh_cached_quote_without_new_tick(tmp_path):
    sink = sink_fixture(tmp_path)
    trade = trade_fixture()
    trade["entry_order_state"] = "complete"
    now = datetime(2026, 10, 1, 15, 0, tzinfo=IST).timestamp()
    sink.manager.get_order_status.return_value = status("complete", 102)
    maintain_positions(
        sink, {"ABC": trade}, {"trades": [trade]}, {"ABC": (now - 1, {"ltp": 102})}, now
    )
    assert trade["exit_ts"] == now and trade["reason"] == "SQUARE_OFF"


def test_cutoff_cancels_pending_entry_then_records_terminal_state(tmp_path):
    sink = sink_fixture(tmp_path)
    trade = trade_fixture()
    sink.manager.get_order_status.return_value = status("open")
    sink.enter(trade, {"ltp": 100}, 0.05)
    sink.manager.get_order_status.side_effect = [status("open"), status("cancelled")]
    report, traded = {"trades": [trade]}, {"ABC": trade}
    now = datetime(2026, 10, 1, 15, 0, tzinfo=IST).timestamp()
    maintain_positions(sink, traded, report, {}, now)
    sink.manager.cancel_order.assert_called_once_with("one")
    assert not traded and not report["trades"]
    assert report["rejected_entries"][0]["entry_order_state"] == "cancelled"


def seed5():
    start = datetime(2026, 10, 1, 9, 15, tzinfo=IST).timestamp()
    rows = [[start - 86400 + i * 60, 100, 100, 100, 100, 10] for i in range(100)]
    rows += [[start + i * 60, 110, 112, 110, 111, 20] for i in range(5)]
    return rows, start


@pytest.mark.parametrize("profile_id", list(PROFILES))
def test_all_profiles_dispatch_on_intrabar_high_cross_before_entry_close(profile_id, tmp_path):
    profile = PROFILES[profile_id]
    minutes = profile["timeframe_minutes"]
    interval = minutes * 60
    start = int(datetime(2026, 10, 1, 9, 15, tzinfo=IST).timestamp())
    raw = [[start - 86400 + i * 60, 100, 100, 100, 100, 10] for i in range(100)]
    # Low-priced opening volume keeps session VWAP below the complete signal's
    # HA low, so the stricter trailing profiles qualify without bypassing guards.
    raw += [[start + i * 60, 90, 90, 90, 90, 1000] for i in range(minutes)]
    raw += [[start + interval + i * 60, 110, 112, 110, 111, 1] for i in range(minutes)]
    candle = TickCandles(
        raw,
        start + 2 * interval - 1,
        strict_vwap=profile["trailing"],
        timeframe_minutes=minutes,
    )
    entry_start = start + 2 * interval
    volume = minutes * 1001
    sink = sink_fixture(tmp_path)
    sink.manager.get_order_status.return_value = status("open")

    assert not candle.tick(entry_start, 111, volume)
    assert candle.signal == (start + interval, 112, 95)
    assert not candle.tick(entry_start + 1, 112, volume + 10)  # Touch is not a cross.
    sink.manager.place_order.assert_not_called()

    stamp = entry_start + 2
    assert candle.tick(stamp, 113, volume + 20)
    assert candle.last_completed[0] == start + interval
    assert candle.bar[0] == entry_start and stamp < entry_start + interval
    trade = enter("ABC", stamp, 113, candle, 0.05)
    assert trade["entry_ts"] == stamp
    quote = {"ltp": 113, "low": 90, "high": 113}
    assert sink.enter(trade, quote, 0.05)
    sink.manager.place_order.assert_called_once()
    order = sink.manager.place_order.call_args.args[0]
    assert order["action"] == "BUY" and order["price_type"] == "MARKET"
    assert trade["entry_order_state"] == "pending"


def test_five_minute_ha_aggregates_ohlcv_before_indicator_calculation():
    rows, start = seed5()
    candle = TickCandles(rows, start + 299, timeframe_minutes=5)
    assert candle.interval == 300
    assert len(candle.closes) == 20
    assert candle.bar == [start, 110, 112, 110, 111, 100]
    assert not candle.tick(start + 300, 111, 110)
    assert candle.chart[-1]["ha_close"] == 110.75
    assert candle.chart[-1]["volume"] == 100
    assert candle.signal[0] == start
    assert candle.tick(start + 301, 113, 120)
    assert candle.bar[0] == start + 300  # Entry is in NEXT 5m bar, not next 1m.
    assert not candle.tick(start + 302, 90, 130)


def test_missing_minute_cannot_hide_inside_five_minute_warmup():
    rows, start = seed5()
    del rows[-3]
    with pytest.raises(ValueError, match="incomplete"):
        TickCandles(rows, start + 299, timeframe_minutes=5)


def test_partial_historical_bucket_is_not_promoted_to_completed():
    rows, start = seed5()
    del rows[2]
    assert len(aggregate_minutes(rows, 5, start + 299)) == 20


def test_shared_history_coalesces_identical_requests_and_closes_db(tmp_path, monkeypatch):
    from strategies.top_gain_volumes import history

    monkeypatch.setattr(history.time, "sleep", lambda _: None)
    provider = Mock()
    provider._request.return_value = {"candles": [[1, 2, 3, 1, 2, 9]]}
    path = tmp_path / "history.db"
    for _ in range(120):
        assert (
            shared_request(provider, "/history/ABC", "fixture", "2026-10-01", True, path)
            == provider._request.return_value
        )
    assert provider._request.call_count == 1
    with sqlite3.connect(path) as c:
        assert c.execute("select count(*) from history_cache").fetchone()[0] == 1
        assert (
            json.loads(c.execute("select payload from history_cache").fetchone()[0])
            == provider._request.return_value
        )


def test_shared_rate_limit_failure_applies_global_cooldown(tmp_path):
    provider = Mock()
    provider._request.side_effect = RuntimeError("rate limited")
    path = tmp_path / "history.db"
    with pytest.raises(RuntimeError, match="rate limited"):
        shared_request(provider, "a", "fixture", "2026-10-01", True, path)
    with pytest.raises(RuntimeError, match="cooldown"):
        shared_request(provider, "b", "fixture", "2026-10-01", True, path)
    assert provider._request.call_count == 1


def test_feed_reconnect_restores_all_subscriptions_without_duplicate_on_same_socket():
    from strategies.top_gain_volumes.runtime import restore_quote_feed

    client = Mock(connected=True, authenticated=True)
    client.ws = object()
    client.subscribe.return_value = {"status": "success"}
    symbols = [f"S{i}" for i in range(101)]
    assert restore_quote_feed(client, symbols, object()) is client.ws
    assert client.subscribe.call_count == 3
    assert restore_quote_feed(client, symbols, client.ws) is client.ws
    assert client.subscribe.call_count == 3
    client.ws = object()
    assert restore_quote_feed(client, symbols, object()) is client.ws
    assert client.subscribe.call_count == 6


def test_exhausted_local_client_closes_before_restarting():
    from strategies.top_gain_volumes.runtime import restore_quote_feed

    client = Mock(connected=False, authenticated=False)
    client.thread.is_alive.return_value = False
    client.connect.return_value = False
    assert restore_quote_feed(client, ["ABC"], None) is None
    assert [c[0] for c in client.mock_calls] == ["thread.is_alive", "disconnect", "connect"]


def test_hsm_keeps_retrying_after_ten_failures_and_stops_promptly(monkeypatch):
    import websocket_proxy  # noqa: F401 -- import order matches the application's plugin loading
    from broker.fyers.streaming import fyers_hsm_websocket as hsm

    sock = hsm.FyersHSMWebSocket.__new__(hsm.FyersHSMWebSocket)
    sock.logger = Mock()
    sock.running = sock.reconnect_enabled = True
    sock.reconnect_attempts = 10000
    timer = [0.0]
    monkeypatch.setattr(hsm.time, "monotonic", lambda: timer[0])
    monkeypatch.setattr(hsm.time, "sleep", lambda delay: timer.__setitem__(0, timer[0] + delay))
    assert sock._handle_reconnect()
    assert timer[0] == pytest.approx(60)
    assert sock.running

    def stop(delay):
        timer[0] += delay
        sock.running = False

    monkeypatch.setattr(hsm.time, "sleep", stop)
    assert not sock._handle_reconnect()
    assert timer[0] <= 60.2


def test_history_repetition_has_bounded_descriptors(tmp_path, monkeypatch):
    import psutil

    from strategies.top_gain_volumes import history

    monkeypatch.setattr(history.time, "sleep", lambda _: None)
    provider = Mock()
    provider._request.return_value = {"candles": []}
    path = tmp_path / "history.db"
    shared_request(provider, "a", "fixture", "2026-10-01", True, path)
    process = psutil.Process()
    before = process.num_fds()
    for _ in range(120):
        shared_request(provider, "a", "fixture", "2026-10-01", True, path)
    assert process.num_fds() <= before + 2


def test_history_requests_exact_regular_session_to_avoid_conflicting_fyers_duplicates():
    from urllib.parse import parse_qs, urlparse

    from strategies.top_gain_volumes.history import fetch_intraday_history

    provider = Mock()
    provider._request.return_value = {"candles": []}
    fetch_intraday_history(provider, "NSE:BANKBARODA-EQ", "2026-09-30")
    query = parse_qs(urlparse(provider._request.call_args_list[1].args[0]).query)
    assert query["range_from"] == [str(int(datetime(2026, 9, 30, 9, 15, tzinfo=IST).timestamp()))]
    assert query["range_to"] == [
        str(int(datetime(2026, 9, 30, 15, 30, tzinfo=IST).timestamp()) - 1)
    ]
