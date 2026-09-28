import ast
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from paper_runtime import Candles, candidate, close_position


def test_forming_signal_uses_current_wick_and_vwap():
    signal = (0, 101, 99)
    closes = deque([100.0] * 20, maxlen=20)
    bar = [60, 101, 103, 101, 103, 10]
    assert candidate(signal, bar, 100, closes, 100000, 1000)
    assert not candidate(signal, [60, 101, 103, 99, 103, 10], 100, closes, 100000, 1000)
    assert not candidate(signal, bar, 100, closes, 110000, 1000)
    assert not candidate(signal, [60, 101, 103, 101, 103, 0], 100, closes, 100000, 1000)
    assert not candidate(signal, [60, 101, 101, 101, 101, 10], 100, closes, 100000, 1000)


def test_vwap_test_detects_disabled_guard():
    import inspect

    import paper_runtime

    source = inspect.getsource(candidate)
    assert source.count("return price > upper and price > vw") == 1
    namespace = dict(paper_runtime.__dict__)
    exec(source.replace("return price > upper and price > vw", "return price > upper"), namespace)
    original = test_forming_signal_uses_current_wick_and_vwap.__globals__["candidate"]
    try:
        test_forming_signal_uses_current_wick_and_vwap.__globals__["candidate"] = namespace[
            "candidate"
        ]
        with pytest.raises(AssertionError):
            test_forming_signal_uses_current_wick_and_vwap()
    finally:
        test_forming_signal_uses_current_wick_and_vwap.__globals__["candidate"] = original


def test_feed_gap_disables_new_entries_and_window_bounded():
    raw = np.array([[i * 60, 100, 101, 99, 100, 10] for i in range(30)], float)
    c = Candles(raw)
    c.tick(1800, 102, 10)
    c.tick(1980, 103, 20)
    assert c.disabled
    for i in range(100):
        c.tick(2040 + i * 60, 104, 30 + i)
    assert len(c.closes) == 20


class Sink:
    def __init__(self, race=False):
        self.race = race
        self.cancelled = False
        self.placed = []

    def status(self, oid):
        if oid == "target":
            return {
                "order_status": "complete"
                if self.race and self.cancelled
                else ("cancelled" if self.cancelled else "open"),
                "average_price": 110,
            }
        return {"order_status": "complete", "filled_quantity": 10, "average_price": 95}

    def cancel(self, oid):
        self.cancelled = True
        if self.race:
            raise RuntimeError("Target filled first")

    def place(self, *args):
        self.placed.append(args)
        return "exit"


def test_stop_cancels_target_before_exit():
    sink = Sink()
    p = {"target_order": "target", "quantity": 10, "phase": "open"}
    saved = []
    close_position(sink, p, "TEST", {"ltp": 95}, lambda: saved.append(dict(p)))
    assert sink.cancelled and p["phase"] == "closed"
    assert len(sink.placed) == 1
    assert saved[0]["phase"] == "exit_pending"


def test_target_fill_during_cancel_does_not_sell_twice():
    sink = Sink(race=True)
    p = {"target_order": "target", "quantity": 10, "phase": "open"}
    close_position(sink, p, "TEST", {"ltp": 95}, lambda: None)
    assert p["phase"] == "closed" and p["reason"] == "TARGET"
    assert sink.placed == []


def test_no_live_order_route_in_runtime():
    tree = ast.parse((HERE / "paper_runtime.py").read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert "services.place_order_service" not in imports
    calls = [
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    ]
    assert not {
        "placeorder",
        "placesmartorder",
        "cancelorder",
        "closeposition",
        "analyzertoggle",
    } & set(calls)


def test_sandbox_adapter_passes_key_and_cleans_sessions(monkeypatch):
    import types

    from paper_runtime import Sandbox

    cleaned = []
    for module in ["database.auth_db", "database.sandbox_db", "database.symbol"]:
        monkeypatch.setitem(
            sys.modules,
            module,
            types.SimpleNamespace(
                db_session=types.SimpleNamespace(remove=lambda m=module: cleaned.append(m))
            ),
        )
    seen = []

    def place(order, key, original, prefetched_quote):
        seen.append((order, key, prefetched_quote))
        return True, {"mode": "analyze", "orderid": "paper-id"}, 200

    monkeypatch.setitem(
        sys.modules, "services.sandbox_service", types.SimpleNamespace(sandbox_place_order=place)
    )
    assert Sandbox("test-key").place("TEST", "BUY", 10, {"ltp": 100}) == "paper-id"
    assert seen[0][0]["strategy"] == "Narasimha_HA1m_Sep25_PAPER"
    assert seen[0][1] == "test-key" and len(cleaned) == 3
    with pytest.raises(RuntimeError):
        Sandbox("test-key").call(lambda: (True, {"mode": "live"}, 200))
    assert len(cleaned) == 6
