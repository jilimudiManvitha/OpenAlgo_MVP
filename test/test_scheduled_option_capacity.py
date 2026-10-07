"""Exercise the real pool allocator offline; no broker, sockets or production data."""

import logging
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from services.market_scanner_feed import ScannerFeed
from strategies.nifty_options.feed import QuoteSubscriptions, connection_delay, required_contracts
from strategies.nifty_options.profiles import PROFILES
from strategies.nifty_options.selection import DataUnavailable
from websocket_proxy.connection_manager import ConnectionPool


def catalogue():
    return [
        {"symbol": f"W{week}_{strike}", "expiry": expiry}
        for week, expiry in enumerate(("2026-10-06", "2026-10-13"))
        for strike in range(480)
    ]


def offline_pool():
    pool = ConnectionPool.__new__(ConnectionPool)
    pool.lock = threading.RLock()
    pool.logger = logging.getLogger("test.scheduled.capacity")
    pool.adapters, pool.adapter_symbol_counts = [], []
    pool.max_symbols, pool.max_connections = 1000, 3
    pool.broker_name, pool.user_id = "fyers", "test-only"
    pool.subscription_map, pool.subscription_depths = {}, {}
    pool.peak_total_symbols, pool.peak_connections_used, pool.peak_symbol_counts = 0, 0, []
    pool._create_adapter = lambda: SimpleNamespace(
        initialize=lambda *_: None,
        connect=lambda: None,
        subscribe=lambda *_: {"status": "success"},
    )
    return pool


def test_scanner_and_all_twelve_profiles_fit_real_shared_pool(monkeypatch):
    monkeypatch.delenv("SCANNER_STREAM_LIMIT", raising=False)
    scanner = ScannerFeed("test-only", "fyers", None, None)
    pool = offline_pool()
    # Deliberately disjoint equities give a conservative upper bound. In use,
    # the scanner and scheduled Nifty500 runners share many of these symbols.
    for prefix, count in (("SCANNER", min(2679, scanner.limit)), ("NIFTY500", 500)):
        for index in range(count):
            assert pool._subscribe_inner(f"{prefix}_{index}", "NSE", 2)["status"] == "success"

    def subscribe(specs, mode):
        assert mode == "Quote"
        return {
            "subscriptions": [
                {**s, **pool._subscribe_inner(s["symbol"], s["exchange"], 2)} for s in specs
            ]
        }

    contracts = catalogue()
    expiries = [date(2026, 10, 6), date(2026, 10, 13)]
    for profile in PROFILES.values():
        selected = required_contracts(contracts, expiries, profile, date(2026, 10, 6), [])
        assert len(selected) == 480
        feed = QuoteSubscriptions(
            [
                {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
                *[{"symbol": c["symbol"], "exchange": "NFO"} for c in selected],
            ]
        )
        client = SimpleNamespace(
            connected=True, authenticated=True, ws=object(), subscribe=subscribe
        )
        for tick in range(25):
            feed.step(client, tick)
        assert feed.ready, feed.error
        assert len(feed.accepted) == 481
    assert len(pool.subscription_map) == 2461
    assert sum(pool.adapter_symbol_counts) == 2461
    assert 3000 - pool.peak_total_symbols == 539


def test_active_cycle_keeps_full_chain_for_adjustment_after_week_rollover():
    contracts = catalogue()
    profile = PROFILES["delta_positional_next_week"]
    selected = required_contracts(
        contracts,
        [date(2026, 10, 6), date(2026, 10, 13)],
        profile,
        date(2026, 10, 6),
        [{"symbol": "W0_3"}],
        "2026-10-06",
    )
    assert selected == contracts
    # Flat after closing an adjustment (or an unfilled pending open) also
    # requires the entire original chain, not just formerly held symbols.
    assert (
        required_contracts(
            contracts,
            [date(2026, 10, 6), date(2026, 10, 13)],
            profile,
            date(2026, 10, 6),
            [],
            "2026-10-06",
        )
        == contracts
    )


def test_missing_new_week_does_not_prevent_held_risk_management():
    contracts = catalogue()[:480]
    profile = PROFILES["premium_positional_next_week"]
    assert (
        required_contracts(
            contracts, [date(2026, 10, 6)], profile, date(2026, 10, 6), [{"symbol": "W0_2"}]
        )
        == contracts
    )
    with pytest.raises(DataUnavailable, match="Missing next"):
        required_contracts(contracts, [date(2026, 10, 6)], profile, date(2026, 10, 6), [])


def test_scanner_budget_respects_lower_limits_and_other_brokers(monkeypatch):
    monkeypatch.setenv("SCANNER_STREAM_LIMIT", "5000")
    assert ScannerFeed("user", "fyers", None, None).limit == 1000
    assert ScannerFeed("user", "other", None, None).limit == 5000
    monkeypatch.setenv("SCANNER_STREAM_LIMIT", "250")
    assert ScannerFeed("user", "fyers", None, None).limit == 250


def test_connections_are_staggered_but_held_positions_connect_immediately():
    assert [connection_delay(i) for i in range(12)] == list(range(12))
    assert [connection_delay(i, has_positions=True) for i in range(12)] == [0] * 12
    assert [connection_delay(i, retry=True) for i in range(12)] == [5 + i * 0.5 for i in range(12)]
