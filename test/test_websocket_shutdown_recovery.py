"""Offline reproductions of October 7 closed-loop shutdown failures."""

import asyncio
import gc
import threading
import warnings
from unittest.mock import Mock

import pytest

from services.websocket_client import WebSocketClient


def test_disconnect_is_idempotent_after_event_loop_has_closed():
    client = WebSocketClient("fixture")
    client.loop = asyncio.new_event_loop()
    client.loop.close()
    client.ws = Mock()
    client.connected = client.authenticated = True
    client.active_subscriptions = {"NSE:ABC": {"Quote"}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        client.disconnect()
        client.disconnect()
        gc.collect()
    assert not client.connected and not client.authenticated
    assert not client.active_subscriptions
    assert not [w for w in caught if "never awaited" in str(w.message)]


def test_disconnect_handles_loop_closing_between_check_and_schedule():
    client = WebSocketClient("fixture")
    client.loop = Mock()
    client.loop.is_closed.return_value = False
    client.loop.is_running.return_value = True

    def closed_during_schedule(*_):
        client.loop.is_closed.return_value = True
        raise RuntimeError("Event loop is closed")

    client.loop.call_soon_threadsafe.side_effect = closed_during_schedule
    client.ws = Mock()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        client.disconnect()
        gc.collect()
    assert not [w for w in caught if "never awaited" in str(w.message)]


def test_running_loop_closes_socket_and_finishes_thread():
    client = WebSocketClient("fixture")
    ready = threading.Event()
    closed = threading.Event()

    class Socket:
        async def close(self):
            closed.set()

    async def run():
        client.ws = Socket()
        ready.set()
        while not closed.is_set():
            await asyncio.sleep(0.001)

    client._connect_and_run = run
    client.running = True
    client.thread = threading.Thread(target=client._run_event_loop)
    client.thread.start()
    assert ready.wait(2)
    client.disconnect()
    client.thread.join(2)
    assert closed.is_set() and not client.thread.is_alive()
    assert client.loop.is_closed()
    client.disconnect()
