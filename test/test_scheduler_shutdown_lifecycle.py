"""Exercise production shutdown functions with real, harmless APScheduler jobs.

Load just the lifecycle functions so importing the Python blueprint cannot
restore the operator's processes/configuration or start trading jobs.
"""

import ast
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == set(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), path, "exec"), namespace)
    return namespace


@pytest.mark.parametrize("kind", ["strategy_module", "python_strategy"])
def test_shutdown_joins_active_jobs_and_scheduler_without_holding_locks(kind):
    scheduler = BackgroundScheduler()
    lock = threading.Lock()
    namespace = {"logger": logging.getLogger(__name__), "_lock": lock, "PROCESS_LOCK": lock}
    if kind == "strategy_module":
        namespace["_scheduler"] = scheduler
        load_functions("services/strategy_module/scheduler.py", ["shutdown"], namespace)
        stop = namespace["shutdown"]
        singleton = "_scheduler"
    else:
        namespace["SCHEDULER"] = scheduler
        load_functions("blueprints/python_strategy.py", ["shutdown_scheduler"], namespace)
        stop = namespace["shutdown_scheduler"]
        singleton = "SCHEDULER"

    started, release, completed, stopped = (threading.Event() for _ in range(4))

    def job():
        started.set()
        assert release.wait(5)
        with lock:
            completed.set()

    def shutdown():
        stop()
        stopped.set()

    scheduler.add_job(job)
    scheduler.start()
    scheduler_thread = scheduler._thread
    stopper = threading.Thread(target=shutdown, daemon=True)
    try:
        assert started.wait(5)
        workers = list(scheduler._executors["default"]._pool._threads)
        stopper.start()
        assert not stopped.wait(0.1), "shutdown returned while a job was still running"
        release.set()
        assert stopped.wait(5), "shutdown deadlocked waiting for a job"
        assert completed.is_set()
        assert not scheduler_thread.is_alive()
        assert all(not worker.is_alive() for worker in workers)
        assert namespace[singleton] is None
        stop()  # repeated cleanup is harmless
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(timeout=5)
        if scheduler.running:
            scheduler.shutdown()


def test_python_scheduler_stops_before_process_cleanup():
    calls = []
    namespace = {
        "logger": logging.getLogger(__name__),
        "PROCESS_LOCK": threading.RLock(),
        "RUNNING_STRATEGIES": {"example": object()},
        "shutdown_scheduler": lambda: calls.append("scheduler"),
        "stop_strategy_process": lambda sid: calls.append(sid),
    }
    load_functions("blueprints/python_strategy.py", ["cleanup_on_exit"], namespace)
    namespace["cleanup_on_exit"]()
    assert calls == ["scheduler", "example"]


@pytest.mark.parametrize("error", [None, RuntimeError, SystemExit, KeyboardInterrupt])
def test_server_finally_runs_cleanup_on_every_exit(monkeypatch, error):
    from utils import shutdown as shutdown_mod

    calls = []
    monkeypatch.setattr(shutdown_mod, "shutdown_runtime", lambda: calls.append("shutdown"))

    def run(*args, **kwargs):
        calls.append("run")
        if error:
            raise error()

    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    main = tree.body[-1]
    final_block = main.body[-1]
    assert isinstance(final_block, ast.Try) and final_block.finalbody
    code = compile(ast.Module(body=[final_block], type_ignores=[]), "app.py", "exec")
    namespace = {
        "socketio": SimpleNamespace(run=run),
        "app": object(),
        "host_ip": "localhost",
        "port": 0,
        "debug": False,
        "reloader_options": {},
    }
    if error:
        with pytest.raises(error):
            exec(code, namespace)
    else:
        exec(code, namespace)
    assert calls == ["run", "shutdown"]


def test_shutdown_helpers_only_touch_already_loaded_services():
    calls = []
    modules = {}
    namespace = {"sys": SimpleNamespace(modules=modules)}
    load_functions(
        "utils/shutdown.py",
        ["_stop_strategy_module_scheduler", "_stop_python_strategy_scheduler"],
        namespace,
    )
    for name in ("_stop_strategy_module_scheduler", "_stop_python_strategy_scheduler"):
        namespace[name]()
    assert not calls and not modules
    modules["services.strategy_module.scheduler"] = SimpleNamespace(
        shutdown=lambda: calls.append("strategy")
    )
    modules["blueprints.python_strategy"] = SimpleNamespace(
        shutdown_scheduler=lambda: calls.append("python")
    )
    namespace["_stop_strategy_module_scheduler"]()
    namespace["_stop_python_strategy_scheduler"]()
    assert calls == ["strategy", "python"]
