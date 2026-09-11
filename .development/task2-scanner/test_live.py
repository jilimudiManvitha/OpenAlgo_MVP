import json
from datetime import datetime, timedelta

import pytest
from flask import Flask
from flask_wtf.csrf import CSRFProtect, generate_csrf

from services import market_scanner_live as live
from services.market_scanner_service import IST, make_row, validate_options

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=IST)


def row(symbol="ABC", price=110, volume=250000, average=100000):
    return make_row(
        {"symbol": symbol, "name": symbol},
        {
            "lp": price,
            "prev_close_price": 100,
            "open": 109,
            "volume": volume,
            "tt": NOW.timestamp(),
        },
        [{"date": f"2026-09-{d:02d}", "volume": average} for d in (4, 7, 8, 9, 10)],
        NOW.date(),
        5,
        NOW,
    )


@pytest.fixture(autouse=True)
def offline_calendar(monkeypatch):
    monkeypatch.setattr(
        live,
        "market_open",
        lambda now: now.weekday() < 5 and 555 <= now.hour * 60 + now.minute < 930,
    )


def snapshot(rows, now=NOW, **filters):
    return live.view_snapshot(
        {"session_date": NOW.date().isoformat(), "rows": rows},
        validate_options(dict(limit=50, **filters)),
        {},
        now=now,
    )


def test_percent_previous_close_and_volume_consistent():
    result = snapshot([row()])["volume_shockers"][0]
    assert result["change_percent"] == pytest.approx(10)
    assert result["rvol"] == 2.5
    assert result["volume_change_percent"] == 150
    assert result["stale"] is False
    assert snapshot([row(price=90)])["top_losers"][0]["change_percent"] == -10


def test_zero_baseline_is_na_but_price_mover_remains():
    result = snapshot([row(average=0)])
    assert result["volume_shockers"] == []
    assert result["top_gainers"][0]["volume_change_percent"] is None


def test_changed_baseline_never_relabels_old_volume_results():
    result = live.view_snapshot(
        {"session_date": "2026-09-11", "rows": [row()], "options": {"lookback_days": 5}},
        validate_options({"lookback_days": 1}),
        {},
        now=NOW,
    )
    assert result["top_gainers"][0]["change_percent"] == 10
    assert result["top_gainers"][0]["baseline_status"] == "baseline_refresh_pending"
    assert result["top_gainers"][0]["rvol"] is None
    assert not result["volume_shockers"]


def test_missing_live_volume_does_not_hide_valid_price_change():
    result = snapshot([row(volume=None)])
    assert result["top_gainers"][0]["change_percent"] == pytest.approx(10)
    assert result["top_gainers"][0]["volume"] is None
    assert not result["volume_shockers"]
    assert not snapshot([row(volume=None)], min_volume=1)["top_gainers"]


def test_shared_tick_recalculates_price_and_volume_and_rejects_old_ticks():
    from services.market_scanner_feed import merge_quote

    original = row()
    now = NOW + timedelta(seconds=5)
    message = {
        "mode": 2,
        "data": {
            "timestamp": now.timestamp(),
            "last_traded_time": now.timestamp(),
            "ltp": 120,
            "volume": 300000,
        },
    }
    updated = merge_quote(original, message, now)
    assert updated["change_percent"] == pytest.approx(20)
    assert updated["rvol"] == 3
    assert merge_quote(updated, message, now) is updated
    assert merge_quote(original, message, now + timedelta(minutes=1)) is original
    assert merge_quote(original, {**message, "mode": 3}, now) is original
    for changes in (
        {"last_traded_time": (NOW - timedelta(days=1)).timestamp()},
        {"volume": 10},
        {"ltp": float("nan")},
        {"timestamp": None},
    ):
        assert (
            merge_quote(original, {**message, "data": {**message["data"], **changes}}, now)
            is original
        )


def test_expired_owner_cannot_publish_over_new_worker(tmp_path):
    import time

    store = live.LiveStore("sqlite:///" + (tmp_path / "fence.db").as_posix())
    try:
        key = store.configure("alice", "fyers")
        assert store.elect("new", time.time())
        store.publish(key, {"state": "completed"}, owner="new")
        store.publish(key, {"state": "failed"}, owner="old")
        assert json.loads(store.accounts()[0]["snapshot"])["state"] == "completed"
    finally:
        store.engine.dispose()


def test_coordinator_publishes_completion_then_waits_and_honors_changed_options(
    tmp_path, monkeypatch
):
    import time

    from services import market_scanner_provider, market_scanner_service

    calls = []

    class Provider:
        def quotes(self, instruments):
            calls.append("quotes")
            return {
                "NSE:ABC-EQ": {
                    "lp": 110,
                    "prev_close_price": 100,
                    "volume": 250000,
                    "tt": NOW.timestamp(),
                }
            }

        def history(self, *args):
            return [
                [(NOW - timedelta(days=d)).timestamp(), 100, 110, 90, 100, 100000]
                for d in range(6, 0, -1)
            ]

    class Cache:
        def __init__(self):
            self.engine = self

        def prune(self, *args):
            pass

        def get(self, *args):
            return None

        def put(self, *args):
            pass

        def dispose(self):
            pass

    monkeypatch.setattr(live, "market_open", lambda now: False)
    monkeypatch.setattr(live, "now_ist", lambda: NOW)
    monkeypatch.setattr(market_scanner_service, "now_ist", lambda: NOW)
    monkeypatch.setattr(live, "provider_for", lambda *args: Provider())
    monkeypatch.setattr(
        live,
        "universe_for",
        lambda *args: [{"symbol": "ABC", "name": "ABC", "broker_symbol": "NSE:ABC-EQ"}],
    )
    monkeypatch.setattr(market_scanner_provider, "credentials", lambda *args: ("fixture", None))
    monkeypatch.setattr(live.PublishingManager, "_default_cache", staticmethod(Cache))
    store = live.LiveStore("sqlite:///" + (tmp_path / "coordinator.db").as_posix())
    coordinator = live.LiveCoordinator(store)
    key = store.configure("alice", "fyers")
    try:
        coordinator.tick()
        deadline = time.monotonic() + 5
        while coordinator.managers[key].active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not coordinator.managers[key].active
        coordinator.tick()
        assert json.loads(store.accounts()[0]["snapshot"])["state"] == "completed"
        assert not coordinator.managers and len(calls) == 2
        coordinator.tick()
        assert len(calls) == 2
        store.configure("alice", "fyers", {"lookback_days": 1, "limit": 50})
        coordinator.tick()
        assert key in coordinator.managers
        while coordinator.managers[key].active and time.monotonic() < deadline:
            time.sleep(0.01)
        coordinator.tick()
        assert len(calls) == 4
    finally:
        coordinator.close()


def test_feed_owns_and_closes_only_its_proxy_connection(monkeypatch):
    from database import auth_db
    from services import market_scanner_provider, websocket_client
    from services.market_scanner_feed import ScannerFeed

    calls = []

    class Store:
        def owns(self, owner):
            return True

    feed = ScannerFeed("alice", "fyers", Store(), "owner")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            calls.append("connect")
            return True

        def subscribe(self, instruments, mode):
            calls.append(("subscribe", len(instruments), mode))
            return {"status": "success"}

        def get_subscriptions(self):
            feed.stop_event.set()
            return {"count": 1}

        def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setattr(websocket_client, "WebSocketClient", Client)
    monkeypatch.setattr(market_scanner_provider, "credentials", lambda *args: ("fixture", None))
    monkeypatch.setattr(market_scanner_provider, "universe_for", lambda *args: [{"symbol": "ABC"}])
    monkeypatch.setattr(auth_db, "get_api_key_for_tradingview", lambda *args: "fixture")
    feed._run()
    assert calls == ["connect", ("subscribe", 1, "Quote"), "disconnect"]
    assert feed.client is None and feed.subscribed == 0


def test_category_before_top_50_and_deduplicated_membership():
    rows = [row(f"S{i:03}", 101 + i) for i in range(100)]
    categories = {"nifty50": {"symbols": ["S000", "S001", "S001"], "effective_date": None}}
    result = live.view_snapshot(
        {"session_date": "2026-09-11", "rows": rows},
        validate_options({"limit": 50}),
        categories,
        "nifty50",
        NOW,
    )
    assert [r["symbol"] for r in result["top_gainers"]] == ["S001", "S000"]
    assert result["matching_counts"]["top_gainers"] == 2
    assert len(snapshot(rows)["top_gainers"]) == 50
    assert snapshot(rows)["top_gainers"][0]["symbol"] == "S099"


def test_stale_and_new_day_never_mislabeled_live():
    assert snapshot([row()], NOW + timedelta(minutes=3))["top_gainers"][0]["stale"]
    result = snapshot([row()], NOW + timedelta(days=1))
    assert result["stale"] and not result["top_gainers"]


def test_persistent_controls_lease_and_account_isolation(tmp_path):
    url = "sqlite:///" + (tmp_path / "scanner.db").as_posix()
    a, b = live.LiveStore(url), live.LiveStore(url)
    try:
        key = a.configure("alice", "fyers")
        a.configure("alice", "fyers", enabled=False)
        a.configure("alice", "fyers")  # navigation must not undo pause
        assert not b.accounts()[0]["enabled"]
        other = a.configure("alice", "zerodha")
        assert key != other
        a.publish(key, {"rows": [row()]})
        assert next(r for r in b.accounts() if r["account"] == other)["snapshot"] is None
        assert a.elect("worker1", 100)
        assert not b.elect("worker2", 105)
        assert a.elect("worker1", 110)
        assert not b.elect("worker2", 121)
        assert b.elect("worker2", 131)
        a.release("worker1")
        assert not a.elect("worker1", 132)
    finally:
        a.engine.dispose()
        b.engine.dispose()


def test_index_import_provenance_and_overlap(tmp_path):
    (tmp_path / "ind_nifty50list.csv").write_text("Symbol,Series\nABC,EQ\nABC,EQ\nBAD,BE\n")
    result = live.import_categories(tmp_path)["nifty50"]
    assert result["symbols"] == ["ABC"]
    assert result["effective_date"] is None and len(result["sha256"]) == 64


def test_observations_bounded_and_preserve_unknown_history(monkeypatch):
    class Store:
        def owns(self, owner):
            return True

        def publish(self, *args, **kwargs):
            pass

    manager = live.PublishingManager(Store(), "account", "owner", {}, clock=lambda: NOW)
    job = {
        "rows": [],
        "session_date": "2026-09-11",
        "options": validate_options({}),
        "state": "completed",
        "issues": [],
    }
    for i in range(250):
        r = row()
        r["last_trade_at"] = (NOW + timedelta(seconds=i)).isoformat()
        manager._update(job, rows=[r])
    assert len(manager.series) == 1
    assert len(job["rows"][0]["sparkline"]) == 120
    assert job["rows"][0]["sparkline_basis"] == "since connected"


def test_common_non_fyers_provider_retains_timestamp(monkeypatch):
    from services import quotes_service
    from services.market_scanner_provider import CommonScannerProvider

    monkeypatch.setattr(
        quotes_service,
        "import_broker_module",
        lambda broker: type("Module", (), {"BrokerData": object}),
    )
    monkeypatch.setattr(
        quotes_service,
        "get_multiquotes_with_auth",
        lambda *args: (
            True,
            {
                "results": [
                    {
                        "symbol": "ABC",
                        "data": {
                            "ltp": 110,
                            "prev_close": 100,
                            "volume": 250000,
                            "timestamp": NOW.timestamp(),
                        },
                    }
                ]
            },
            200,
        ),
    )
    provider = CommonScannerProvider("fixture", None, "fixturebroker")
    quote = provider.quotes([{"symbol": "ABC", "exchange": "NSE"}])["fixturebroker:NSE:ABC"]
    assert quote["tt"] == NOW.timestamp() and quote["prev_close_price"] == 100


def test_zerodha_native_quote_preserves_previous_close_and_trade_time(monkeypatch):
    from broker.zerodha.api import data
    from services.market_scanner_provider import ZerodhaScannerProvider

    monkeypatch.setattr(
        data,
        "get_api_response",
        lambda *args: {
            "status": "success",
            "data": {
                "NSE:ABC": {
                    "last_price": 110,
                    "ohlc": {"open": 109, "close": 100},
                    "volume": 250000,
                    "last_trade_time": "2026-09-11 12:00:00",
                }
            },
        },
    )
    provider = ZerodhaScannerProvider("fixture", None, "zerodha")
    quote = provider.quotes([{"symbol": "ABC", "broker_symbol": "zerodha:NSE:ABC"}])[
        "zerodha:NSE:ABC"
    ]
    result = make_row({"symbol": "ABC", "name": "ABC"}, quote, None, NOW.date(), 5, NOW)
    assert result["change_percent"] == 10
    assert result["last_trade_at"] == NOW.isoformat()


def test_routes_auth_csrf_shared_results_and_controls(tmp_path, monkeypatch):
    from blueprints import market_scanner as routes
    from services import market_scanner_provider

    store = live.LiveStore("sqlite:///" + (tmp_path / "routes.db").as_posix())

    class Coordinator:
        def __init__(self):
            self.store = store

    monkeypatch.setattr(live, "coordinator", lambda: Coordinator())
    monkeypatch.setattr(market_scanner_provider, "credentials", lambda *args: ("fixture", None))
    monkeypatch.setattr(routes, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-only")
    CSRFProtect(app)
    app.register_blueprint(routes.market_scanner_bp)
    app.get("/csrf")(lambda: {"token": generate_csrf()})
    try:
        with app.test_client() as client:
            assert client.get("/market-scanner/api/live").status_code == 401
            with client.session_transaction() as session:
                session.update(user="alice", broker="zerodha")
            assert (
                client.post("/market-scanner/api/live", json={"enabled": False}).status_code == 400
            )
            headers = {"X-CSRFToken": client.get("/csrf").json["token"]}
            assert (
                client.post(
                    "/market-scanner/api/live", json={"enabled": False}, headers=headers
                ).status_code
                == 200
            )
            result = client.get("/market-scanner/api/live").json["data"]
            assert result["enabled"] is False and result["broker"] == "zerodha"
            assert "user" not in result and "rows" not in result
            assert client.get("/market-scanner/api/live?category=missing").status_code == 400
    finally:
        store.engine.dispose()
