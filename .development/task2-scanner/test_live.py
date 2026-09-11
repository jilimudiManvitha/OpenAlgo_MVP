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

        def publish(self, *args):
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
