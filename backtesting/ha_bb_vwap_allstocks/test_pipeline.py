"""Synthetic-only source, accounting, resumption and dashboard checks."""

import json
from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pytest

from .configuration import Costs, file_hash, load_config
from .dashboard import Reports
from .demo import create_demo
from .runner import run
from .source import Source, bounds
from .statistics import DayAccumulator, combine, period
from .storage import Store, read_connection


def empty_day(day, equity):
    acc = DayAccumulator(day)
    acc.equity[: len(equity)] = equity
    acc.equity[len(equity) :] = equity[-1]
    acc.sums["net_pnl"] = equity[-1]
    return acc.finish()[0]


def test_period_boundaries():
    assert period("2022-01-01", "week")[1:] == ("2021-12-27", "2022-01-02")
    assert period("2024-02-29", "month")[2] == "2024-02-29"
    assert period("2022-06-30", "half_year")[1:] == ("2022-01-01", "2022-06-30")
    assert period("2022-07-01", "quarter")[1:] == ("2022-07-01", "2022-09-30")
    assert period("2021-12-31", "five_year")[1:] == ("2017-01-01", "2021-12-31")
    assert period("2022-01-01", "five_year")[1:] == ("2022-01-01", "2026-12-31")


def test_cross_day_drawdown_exceeds_each_daily_drawdown():
    a = empty_day("2020-12-31", [0, 100, 40])
    b = empty_day("2021-01-04", [0, -70, -20])
    stats = combine([a, b], 100000)
    assert max(a["max_drawdown"], b["max_drawdown"]) == 70
    assert stats["max_drawdown"] == 130
    assert stats["drawdown_peak_time"].startswith("2020-12-31")
    assert stats["drawdown_trough_time"].startswith("2021-01-04")
    assert stats["net_pnl"] == 20


def test_period_resets_reference_equity():
    a = empty_day("2020-12-31", [0, 100, 40])
    b = empty_day("2021-01-04", [0, -70, -20])
    assert combine([b], 100000)["max_drawdown"] == 70
    assert combine([a, b], 100000)["max_drawdown"] == 130


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    folder = tmp_path_factory.mktemp("synthetic_historify")
    source = folder / "source.duckdb"
    db = duckdb.connect(str(source))
    try:
        db.execute(
            "CREATE TABLE market_data(symbol VARCHAR,exchange VARCHAR,interval VARCHAR,timestamp BIGINT,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume BIGINT)"
        )
        rows = []
        for day in ("2020-12-31", "2021-01-04"):
            start, _ = bounds(day)
            for i in range(375):
                value = (
                    100
                    + i * 0.015
                    + (4 if i >= 40 else 0)
                    - (9 if i >= 170 else 0)
                    + (7 if i >= 260 else 0)
                )
                rows.append(
                    (
                        "TEST_EQ",
                        "NSE",
                        "1m",
                        int((start + timedelta(minutes=i)).timestamp()),
                        value,
                        value + 0.2,
                        value - 0.05,
                        value + 0.1,
                        20000,
                    )
                )
        db.executemany("INSERT INTO market_data VALUES(?,?,?,?,?,?,?,?,?)", rows)
    finally:
        db.close()
    config = load_config()
    config.update(
        source=str(source),
        output=str(folder / "result"),
        start="2020-12-31",
        end="2021-01-04",
        symbols=["TEST_EQ"],
        strategy_ids=["S059", "S261"],
        paths=["OLHC"],
        metadata_database=None,
    )
    original = file_hash(source)
    first = run(config, max_days=1, demo=True)
    assert first["completed_days"] == 1
    second = run(config, resume=True, demo=True)
    assert second["completed_days"] == 2
    assert file_hash(source) == original
    return config


def test_read_only_source_and_warmup(synthetic_run):
    with Source(synthetic_run) as source:
        with pytest.raises(duckdb.Error):
            source.db.execute("DELETE FROM market_data")
        history, bars, audit = source.session("TEST_EQ", "2021-01-04")
        assert len(bars) == 375 and len(history) == 375
        assert all(b.start.date().isoformat() < "2021-01-04" for b in history)
        assert audit["missing_minutes"] == 0


def test_real_engine_on_fixture_and_resume(synthetic_run):
    reports = Reports(synthetic_run["output"])
    q = {"strategy": "S059", "path": "OLHC", "group": "year"}
    report = reports.report(q)
    assert len(report["periods"]) == 2
    assert report["summary"]["trades"] > 0
    assert not report["benchmark"]["available"]
    with read_connection(reports.path) as db:
        net, fees = db.execute(
            "SELECT sum(net),sum(fees) FROM trades WHERE strategy='S059'"
        ).fetchone()
    assert np.isclose(net, report["summary"]["net_pnl"])
    assert np.isclose(fees, report["summary"]["fees"])
    assert run(synthetic_run, resume=True, demo=True)["new_days"] == 0
    changed = {**synthetic_run, "slippage": 0.001}
    with pytest.raises(ValueError, match="Resume refused"):
        run(changed, resume=True, demo=True)


def test_atomic_day_rollback(tmp_path):
    with Store(tmp_path / "r.sqlite", {"test": True}, []) as store:
        with pytest.raises(RuntimeError), store.db:
            store.db.execute("INSERT INTO days VALUES('2020-01-01',1,1,0,NULL,'test')")
            raise RuntimeError("simulated interrupted day")
        assert store.complete_days() == set()


def test_effective_cost_schedule_rejects_missing_date(tmp_path):
    config = load_config()
    path = tmp_path / "fees.csv"
    keys = list(config["fixed_research_fees"])
    path.write_text(
        "effective_from,effective_to,"
        + ",".join(keys)
        + "\n2020-01-01,2020-12-31,"
        + ",".join(str(config["fixed_research_fees"][k]) for k in keys)
        + "\n"
    )
    config["fees_csv"] = str(path)
    costs = Costs(config)
    assert costs.breakdown("2020-02-01", "buy", 1000, 100)["brokerage"] == 20
    with pytest.raises(ValueError, match="exactly once"):
        costs.rates("2021-01-01")


def test_unrun_dashboard_does_not_create_result_or_open_source(tmp_path):
    reports = Reports(tmp_path / "absent")
    assert reports.meta()["state"] == "not_run"
    assert not reports.path.exists()


def test_demo_time_lookup_partial_exits_and_exports(tmp_path):
    create_demo(tmp_path / "demo")
    reports = Reports(tmp_path / "demo")
    q = {"strategy": "D001", "path": "OLHC", "day": "2017-07-03", "at": "10:40:00"}
    current = reports.open_positions(q)
    assert current["open_trades"] == 2
    assert sorted(p["remaining"] for p in current["positions"]) == [50, 75]
    assert reports.open_positions({**q, "at": "15:30:00"})["open_trades"] == 0
    for group in ("day", "week", "month", "quarter", "half_year", "year", "five_year", "all"):
        result = reports.report({**q, "group": group})
        assert np.isclose(
            sum(r["net_pnl"] for r in result["periods"]), result["summary"]["net_pnl"]
        )
        assert sum(r["trades"] for r in result["periods"]) == result["summary"]["trades"]
    assert len(list(reports.export_rows({**q, "kind": "fills"}))) == 48
