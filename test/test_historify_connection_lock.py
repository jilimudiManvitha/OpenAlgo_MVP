"""Exercise real DuckDB ownership across threads and Windows spawn processes."""

import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import duckdb
import pytest

from database import historify_db
from utils.file_lock import exclusive_file_lock


@pytest.fixture
def database(monkeypatch, tmp_path):
    path = str(tmp_path / "history.duckdb")
    monkeypatch.setattr(historify_db, "HISTORIFY_DB_PATH", path)
    with historify_db.get_connection() as conn:
        conn.execute("CREATE TABLE progress (n INTEGER)")
        conn.execute("INSERT INTO progress VALUES (0)")
    return path


def _hold_connection(path, ready, release):
    historify_db.HISTORIFY_DB_PATH = path
    with historify_db.get_connection(max_retries=1) as conn:
        conn.execute("UPDATE progress SET n = n + 1")
        ready.set()
        assert release.wait(15), "parent did not release child"


def test_progress_updates_from_threads_are_serialized(database):
    start = threading.Barrier(6)

    def update():
        start.wait(timeout=10)
        for _ in range(5):
            with historify_db.get_connection(max_retries=1) as conn:
                conn.execute("BEGIN")
                previous = conn.execute("SELECT n FROM progress").fetchone()[0]
                time.sleep(0.005)
                conn.execute("UPDATE progress SET n = ?", [previous + 1])
                conn.execute("COMMIT")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(update) for _ in range(6)]
        for future in futures:
            future.result(timeout=30)
    with historify_db.get_connection() as conn:
        assert conn.execute("SELECT n FROM progress").fetchone() == (30,)


def test_another_process_waits_before_opening_duckdb(database):
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_hold_connection, args=(database, ready, release))
    child.start()
    try:
        assert ready.wait(15), "child never opened database"
        # Exceed the former 1.5s retry budget. Even max_retries=1 must work:
        # cooperating callers wait on the sidecar before trying DuckDB.
        timer = threading.Timer(2.0, release.set)
        timer.start()
        try:
            with historify_db.get_connection(max_retries=1) as conn:
                assert conn.execute("SELECT n FROM progress").fetchone() == (1,)
        finally:
            release.set()
            timer.join(timeout=5)
    finally:
        release.set()
        child.join(timeout=15)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        assert child.exitcode == 0
        child.close()


def test_query_failure_closes_connection_and_releases_lock(database):
    with pytest.raises(duckdb.CatalogException):
        with historify_db.get_connection() as conn:
            conn.execute("SELECT * FROM nonexistent_table")
    # A raw connection can open afterward; the prior connection was closed.
    with duckdb.connect(database) as conn:
        assert conn.execute("SELECT n FROM progress").fetchone() == (0,)
    with exclusive_file_lock(database + ".lock", timeout=0):
        pass


def test_timeout_releases_waiter_handle_and_preserves_owner(tmp_path):
    path = tmp_path / "database.lock"
    with exclusive_file_lock(path):
        with pytest.raises(TimeoutError, match="waiting for database lock"):
            with exclusive_file_lock(path, timeout=0.05):
                pytest.fail("second owner entered")
        with pytest.raises(TimeoutError):
            with exclusive_file_lock(path, timeout=0):
                pytest.fail("timed-out waiter released the owner's lock")
    with exclusive_file_lock(path, timeout=0):
        pass


def test_connect_failure_releases_lock(database, monkeypatch):
    def fail(*args, **kwargs):
        raise duckdb.IOException("external application owns database")

    monkeypatch.setattr(duckdb, "connect", fail)
    with pytest.raises(duckdb.IOException):
        with historify_db.get_connection(max_retries=1):
            pytest.fail("connection should fail")
    with exclusive_file_lock(database + ".lock", timeout=0):
        pass


@pytest.mark.parametrize("export_format", ["parquet", "zip"])
def test_daily_aggregated_export_reuses_its_connection(
    database, monkeypatch, tmp_path, export_format
):
    import pandas as pd

    monkeypatch.setattr(historify_db, "HISTORIFY_DB_LOCK_TIMEOUT", 0.1)
    monkeypatch.setattr(historify_db, "_get_market_open_seconds", lambda exchange: 33300)
    historify_db.init_database()
    frame = pd.DataFrame(
        {
            "timestamp": [1704067200],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1000],
        }
    )
    historify_db.upsert_market_data(frame, "TEST", "NSE", "D")
    output = str(tmp_path / f"weekly.{export_format}")
    if export_format == "parquet":
        success, message, count = historify_db.export_to_parquet(output, interval="W")
        assert success, message
        assert len(pd.read_parquet(output)) == 1
    else:
        success, message, count = historify_db.export_to_zip(output, intervals=["W"])
        assert success, message
        assert len(pd.read_csv(output)) == 1
    assert count == 1
