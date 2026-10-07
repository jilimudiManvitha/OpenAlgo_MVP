"""Causal entry, ranking, report ownership/accounting and warm-cache regression tests."""

from datetime import datetime

import pytest
from flask import Flask
from flask_wtf.csrf import CSRFProtect

from services.market_scanner_service import rank_rows, validate_options
from services.scanner_strategy_reports import ReportStore, metrics, trades_csv
from strategies.top_gain_volumes.runtime import (
    IST,
    TickCandles,
    eligible_symbols,
    enter,
    exit_trade,
)


def seeded():
    start = datetime(2026, 9, 28, 9, 15, tzinfo=IST).timestamp()
    raw = [[start - 86400 + i * 60, 100, 100, 100, 100, 100] for i in range(20)]
    raw.append([start, 110, 112, 110, 111, 100])
    return TickCandles(raw, start + 59), start


def test_enters_on_cross_before_entry_minute_closes():
    candle, start = seeded()
    assert not candle.tick(start + 60, 111, 110)
    assert candle.tick(start + 61, 113, 120)
    trade = enter("ABC", start + 61, 113, candle, 0.05)
    assert trade["entry_ts"] < start + 120
    assert trade["quantity"] * trade["entry"] <= 10000
    assert trade["target"] >= trade["entry"] + 3 * (trade["entry"] - trade["stop"])
    assert not candle.tick(start + 62, 90, 130)  # Later wick cannot erase the earlier entry.
    assert trade["entry_ts"] == start + 61


def test_vwap_guard_is_used_at_intrabar_entry():
    candle, start = seeded()
    candle.tick(start + 60, 111, 110)
    candle.pv = 1000000
    assert not candle.tick(start + 61, 113, 120)


def test_vwap_regression_test_detects_disabled_guard(monkeypatch):
    import inspect
    import textwrap

    from strategies.top_gain_volumes import runtime

    source = textwrap.dedent(inspect.getsource(TickCandles.tick))
    assert source.count("and price > vw") == 1
    namespace = dict(runtime.__dict__)
    exec(source.replace("and price > vw", "and True"), namespace)
    monkeypatch.setattr(TickCandles, "tick", namespace["tick"])
    with pytest.raises(AssertionError):
        test_vwap_guard_is_used_at_intrabar_entry()


def test_gap_and_volume_rewind_suppress_entries():
    candle, start = seeded()
    candle.tick(start + 60, 111, 110)
    assert not candle.tick(start + 61, 113, 109)
    assert candle.invalid
    candle, start = seeded()
    candle.tick(start + 60, 111, 110)
    assert not candle.tick(start + 151, 113, 120)
    assert candle.invalid


def test_missing_warmup_minutes_rejected():
    candle, start = seeded()
    with pytest.raises(ValueError, match="incomplete"):
        TickCandles(
            [[start - 86400 + i * 60, 100, 100, 100, 100, 100] for i in range(20)], start + 120
        )


def test_older_than_seed_tick_ignored_without_mutation():
    candle, start = seeded()
    original = list(candle.bar)
    assert not candle.tick(start + 50, 500, 500)
    assert candle.bar == original


def test_targets_stops_and_clock_close_whole_position():
    for price, minute, reason in [
        (160, 600, "TARGET"),
        (50, 600, "STOP"),
        (114, 920, "SQUARE_OFF"),
    ]:
        candle, start = seeded()
        candle.tick(start + 60, 111, 110)
        candle.tick(start + 61, 113, 120)
        trade = enter("ABC", start + 61, 113, candle, 0.05)
        stamp = start + (minute - 555) * 60
        assert exit_trade(trade, stamp, price, 0.05, 920)
        assert trade["reason"] == reason
        assert trade["net_pnl"] == pytest.approx(
            (trade["exit"] - trade["entry"]) * trade["quantity"] - trade["fees"]
        )
        if reason == "TARGET":
            assert trade["exit"] >= trade["target"]


def test_forward_cutoff_is_1515_for_every_stock():
    from strategies.top_gain_volumes.runtime import SQUARE_OFF_MINUTE
    candle, start = seeded()
    candle.tick(start + 60, 111, 110)
    candle.tick(start + 61, 113, 120)
    trade = enter("NON_FO_STOCK", start + 61, 113, candle, 0.05)
    assert SQUARE_OFF_MINUTE == 915
    assert exit_trade(trade, start + (915 - 555) * 60, 114, 0.05, SQUARE_OFF_MINUTE)
    assert trade["reason"] == "SQUARE_OFF"


def rows():
    return [
        {"symbol": s, "ltp": 100, "volume": v, "rvol": r, "change_percent": p, "live_stamp": 100}
        for s, v, r, p in [("A", 100, 2, 3), ("B", 300, 3, -2), ("C", 200, 4, 5)]
    ]


@pytest.mark.parametrize(
    "field,order,expected",
    [
        ("change_percent", "asc", ["A", "C"]),
        ("change_percent", "desc", ["C", "A"]),
        ("volume", "asc", ["A", "C"]),
        ("volume", "desc", ["C", "A"]),
    ],
)
def test_positive_shocker_sort_happens_before_limit(field, order, expected):
    options = validate_options(
        {"positive_only": "true", "shocker_sort": field, "sort_order": order, "limit": 1}
    )
    ranked = rank_rows(rows(), options)
    assert [r["symbol"] for r in ranked["volume_shockers"]] == expected[:1]
    assert ranked["matching_counts"]["volume_shockers"] == 2


def test_membership_excludes_negative_stale_and_future_quotes():
    data = {r["symbol"]: r for r in rows()}
    assert eligible_symbols(data, 101) == {"A", "C"}
    assert eligible_symbols(data, 116) == set()
    assert eligible_symbols(data, 99) == set()


def test_scanner_keeps_changed_volume_within_same_second():
    from services.market_scanner_feed import merge_quote
    from test.test_market_scanner_live import NOW, row

    original = row()
    quote = {
        "mode": 2,
        "data": {
            "timestamp": NOW.timestamp(),
            "last_traded_time": NOW.timestamp(),
            "ltp": original["ltp"],
            "volume": original["volume"] + 100,
        },
    }
    updated = merge_quote(original, quote, NOW)
    assert updated["volume"] == original["volume"] + 100
    assert updated["rvol"] > original["rvol"]
    assert merge_quote(updated, quote, NOW) is updated


def test_fyers_adapter_forwards_volume_change_at_unchanged_price(monkeypatch):
    from unittest.mock import Mock

    from broker.fyers.streaming.fyers_adapter import FyersAdapter

    adapter = FyersAdapter("fixture-only", "fixture")
    adapter.active_subscriptions = {"NSE:ABC": {"symbol": "ABC", "exchange": "NSE"}}
    received = []
    adapter.subscription_callbacks = {"SymbolUpdate_NSE:ABC": received.append}
    adapter.data_mapper.map_fyers_data = lambda data, mode: {
        "symbol": "ABC",
        "ltp": 100,
        "volume": data["volume"],
    }
    adapter.logger = Mock()
    monkeypatch.setattr("broker.fyers.streaming.fyers_adapter.time.time", lambda: 1000)
    try:
        for volume in (100, 200, 200):
            adapter._on_message({"original_symbol": "NSE:ABC", "type": "sf", "volume": volume})
        assert [r["volume"] for r in received] == [100, 200]
        adapter.logger.error.assert_not_called()
    finally:
        adapter.disconnect()


def report():
    return {
        "id": "paper-test",
        "day": "2026-09-28",
        "kind": "Live paper",
        "status": "complete",
        "paths": ["PAPER"],
        "trades": [
            {
                "symbol": "ABC",
                "path": "PAPER",
                "entry_ts": 1,
                "exit_ts": 3,
                "entry": 100,
                "exit": 110,
                "quantity": 10,
                "fees": 1,
                "gross_pnl": 100,
                "net_pnl": 99,
            }
        ],
        "candles": {},
    }


def test_peak_capital_uses_overlapping_positions_and_fees():
    trades = report()["trades"]
    trades.append(dict(trades[0], symbol="DEF", entry_ts=2, exit_ts=4, net_pnl=-51, gross_pnl=-50))
    result = metrics(trades)
    assert result["peak_capital"] == 2000
    assert result["net_pnl"] == 48
    assert result["realized_drawdown"] == 51
    assert result["current_capital"] == 0


def test_store_account_isolation_and_csv(tmp_path):
    store = ReportStore(tmp_path / "reports.db")
    try:
        store.save("alice", report())
        assert store.get("bob", "paper-test") is None
        assert store.list("bob") == []
        assert len(store.list("alice")) == 1
        saved = store.get("alice", "paper-test")
        assert saved["metrics"]["PAPER"]["net_pnl"] == 99
        assert "ABC,PAPER" in trades_csv(saved)
    finally:
        store.close()


def test_duplicate_paper_claim_cannot_overwrite_existing_run(tmp_path):
    store = ReportStore(tmp_path / "reports.db")
    try:
        assert store.claim("alice", report())
        duplicate = dict(report(), status="replacement")
        assert not store.claim("alice", duplicate)
        assert store.get("alice", "paper-test")["status"] == "complete"
    finally:
        store.close()


def test_report_routes_require_login_and_never_cross_accounts(monkeypatch, tmp_path):
    from blueprints import market_scanner as routes
    from services import scanner_strategy_reports as reports

    store = ReportStore(tmp_path / "reports.db")
    store.save("alice", report())
    monkeypatch.setattr(reports, "ReportStore", lambda: store)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-only")
    CSRFProtect(app)
    app.register_blueprint(routes.market_scanner_bp)
    monkeypatch.setattr(routes, "is_session_valid", lambda: True)
    with app.test_client() as client:
        assert client.get("/market-scanner/api/reports").status_code == 401
        with client.session_transaction() as session:
            session["user"] = "bob"
        assert client.get("/market-scanner/api/reports/paper-test").status_code == 404
        assert client.post("/market-scanner/api/paper-schedule", json={}).status_code == 400
        with client.session_transaction() as session:
            session["user"] = "alice"
        assert (
            client.get("/market-scanner/api/reports/paper-test").json["data"]["id"] == "paper-test"
        )
        download = client.get("/market-scanner/api/reports/paper-test?download=csv")
        assert download.status_code == 200
        assert "trades.csv" in download.headers["Content-Disposition"]
    store.close()


def test_warm_scan_uses_one_quote_pass_and_no_per_symbol_cache_connections(tmp_path):
    from database.market_scanner_db import BaselineCache
    from test.test_market_scanner import (
        NOW,
        FakeProvider,
        candles,
        finished,
        manager,
        normalize_history,
    )

    cache = BaselineCache("sqlite:///" + (tmp_path / "baseline.db").as_posix())
    for index in range(51):
        cache.put(
            f"NSE:S{index}-EQ", NOW.date().isoformat(), normalize_history(candles(), NOW.date())
        )
    cache.get = lambda *args: pytest.fail("warm scan must bulk-load baselines")
    provider = FakeProvider()
    scanner = manager(provider, count=51, cache=cache)
    try:
        scanner.start("alice", {})
        assert finished(scanner)["state"] == "completed"
        assert provider.history_calls == 0
        assert provider.quote_batches == [50, 1]
    finally:
        cache.engine.dispose()


def test_report_repetition_releases_database_handles(tmp_path):
    import psutil

    store = ReportStore(tmp_path / "reports.db")
    process = psutil.Process()
    count = process.num_handles if hasattr(process, "num_handles") else process.num_fds
    try:
        store.save("alice", report())
        baseline = count()
        for _ in range(150):
            store.save("alice", report())
            store.get("alice", "paper-test")
            store.get("bob", "paper-test")
        assert count() <= baseline + 4
    finally:
        store.close()
