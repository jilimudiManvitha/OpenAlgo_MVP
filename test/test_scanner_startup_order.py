"""Startup ordering without importing app.py or starting saved strategies."""

import ast
import asyncio
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, Mock

import pytest

from websocket_proxy import app_integration, server


def test_scanner_is_started_after_proxy_instead_of_during_app_construction():
    tree = ast.parse(Path("app.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    scanner = [node for node in calls if node.func.id == "coordinator"]
    proxy = [node for node in calls if node.func.id == "start_websocket_proxy"]
    assert len(scanner) == len(proxy) == 1
    assert scanner[0].lineno > proxy[0].lineno
    factory = next(node for node in tree.body if getattr(node, "name", None) == "create_app")
    assert scanner[0] not in list(ast.walk(factory))


def test_threaded_start_waits_until_listener_is_ready(monkeypatch):
    ready = Event()
    finish = Event()

    class Proxy:
        def __init__(self, **kwargs):
            pass

        async def start(self, on_ready=None):
            await asyncio.sleep(0.05)
            ready.set()
            if on_ready:
                on_ready()
            while not finish.is_set():
                await asyncio.sleep(0.001)

    monkeypatch.setattr(server, "WebSocketProxy", Proxy)
    monkeypatch.setattr(app_integration, "_eventlet_active", lambda: False)
    monkeypatch.setattr(app_integration.atexit, "register", lambda *args: None)
    monkeypatch.setattr(app_integration.signal, "signal", lambda *args: None)
    monkeypatch.setattr(app_integration, "_websocket_proxy_instance", None)
    monkeypatch.setattr(app_integration, "_websocket_thread", None)
    thread = app_integration.start_websocket_server()
    try:
        assert ready.is_set(), "Startup returned before the listener was ready"
    finally:
        finish.set()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("fails", [True, False])
def test_startup_failure_or_timeout_does_not_block_flask(monkeypatch, fails):
    finish = Event()
    startup_event = Mock(wraps=Event())
    if not fails:
        startup_event.wait.return_value = False

    class Proxy:
        def __init__(self, **kwargs):
            pass

        async def start(self, on_ready=None):
            if fails:
                raise OSError("fixture startup failure")
            while not finish.is_set():
                await asyncio.sleep(0.001)

    monkeypatch.setattr(server, "WebSocketProxy", Proxy)
    monkeypatch.setattr(app_integration, "_eventlet_active", lambda: False)
    monkeypatch.setattr(app_integration.atexit, "register", lambda *args: None)
    monkeypatch.setattr(app_integration.signal, "signal", lambda *args: None)
    monkeypatch.setattr(app_integration, "_websocket_proxy_instance", None)
    monkeypatch.setattr(app_integration, "_websocket_thread", None)
    # Patch only the module's reference, leaving real thread internals intact.
    from threading import Thread
    from types import SimpleNamespace

    monkeypatch.setattr(
        app_integration,
        "_original_threading",
        SimpleNamespace(Event=lambda: startup_event, Thread=Thread),
    )
    thread = app_integration.start_websocket_server()
    try:
        startup_event.wait.assert_called_once_with(timeout=10)
        if fails:
            assert startup_event.is_set()
    finally:
        finish.set()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("bind_fails", [False, True])
def test_proxy_reports_ready_only_after_successful_bind(monkeypatch, bind_fails):
    proxy = server.WebSocketProxy.__new__(server.WebSocketProxy)
    proxy.host, proxy.port = "127.0.0.1", 0
    proxy.handle_client = AsyncMock()
    proxy.zmq_listener = AsyncMock()
    proxy._stats_file_writer = AsyncMock()
    proxy.stop = AsyncMock()
    events = []

    async def serve(*args, **kwargs):
        events.append("bind")
        if bind_fails:
            raise OSError("fixture bind failure")
        return Mock()

    def on_ready():
        events.append("ready")
        proxy.running = False

    monkeypatch.setattr(server.websockets, "serve", serve)
    monkeypatch.setattr(server.threading, "main_thread", lambda: None)

    if bind_fails:
        with pytest.raises(OSError, match="fixture bind failure"):
            asyncio.run(proxy.start(on_ready=on_ready))
        assert events == ["bind"]
    else:
        asyncio.run(proxy.start(on_ready=on_ready))
        assert events == ["bind", "ready"]
        proxy.stop.assert_awaited_once()
