"""Real read-only SQLite execution history -> daily journal, owner/mode/broker provenance."""

import hashlib
import sqlite3
from contextlib import closing

import pytest

from services.report_journal import journal
from services.report_strategy_runs import detail, reports


@pytest.fixture
def history(tmp_path):
    path = tmp_path / "runs.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript("""
            CREATE TABLE sm_strategy(id INTEGER,user_id TEXT,name TEXT);
            CREATE TABLE sm_strategy_run(id INTEGER,strategy_id INTEGER,mode TEXT,broker TEXT,stopped_at TEXT);
            CREATE TABLE sm_strategy_order(id INTEGER,run_id INTEGER,leg_id INTEGER,position_ref TEXT,
                kind TEXT,broker_order_id TEXT,symbol TEXT,exchange TEXT,product TEXT,action TEXT,
                filled_qty REAL,avg_fill_price REAL,filled_at TEXT);
            INSERT INTO sm_strategy VALUES (1,'alice','Live Swing'),(2,'alice','Paper Swing'),(3,'bob','Private');
            INSERT INTO sm_strategy_run VALUES (1,1,'live','fyers','2026-10-07 10:00:00'),
                (2,2,'sandbox','zerodha','2026-10-07 10:00:00'),(3,3,'live','fyers',NULL);
        """)
        for rid in (1, 2, 3):
            for index, kind, side, qty, price, stamp in [
                (1, "entry", "BUY", 10, 100, "2026-10-06 04:00:00"),
                (2, "exit", "SELL", 4, 110, "2026-10-07 05:00:00"),
                (3, "exit", "SELL", 6, 95, "2026-10-07 06:00:00"),
            ]:
                conn.execute(
                    "INSERT INTO sm_strategy_order VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        rid * 10 + index,
                        rid,
                        1,
                        "position-a",
                        kind,
                        f"{rid}-{index}",
                        "SBIN",
                        "NSE",
                        "CNC",
                        side,
                        qty,
                        price,
                        stamp,
                    ),
                )
        conn.commit()
    return path


def test_live_and_sandbox_reports_keep_owner_and_recorded_broker(history, tmp_path):
    before = hashlib.sha256(history.read_bytes()).hexdigest()
    for scenario, broker, sid in [("LIVE", "fyers", "sm-1"), ("PAPER", "zerodha", "sm-2")]:
        derived = reports("alice", 2026, scenario, history)
        assert len(derived) == 2
        assert {r["broker"] for r in derived} == {broker}
        assert {r["strategy_id"] for r in derived} == {sid}
        data = journal(
            "alice",
            2026,
            scenario,
            path=tmp_path / "absent.db",
            extra_reports=derived,
            charge_basis="estimated",
            session_broker="dhan",
        )
        closed = data["days"][0]
        assert closed["day"] == "2026-10-07"
        assert closed["metrics"]["trades"] == 2
        assert closed["metrics"]["gross_pnl"] == 10
        assert closed["metrics"]["charges"] > 0
        assert data["charge_profiles"][0]["broker"] == broker
        assert data["charge_profiles"][0]["broker_inferred"] is False
        assert (
            data["days"][1]["metrics"]["entries"] == 2
        )  # Two matched portions of the same entry order.
        assert data["days"][1]["metrics"]["peak_capital"] == 1000
    assert hashlib.sha256(history.read_bytes()).hexdigest() == before
    assert reports("missing", 2026, "LIVE", history) == []
    assert reports("alice", 2025, "LIVE", history) == []
    assert reports("alice", 2026, "OLHC", history) == []


def test_order_cap_allocated_once_across_partial_exits(history, tmp_path):
    from services.report_brokerage import estimate_report, order_cost, tariff

    report = reports("alice", 2026, "LIVE", history)[1]
    estimated = estimate_report(report)
    expected = sum(
        order_cost(1000, "BUY", "NSE", "delivery", "2026-10-06", tariff("fyers")).values()
    )
    assert sum(t["entry_estimated_fees"] for t in estimated["trades"]) == pytest.approx(expected)
    assert detail("alice", "sm-1-2026-10-07", history)["broker"] == "fyers"
    assert detail("bob", "sm-1-2026-10-07", history) is None


def test_short_side_and_open_remainder(history, tmp_path):
    with closing(sqlite3.connect(history)) as conn:
        conn.execute(
            "UPDATE sm_strategy_order SET action=CASE WHEN kind='entry' THEN 'SELL' ELSE 'BUY' END WHERE run_id=1"
        )
        conn.execute("DELETE FROM sm_strategy_order WHERE id=13")
        conn.commit()
    derived = reports("alice", 2026, "LIVE", history)
    data = journal("alice", 2026, "LIVE", path=tmp_path / "absent", extra_reports=derived)
    assert data["days"][0]["metrics"]["gross_pnl"] == -40
    assert data["days"][0]["metrics"]["open_trades"] == 1
    assert data["days"][0]["metrics"]["trades"] == 1


def test_unfilled_ignored_and_unprovable_exit_refused(history):
    with closing(sqlite3.connect(history)) as conn:
        conn.execute("UPDATE sm_strategy_order SET filled_qty=0 WHERE id=13")
        conn.commit()
    assert len(reports("alice", 2026, "LIVE", history)[-1]["trades"]) == 2
    with closing(sqlite3.connect(history)) as conn:
        conn.execute("UPDATE sm_strategy_order SET position_ref='different-owner' WHERE id=12")
        conn.commit()
    with pytest.raises(ValueError, match="cannot be matched"):
        reports("alice", 2026, "LIVE", history)


def test_missing_databases_not_created(tmp_path):
    path = tmp_path / "absent.db"
    assert reports("alice", 2026, "LIVE", path) == []
    assert not path.exists()
