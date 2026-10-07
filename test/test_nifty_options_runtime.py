"""Real scheduled loop with fake transport/orders and isolated SQLite reports."""

import itertools
import queue
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from strategies.nifty_options.daily_reports import DailyReport
from strategies.nifty_options.engine import IST, initial_state
from strategies.nifty_options.feed import QuoteSubscriptions, connection_delay, required_contracts
from strategies.nifty_options.profiles import PROFILES
from strategies.nifty_options.state import Store
from test.test_nifty_options_strategies import POLICY


def spec(symbol):
    return {"exchange": "NFO", "symbol": symbol}


def test_partial_ack_retries_only_missing_symbols_with_backoff():
    calls = []
    replies = iter(
        [
            {
                "status": "partial",
                "subscriptions": [
                    {**spec("A"), "status": "success"},
                    {**spec("B"), "status": "error", "message": "Broker not ready"},
                ],
            },
            {"status": "success"},
        ]
    )

    def subscribe(symbols, mode):
        calls.append(symbols)
        return next(replies)

    client = SimpleNamespace(connected=True, authenticated=True, ws=object(), subscribe=subscribe)
    feed = QuoteSubscriptions([spec("A"), spec("B")])
    feed.step(client, 0)
    assert not feed.ready
    assert "NFO:B: Broker not ready" in feed.error
    feed.step(client, 1)
    assert len(calls) == 1
    feed.step(client, 2)
    assert feed.ready and calls[1] == [spec("B")]
    client.ws = object()
    client.subscribe = lambda symbols, mode: calls.append(symbols) or {"status": "success"}
    feed.step(client, 3)
    assert calls[-1] == [spec("A"), spec("B")]
    client.connected = False
    feed.step(client, 4)
    assert not feed.ready and not feed.accepted


def test_subscription_exceptions_and_incomplete_ack_never_mark_ready():
    client = SimpleNamespace(connected=True, authenticated=True, ws=object())
    feed = QuoteSubscriptions([spec("A"), spec("B")])
    client.subscribe = lambda *_: {
        "status": "success",
        "subscriptions": [{**spec("A"), "status": "success"}],
    }
    feed.step(client, 0)
    assert not feed.ready and feed.pending == [("NFO", "B")]

    def broken(*_):
        raise TimeoutError("secret-like transport details must not be echoed")

    client.subscribe = broken
    for tick in range(2, 4000, 30):
        feed.step(client, tick)
        assert tick < feed.next_attempt <= tick + 30
        assert len(feed.pending) == 1 and len(feed.accepted) == 1
    assert "TimeoutError" in feed.error and "secret-like" not in feed.error


@pytest.mark.parametrize("profile_name", PROFILES)
def test_scheduled_runner_survives_subscription_failure_and_writes_report(
    monkeypatch, tmp_path, profile_name
):
    from database import auth_db
    from services import websocket_client
    from strategies.nifty_options import runtime

    calls = []
    clients = []
    clock_ticks = []
    connection_times = []

    class Client:
        def __init__(self, *args, **kwargs):
            self.connected = self.authenticated = False
            self.ws = object()
            self.thread = None
            self.cleaned = False
            clients.append(self)

        def register_callback(self, *_):
            pass

        def connect(self):
            connection_times.append(clock_ticks[-1])
            self.connected = self.authenticated = True

        def unregister_callback(self, *_):
            pass

        def subscribe(self, symbols, mode):
            calls.append(symbols)
            return (
                {"status": "error", "message": "Broker warming up"}
                if len(calls) == 1
                else {"status": "success"}
            )

        def disconnect(self):
            self.cleaned = True

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (
                datetime(2026, 10, 5, 15, 40, tzinfo=IST)
                if len(calls) >= 2
                else datetime(2026, 10, 5, 9, 15, tzinfo=IST)
            )

    class EmptyQueue:
        def __init__(self, **_):
            pass

        def get(self, **_):
            raise queue.Empty

    monkeypatch.setenv("OPENALGO_API_KEY", "test-only")
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _: "test-owner")
    monkeypatch.setattr(websocket_client, "WebSocketClient", Client)
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "datetime", Clock)
    monkeypatch.setattr(
        runtime,
        "instruments",
        lambda *_: (
            [{"symbol": "A", "expiry": "2026-10-06"}, {"symbol": "B", "expiry": "2026-10-13"}],
            [date(2026, 10, 6), date(2026, 10, 13)],
        ),
    )
    monkeypatch.setattr(runtime, "SandboxExecutor", lambda *_: SimpleNamespace())
    monkeypatch.setattr(runtime, "cleanup_sessions", lambda: None)
    monkeypatch.setattr(runtime.signal, "signal", lambda *_: None)
    monkeypatch.setattr(runtime.queue, "Queue", EmptyQueue)
    counter = itertools.count(100, 1)

    def monotonic():
        clock_ticks.append(next(counter))
        return clock_ticks[-1]

    monkeypatch.setattr(runtime.time, "monotonic", monotonic)
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    monkeypatch.setattr(runtime.Policy, "load", lambda _: POLICY)
    runtime.run(profile_name, "unused")
    assert len(calls) == 2 and clients[0].cleaned
    assert len(connection_times) == 1
    delay = connection_times[0] - clock_ticks[0]
    assert list(PROFILES).index(profile_name) <= delay <= list(PROFILES).index(profile_name) + 3
    expected = "A" if PROFILES[profile_name].expiry == "current" else "B"
    assert {r["symbol"] for r in calls[0]} == {"NIFTY", expected}
    profile = PROFILES[profile_name]
    state_store = Store(tmp_path / "db/nifty_options/state.sqlite3")
    report = DailyReport(
        "test-owner",
        profile,
        Clock.now().date(),
        state_store,
        tmp_path / "db/scanner_strategy_reports.db",
    )
    try:
        saved = report.store.get("test-owner", f"paper-2026-10-05-nifty-options-{profile_name}")
        assert saved["trades"] == []
        assert "no entry" in saved["status"]
        assert saved["streaming_symbols"] == 2
        assert report.store.list("someone-else") == []
    finally:
        report.close()


def test_daily_report_recovers_confirmed_short_fills_without_duplicates(tmp_path):
    now = datetime.now(IST)
    profile = PROFILES["premium_positional_next_week"]
    state = initial_state(profile, POLICY)
    leg = {
        "symbol": "NIFTY_TEST",
        "side": -1,
        "quantity": 65,
        "entry": 30,
        "entry_ts": (now - timedelta(days=1)).isoformat(),
        "orderid": "entry-1",
    }
    closed = {**leg, "exit": 20, "exit_ts": now.isoformat(), "gross_pnl": 650, "reason": "stop"}
    state["legs"] = [{**leg, "symbol": "OPEN", "orderid": "entry-2"}]
    store = Store(tmp_path / "state.db")
    store.save("alice", profile.name, 0, state, [("trade", [closed])])
    store.save("bob", profile.name, 0, state, [("trade", [closed])])
    assert store.closed_trades("alice", profile.name, now.date() - timedelta(days=1)) == []
    for _ in range(2):
        report = DailyReport("alice", profile, now.date(), store, tmp_path / "reports.db")
        try:
            result = report.save(state, "running", now)
            assert len(result["trades"]) == 2
            assert result["trades"][0]["entry_order"] == "entry-1"
            assert result["metrics"]["PAPER"]["net_pnl"] == 650
            assert result["metrics"]["PAPER"]["open_trades"] == 1
            assert (
                result["trades"][0]["entry_ts"]
                == datetime.fromisoformat(leg["entry_ts"]).timestamp()
            )
        finally:
            report.close()


def test_reporting_failure_does_not_interrupt_risk_management(capsys):
    from strategies.nifty_options.runtime import publish_report

    def fail(*_):
        raise OSError("database unavailable")

    assert (
        publish_report(SimpleNamespace(save=fail), {}, "running", datetime.now(IST), None) is None
    )
    assert "will retry" in capsys.readouterr().out


def test_new_backtest_paths_and_legacy_archive_reads(monkeypatch, tmp_path):
    from strategies.nifty_options import history
    from strategies.nifty_options.profiles import BACKTEST_ROOT, ROOT

    assert BACKTEST_ROOT == ROOT / "backtesting/nifty_options"
    monkeypatch.setattr(history, "ROOT", tmp_path)
    monkeypatch.setattr(history, "CACHE", tmp_path / "backtesting/nifty_options/cache")
    new = history.cache_file("NIFTY", "2026-07-03", "2026-10-01")
    legacy = tmp_path / "backtest/nifty_options/cache/candles" / new.name
    legacy.parent.mkdir(parents=True)
    legacy.write_text("existing archive")
    assert history.existing_cache_file("NIFTY", "2026-07-03", "2026-10-01") == legacy
    assert new.is_relative_to(tmp_path / "backtesting") and not new.exists()
    new.parent.mkdir(parents=True)
    new.write_text("new archive")
    assert history.existing_cache_file("NIFTY", "2026-07-03", "2026-10-01") == new


def test_report_success_and_failure_cycles_release_descriptors(tmp_path):
    import gc

    import psutil

    now = datetime.now(IST)
    profile = PROFILES["premium_intraday_current_week"]
    state = initial_state(profile, POLICY)
    store = Store(tmp_path / "state.db")
    report = DailyReport("alice", profile, now.date(), store, tmp_path / "reports.db")
    try:
        report.save(state, "starting", now)
        gc.collect()
        baseline = psutil.Process().num_fds()
        for _ in range(200):
            payload = report.save(state, "waiting for feed", now)
            payload["invalid"] = float("nan")
            with pytest.raises(ValueError):
                report.store.save("alice", payload)
        gc.collect()
        assert psutil.Process().num_fds() == baseline
        assert len(report.store.list("alice")) == 1
    finally:
        report.close()
