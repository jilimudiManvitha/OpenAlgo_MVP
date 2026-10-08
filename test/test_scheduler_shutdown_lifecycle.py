"""Exercise production shutdown functions with real, harmless APScheduler jobs.

Load just the lifecycle functions so importing the Python blueprint cannot
restore the operator's processes/configuration or start trading jobs.
"""

import ast
import logging
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == set(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), path, "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "kind", ["strategy_module", "python_strategy", "squareoff", "chartink", "flow", "historify"]
)
def test_shutdown_joins_active_jobs_and_scheduler_without_holding_locks(kind):
    scheduler = BackgroundScheduler()
    lock = threading.Lock()
    namespace = {
        "logger": logging.getLogger(__name__),
        "_lock": lock,
        "PROCESS_LOCK": lock,
        "_scheduler_lock": lock,
    }
    if kind == "strategy_module":
        namespace["_scheduler"] = scheduler
        load_functions("services/strategy_module/scheduler.py", ["shutdown"], namespace)
        stop = namespace["shutdown"]
        singleton = "_scheduler"
    elif kind == "python_strategy":
        namespace["SCHEDULER"] = scheduler
        load_functions("blueprints/python_strategy.py", ["shutdown_scheduler"], namespace)
        stop = namespace["shutdown_scheduler"]
        singleton = "SCHEDULER"
    elif kind == "squareoff":
        namespace["_scheduler"] = scheduler
        load_functions("sandbox/squareoff_thread.py", ["stop_squareoff_scheduler"], namespace)
        stop = namespace["stop_squareoff_scheduler"]
        singleton = "_scheduler"
    elif kind == "chartink":
        namespace["sys"] = SimpleNamespace(
            modules={"blueprints.chartink": SimpleNamespace(scheduler=scheduler)}
        )
        load_functions("utils/shutdown.py", ["_stop_chartink_scheduler"], namespace)
        stop = namespace["_stop_chartink_scheduler"]
    else:
        owner = SimpleNamespace(_scheduler=scheduler, _initialized=True)
        load_functions(f"services/{kind}_scheduler_service.py", ["shutdown"], namespace)

        def stop():
            namespace["shutdown"](owner)

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
        if kind in ("flow", "historify"):
            assert owner._scheduler is None and not owner._initialized
        elif kind != "chartink":
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
    from utils.server_startup import allow_unsafe_werkzeug

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
        "allow_unsafe_werkzeug": allow_unsafe_werkzeug,
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


@pytest.mark.parametrize("failed", [None, "squareoff", "chartink", "flow", "historify"])
def test_runtime_stops_all_schedulers_even_when_one_fails(monkeypatch, failed):
    from utils import shutdown as shutdown_mod

    calls = []

    def stop(name):
        calls.append(name)
        if name == failed:
            raise RuntimeError("simulated shutdown failure")

    # Real runtime helpers, fake already-loaded owners: no trading services start.
    monkeypatch.setitem(
        sys.modules,
        "sandbox.squareoff_thread",
        SimpleNamespace(stop_squareoff_scheduler=lambda: (stop("squareoff") is None, "stopped")),
    )
    monkeypatch.setitem(
        sys.modules,
        "blueprints.chartink",
        SimpleNamespace(
            scheduler=SimpleNamespace(
                running=True,
                pause=lambda: None,
                remove_all_jobs=lambda: None,
                shutdown=lambda wait: stop("chartink"),
            )
        ),
    )
    for name in ("flow", "historify"):
        owner = SimpleNamespace(shutdown=lambda name=name: stop(name))
        monkeypatch.setitem(
            sys.modules,
            f"services.{name}_scheduler_service",
            SimpleNamespace(**{f"{name}_scheduler": owner}),
        )
    monkeypatch.setitem(
        sys.modules,
        "services.strategy_module.scheduler",
        SimpleNamespace(shutdown=lambda: stop("strategy")),
    )
    monkeypatch.setitem(
        sys.modules,
        "blueprints.python_strategy",
        SimpleNamespace(shutdown_scheduler=lambda: stop("python")),
    )
    monkeypatch.setattr(shutdown_mod, "_shutdown_done", False)
    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", lambda: stop("health"))
    monkeypatch.setattr(shutdown_mod, "_remove_all_scoped_sessions", lambda: stop("sessions"))
    shutdown_mod.shutdown_runtime()
    shutdown_mod.shutdown_runtime()
    assert calls == [
        "squareoff",
        "chartink",
        "flow",
        "historify",
        "strategy",
        "python",
        "health",
        "sessions",
    ]


@pytest.mark.parametrize("name", ["flow", "historify"])
def test_persistent_scheduler_shutdown_keeps_saved_jobs(name):
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

    from database.engine_factory import create_db_engine

    namespace = {"logger": logging.getLogger(__name__)}
    load_functions(f"services/{name}_scheduler_service.py", ["shutdown"], namespace)
    # Explicit workspace location: never use the operator's database/job store.
    with tempfile.TemporaryDirectory(prefix="scheduler-test-", dir=ROOT / ".development") as folder:
        url = "sqlite:///" + (Path(folder) / "jobs.db").as_posix()

        def create_scheduler():
            return BackgroundScheduler(
                jobstores={"default": SQLAlchemyJobStore(engine=create_db_engine(url))}
            )

        scheduler = create_scheduler()
        scheduler.add_job(
            print,
            "date",
            run_date=datetime.now() + timedelta(days=1),
            args=["test job must not execute"],
            id="preserved-job",
        )
        scheduler.start(paused=True)
        owner = SimpleNamespace(_scheduler=scheduler, _initialized=True)
        try:
            namespace["shutdown"](owner)
            namespace["shutdown"](owner)
            assert not scheduler.running
            assert owner._scheduler is None and not owner._initialized
            restored = create_scheduler()
            restored.start(paused=True)
            try:
                assert restored.get_job("preserved-job") is not None
            finally:
                restored.shutdown()
        finally:
            if scheduler.running:
                scheduler.shutdown()


@pytest.mark.parametrize("name", ["flow", "historify"])
def test_persistent_shutdown_waits_for_dispatch_bookkeeping(name, monkeypatch):
    from apscheduler.schedulers.base import STATE_PAUSED

    scheduler = BackgroundScheduler()
    owner = SimpleNamespace(_scheduler=scheduler, _initialized=True)
    namespace = {"logger": logging.getLogger(__name__)}
    load_functions(f"services/{name}_scheduler_service.py", ["shutdown"], namespace)
    removing, release_dispatch, release_job, paused = (threading.Event() for _ in range(4))
    original_remove, original_pause = scheduler.remove_job, scheduler.pause

    def remove(*args, **kwargs):
        removing.set()
        assert release_dispatch.wait(5)
        return original_remove(*args, **kwargs)

    def pause():
        original_pause()
        paused.set()

    monkeypatch.setattr(scheduler, "remove_job", remove)
    monkeypatch.setattr(scheduler, "pause", pause)
    scheduler.add_job(lambda: release_job.wait(5))
    scheduler.start()
    stopper = threading.Thread(target=lambda: namespace["shutdown"](owner))
    try:
        assert removing.wait(5)
        stopper.start()
        assert paused.wait(5)
        # The old shutdown changed state to STOPPED while dispatch still needed
        # remove_job(), which then searched pending jobs and raised JobLookupError.
        stopper.join(timeout=0.1)
        assert scheduler.state == STATE_PAUSED
        release_dispatch.set()
        release_job.set()
        stopper.join(timeout=5)
        assert not stopper.is_alive()
        assert not scheduler.running
    finally:
        release_dispatch.set()
        release_job.set()
        if stopper.ident is not None:
            stopper.join(timeout=5)
        if scheduler.running:
            scheduler.shutdown()
