"""Closing-session regressions: fake orders/processes, isolated report database."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.scanner_strategy_reports import ReportStore
from strategies.top_gain_volumes.runtime import IST, SHUTDOWN_GRACE_SECONDS, stopping_phase


@pytest.mark.parametrize("quantity", [0, 17, -17])
def test_squareoff_does_not_submit_an_order_for_an_already_closed_position(monkeypatch, quantity):
    from sandbox import order_manager, position_manager

    query = Mock()
    query.filter_by.return_value.first.return_value = SimpleNamespace(quantity=quantity)
    monkeypatch.setattr(position_manager, "SandboxPositions", SimpleNamespace(query=query))
    orders = Mock()
    orders.return_value.place_order.return_value = (True, {"orderid": "test-only"}, 200)
    monkeypatch.setattr(order_manager, "OrderManager", orders)
    manager = position_manager.PositionManager.__new__(position_manager.PositionManager)
    manager.user_id = "test-only"
    ok, response, code = manager.close_position("MCX", "NSE", "MIS")
    assert ok and code == 200
    if quantity == 0:
        assert response.get("already_closed") and "orderid" not in response
        orders.assert_not_called()
    else:
        submitted = orders.return_value.place_order.call_args.args[0]
        assert submitted["quantity"] == 17
        assert submitted["action"] == ("SELL" if quantity > 0 else "BUY")


def test_stopping_snapshot_is_durable_before_slow_batch_and_deadline_does_not_extend(tmp_path):
    store = ReportStore(tmp_path / "reports.db")
    report = {
        "id": "test",
        "day": "2026-10-07",
        "status": "running",
        "trades": [],
        "paths": ["PAPER"],
    }
    now = datetime(2026, 10, 7, 15, 0, tzinfo=IST)
    try:
        deadline = stopping_phase(report, now, 100, None, lambda: store.save("test", report))
        assert deadline == 160 and SHUTDOWN_GRACE_SECONDS == 60
        saved = store.get("test", "test")
        assert saved is not None
        assert saved["status"] == "stopping — reconciling positions"
        assert saved["updated_at"] == now.isoformat()
        assert stopping_phase(report, now, 110, deadline, Mock()) == deadline
        before = {**report, "status": "running"}
        persist = Mock()
        assert stopping_phase(before, now.replace(hour=14), 100, None, persist) is None
        persist.assert_not_called()
    finally:
        store.close()


@pytest.mark.parametrize(
    "filename",
    [
        "Nifty500_Scanner_Fixed_3R_10K_5m.py",
        "premium_positional_next_week.py",
        "user_custom.py",
    ],
)
@pytest.mark.parametrize("kind", ["popen", "restored", "orphan"])
def test_scheduler_passes_sufficient_grace_through_every_stop_path(monkeypatch, filename, kind):
    from blueprints import python_strategy as scheduler
    from test.test_python_strategy_stop_lock import FakePopen

    process = FakePopen() if kind == "popen" else SimpleNamespace(terminate=lambda: None)
    config = {"file_path": "/test/" + filename, "pid": 424242, "is_running": True}
    monkeypatch.setattr(
        scheduler,
        "RUNNING_STRATEGIES",
        {}
        if kind == "orphan"
        else {
            "test": {"process": process, "pid": 424242},
        },
    )
    monkeypatch.setattr(scheduler, "STRATEGY_CONFIGS", {"test": config})
    monkeypatch.setattr(scheduler, "STOPPING_STRATEGIES", set())
    for name in (
        "save_configs",
        "broadcast_status_update",
        "cleanup_strategy_logs",
        "close_log_handle_safely",
    ):
        monkeypatch.setattr(scheduler, name, Mock())
    monkeypatch.setattr(scheduler, "get_schedule_status", lambda _: ("stopped", "Stopped"))
    monkeypatch.setattr(scheduler, "check_process_status", Mock(side_effect=[True, False]))
    terminate = Mock(return_value=True)
    for name in (
        "terminate_popen_safely",
        "terminate_psutil_process_safely",
        "terminate_process_cross_platform",
    ):
        monkeypatch.setattr(scheduler, name, terminate)
    ok, _ = scheduler.stop_strategy_process("test")
    assert ok
    timeout = terminate.call_args.kwargs["terminate_timeout"]
    assert timeout == (5 if filename == "user_custom.py" else 90)
    if filename != "user_custom.py":
        assert timeout >= SHUTDOWN_GRACE_SECONDS + 30
