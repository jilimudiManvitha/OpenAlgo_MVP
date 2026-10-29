"""Annual collector behavior with fake broker responses and temporary archives."""

import importlib
import json
from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace

import pytest


@pytest.fixture
def collector(tmp_path, monkeypatch):
    from strategies.nifty_options import history as h
    from strategies.nifty_options import data_probe
    from broker.fyers.api import data_budget

    monkeypatch.syspath_prepend(str(h.ROOT / ".development/options-year"))
    module = importlib.import_module("collect")
    out = tmp_path / "annual"
    out.mkdir()
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "source_index", lambda _: defaultdict(list))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(h, "ROOT", tmp_path)
    monkeypatch.setattr(h, "CACHE", tmp_path / "cache")
    # Simulate a contract that was unexpired when its catalogue was saved.
    c = dict(
        symbol="FIXTURE_OPTION",
        start="2025-10-09",
        end="2025-10-14",
        expiry="2025-10-14",
        expired=False,
    )
    h.atomic_json(out / "manifest.json", {"contracts": [c]})
    day = module.START
    while day <= module.END:
        end = min(day + timedelta(days=99), module.END)
        h.write_candles(h.cache_file(module.INDEX, str(day), str(end)), {"candles": []})
        day = end + timedelta(days=1)
    calls = []
    state = {"count": 1000, "cooldown": 0}
    monkeypatch.setattr(data_budget, "read", lambda *_: state)
    monkeypatch.setattr(data_budget, "state_path", lambda: tmp_path / "budget.json")
    monkeypatch.setattr(data_budget, "plan", lambda: "standard")
    monkeypatch.setattr(data_probe, "active_login", lambda: ("fixture", "fixture"))

    def fetch(*args):
        calls.append(args)
        state["count"] += 1
        return {
            "candles": [dict(timestamp=1759981500, open=50, high=51, low=49, close=50, volume=10)]
        }

    monkeypatch.setattr(data_probe, "expired_call", fetch)

    def reject_regular(*args):
        raise AssertionError("Expired contract incorrectly routed to regular history")

    monkeypatch.setattr(h, "regular_history", reject_regular)
    return module, out, calls, state


@pytest.mark.parametrize("count,cap,status", [(3800, 4000, "blocked"), (1000, 0, "paused")])
def test_no_broker_call_when_budget_or_batch_cap_reached(collector, count, cap, status):
    module, out, calls, state = collector
    state["count"] = count
    module.collect(SimpleNamespace(prepare_only=False, reserve=1000, max_requests=cap))
    progress = json.loads((out / "download_status.json").read_text())
    assert progress["status"] == status
    assert progress["remaining"] == 1
    assert calls == []


def test_resume_uses_validated_cache_without_repeating_requests(collector):
    module, out, calls, _ = collector
    args = SimpleNamespace(prepare_only=False, reserve=1000, max_requests=4000)
    module.collect(args)
    assert len(calls) == 1
    module.collect(args)
    assert len(calls) == 1
    progress = json.loads((out / "download_status.json").read_text())
    assert progress["status"] == "download_complete"
    assert progress["remaining"] == 0
    assert progress["completed"] == 5


def test_missing_ranges_chunk_at_100_days_and_reject_price_conflicts(collector):
    module, _, _, _ = collector
    assert list(module.intervals("2025-10-09", "2026-01-20", {"2026-01-17"})) == [
        ("2025-10-09", "2026-01-16"),
        ("2026-01-18", "2026-01-20"),
    ]
    original = dict(timestamp=1759981500, open=50, high=51, low=49, close=50, volume=10)
    rows = {original["timestamp"]: original}
    with pytest.raises(RuntimeError, match="Conflicting source prices"):
        module.merge(rows, [{**original, "close": 51}], "2025-10-09", "2025-10-09")


def test_deferred_bad_history_does_not_block_other_contracts_or_mark_complete(collector):
    from strategies.nifty_options import history as h
    from strategies.nifty_options import data_probe

    module, out, calls, _ = collector
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["contracts"].insert(0, {**manifest["contracts"][0], "symbol": "INVALID_OPTION"})
    h.atomic_json(out / "manifest.json", manifest)

    def fetch(token, operation, payload):
        if payload["broker_symbol"] == "INVALID_OPTION":
            raise module.DeferredHistoryError()
        return data_probe.expired_call(token, operation, payload)

    module.collect(SimpleNamespace(prepare_only=False, reserve=1000, max_requests=4000, history_fetcher=fetch))
    progress = json.loads((out / "download_status.json").read_text())
    assert len(calls) == 1
    assert progress["status"] == "blocked"
    assert progress["remaining"] == 1
    assert progress["completed"] == 5
    assert progress["deferred_ranges"][0]["symbol"] == "INVALID_OPTION"
    assert not h.cache_file("INVALID_OPTION", "2025-10-09", "2025-10-14").exists()
