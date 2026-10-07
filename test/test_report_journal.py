"""Journal arithmetic against isolated SQLite snapshots, not production data."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from services.report_journal import day_metrics, journal, streaks


def stamp(day, hour):
    return (
        datetime.fromisoformat(f"{day}T{hour}:00")
        .replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        .timestamp()
    )


def trade(day="2026-10-07", symbol="SBIN", start="10:00", end="11:00", gross=110, fees=10, **extra):
    return dict(
        symbol=symbol,
        path="PAPER",
        entry_ts=stamp(day, start),
        exit_ts=stamp(day, end) if end else None,
        entry=100,
        quantity=10,
        gross_pnl=gross,
        fees=fees,
        net_pnl=gross - fees if end else 0,
        **extra,
    )


def report(day, sid, trades, paths=None):
    return {
        "id": f"paper-{day}-{sid}",
        "day": day,
        "strategy_id": sid,
        "kind": sid,
        "status": "complete",
        "paths": paths or ["PAPER"],
        "trades": trades,
        "candles": {},
        "note": "fixture",
    }


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "reports.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE reports(owner TEXT,id TEXT,day TEXT,payload TEXT)")
        records = [
            (
                "alice",
                report(
                    "2026-10-07",
                    "A",
                    [
                        trade(),
                        trade(start="11:30", end="12:00", gross=-40),
                        trade(start="13:00", end="14:00", gross=10),
                    ],
                ),
            ),
            ("alice", report("2026-10-07", "B", [trade(start="14:30", end="15:00", symbol="TCS")])),
            ("bob", report("2026-10-07", "secret", [trade(gross=99999)])),
            ("alice", report("2026-10-08", "A", [trade("2026-10-08", gross=-90)])),
            ("alice", report("2026-10-09", "A", [])),
            ("alice", report("2026-10-12", "A", [trade("2026-10-12", gross=-90)])),
        ]
        for owner, data in records:
            conn.execute(
                "INSERT INTO reports VALUES(?,?,?,?)",
                (owner, data["id"], data["day"], json.dumps(data)),
            )
        conn.commit()
    return path


def test_combined_arithmetic_and_three_stock_entries(saved):
    before = hashlib.sha256(saved.read_bytes()).hexdigest()
    data = journal("alice", 2026, path=saved)
    day = next(d for d in data["days"] if d["day"] == "2026-10-07")
    m = day["metrics"]
    assert (m["gross_pnl"], m["charges"], m["net_pnl"]) == (190, 40, 150)
    assert (m["entries"], m["trades"], m["wins"], m["losses"], m["breakeven"]) == (4, 4, 2, 1, 1)
    assert m["peak_capital"] == 1000  # B trades after A exits: never sum their peaks.
    sbi = next(s for s in day["stocks"] if s["symbol"] == "SBIN")
    assert sbi["metrics"]["entries"] == 3
    assert sbi["metrics"]["net_pnl"] == 50
    assert data["totals"]["net_pnl"] == -50
    assert data["streaks"] == {"winning": 1, "losing": 2, "current": -2}
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == before


def test_owner_filter_and_stock_calendar(saved):
    assert journal("nobody", 2026, path=saved)["days"] == []
    data = journal("alice", 2026, strategy="B", symbol="TCS", path=saved)
    assert len(data["days"]) == 1
    assert data["totals"]["net_pnl"] == 100
    assert "secret" not in str(data)


def test_full_year_not_100_reports(saved):
    with closing(sqlite3.connect(saved)) as conn:
        for i in range(105):
            r = report("2026-04-01", str(i), [])
            conn.execute(
                "INSERT INTO reports VALUES(?,?,?,?)", ("alice", r["id"], r["day"], json.dumps(r))
            )
        conn.commit()
    assert len(journal("alice", 2026, path=saved)["strategies"]) == 107


def test_scenarios_and_financial_year(saved):
    with closing(sqlite3.connect(saved)) as conn:
        for day in ("2026-03-31", "2026-04-01", "2027-03-31", "2027-04-01"):
            ts = [{**trade(day), "path": "OLHC"}, {**trade(day, gross=-90), "path": "OHLC"}]
            r = report(day, "history", ts, ["OLHC", "OHLC"])
            conn.execute(
                "INSERT INTO reports VALUES(?,?,?,?)", ("alice", r["id"], r["day"], json.dumps(r))
            )
        conn.commit()
    assert journal("alice", 2026, "OLHC", path=saved)["totals"]["net_pnl"] == 200
    assert journal("alice", 2026, "OHLC", path=saved)["totals"]["net_pnl"] == -200
    assert journal("alice", 2026, path=saved)["totals"]["net_pnl"] == -50


def test_carried_positions_and_pending_fills():
    carried = trade("2026-10-06", end=None)
    pending = trade(entry_order_state="pending", gross=999)
    m = day_metrics([carried, pending], "2026-10-07")
    assert (m["entries"], m["open_trades"], m["trades"], m["charges"]) == (0, 1, 0, 0)
    assert m["peak_capital"] == 1000
    closed = {**carried, "exit_ts": stamp("2026-10-07", "11:00"), "net_pnl": 100}
    m = day_metrics([closed], "2026-10-07")
    assert (m["entries"], m["trades"], m["net_pnl"], m["charges"]) == (0, 1, 100, 10)
    assert day_metrics([closed], "2026-10-08")["net_pnl"] == 0


def test_concurrent_and_equal_time_capital():
    assert day_metrics([trade(), trade(start="10:30")], "2026-10-07")["peak_capital"] == 2000
    assert (
        day_metrics([trade(), trade(start="11:00", end="12:00")], "2026-10-07")["peak_capital"]
        == 2000
    )


def test_breakeven_breaks_streak():
    days = [
        {"day": f"2026-10-0{i + 1}", "metrics": {"trades": 1, "net_pnl": n}}
        for i, n in enumerate([100, 100, 0, -20])
    ]
    assert streaks(days) == {"winning": 2, "losing": 1, "current": -1}


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "absent.db"
    assert journal("alice", 2026, path=path)["days"] == []
    assert not path.exists()


def test_api_auth_validation_and_scoping(saved, monkeypatch):
    from blueprints import market_scanner as routes
    from services import report_journal as service

    monkeypatch.setattr(routes, "is_session_valid", lambda: True)
    monkeypatch.setattr(service, "journal", partial(journal, path=saved))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(routes.market_scanner_bp)
    # The fixture must never attach scanner services on requests.
    app.before_request_funcs.clear()
    client = app.test_client()
    url = "/market-scanner/api/report-journal"
    assert client.get(url).status_code == 401
    with client.session_transaction() as session:
        session["user"] = "alice"
    assert client.get(url + "?year=bad").status_code == 400
    assert client.get(url + "?year=3000").status_code == 400
    assert client.get(url + "?scenario=ALL").status_code == 400
    response = client.get(url + "?year=2026&charges=recorded")
    assert response.status_code == 200
    assert response.json["data"]["totals"]["net_pnl"] == -50
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as session:
        session["user"] = "bob"
    assert client.get(url + "?year=2026&charges=recorded").json["data"]["totals"]["net_pnl"] == 99989
