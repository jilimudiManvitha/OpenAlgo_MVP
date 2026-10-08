"""Real Sandbox close-window tests using only conftest's isolated databases."""

import uuid
from datetime import datetime, time
from unittest.mock import Mock

import pytest

from sandbox import scheduled_equity


@pytest.fixture
def account(monkeypatch):
    from database import sandbox_db, symbol
    from sandbox import execution_engine, order_manager
    from sandbox.squareoff_manager import SquareOffManager

    assert "test" in str(sandbox_db.engine.url) and "test" in str(symbol.engine.url)
    sandbox_db.init_db()
    symbol.Base.metadata.create_all(symbol.engine)
    if not symbol.SymToken.query.filter_by(symbol="CLOSETST", exchange="NSE").first():
        symbol.db_session.add(
            symbol.SymToken(
                symbol="CLOSETST",
                brsymbol="CLOSETST-EQ",
                name="Fixture",
                exchange="NSE",
                brexchange="NSE",
                token="99999994",
                lotsize=1,
                instrumenttype="EQ",
                tick_size=0.05,
            )
        )
        symbol.db_session.commit()
    symbol.db_session.remove()
    clock = [time(15, 14)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, clock[0].hour, clock[0].minute, clock[0].second, tzinfo=tz)

    monkeypatch.setattr(order_manager, "datetime", Clock)
    monkeypatch.setattr(scheduled_equity, "ist_now", Clock.now)
    monkeypatch.setattr(
        order_manager.OrderManager, "_generate_order_id", lambda _: "close-" + uuid.uuid4().hex
    )
    for cls, name in (
        (order_manager.OrderManager, "_publish_order_update_event"),
        (execution_engine.ExecutionEngine, "_publish_fill_event"),
        (execution_engine.ExecutionEngine, "_publish_order_update_event"),
    ):
        monkeypatch.setattr(cls, name, lambda *a, **k: None)
    owner = "close-fixture-" + uuid.uuid4().hex[:10]
    manager = order_manager.OrderManager(owner)

    def place(side, strategy, quantity=10):
        return manager.place_order(
            {
                "symbol": "CLOSETST",
                "exchange": "NSE",
                "product": "MIS",
                "action": side,
                "quantity": quantity,
                "price_type": "MARKET",
                "strategy": strategy,
            },
            prefetched_quote={"ltp": 100, "bid": 100, "ask": 100},
        )

    try:
        yield owner, place, clock
    finally:
        sandbox_db.db_session.remove()
        symbol.db_session.remove()


def test_opposing_strategy_exits_can_both_close_after_1515_without_new_entry(account):
    from database.sandbox_db import SandboxPositions

    owner, place, clock = account
    long = "Four10K_nifty500_fixed"
    short = "Short10K_nifty500_short_fixed"
    assert place("BUY", long)[0]
    assert place("SELL", short)[0]
    assert SandboxPositions.query.filter_by(user_id=owner, symbol="CLOSETST").one().quantity == 0
    clock[0] = time(15, 15)
    assert not place("BUY", long)[0]  # No late entry permission.
    assert not place("SELL", short)[0]
    assert place("SELL", long)[0]  # Close attributable long despite net account being flat.
    assert place("BUY", short)[0]
    assert SandboxPositions.query.filter_by(user_id=owner, symbol="CLOSETST").one().quantity == 0
    assert not scheduled_equity.has_exposure(owner, "CLOSETST")
    assert not place("SELL", long)[0]  # Already closed, never reopen.
    assert not place("BUY", short)[0]


def test_close_window_expires_and_unknown_tags_cannot_bypass(account):
    owner, place, clock = account
    long = "Four10K_nifty500_fixed"
    short = "Short10K_nifty500_short_fixed"
    assert place("BUY", long)[0] and place("SELL", short)[0]
    clock[0] = time(15, 15)
    assert not place("SELL", "Four10K_invented")[0]
    assert not place("SELL", long, 11)[0]
    clock[0] = time(15, 16)
    assert not place("SELL", long)[0]
    assert scheduled_equity.in_close_window(time(15, 15, 59), time(15, 15))
    assert not scheduled_equity.in_close_window(time(15, 16), time(15, 15))


def test_safety_squareoff_waits_for_owned_exits_then_runs(account, monkeypatch):
    from sandbox import position_manager, squareoff_manager

    owner, place, clock = account
    assert place("BUY", "Four10K_nifty500_fixed")[0]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, 15, clock[0].minute, tzinfo=tz)

    monkeypatch.setattr(squareoff_manager, "datetime", Clock)
    monkeypatch.setattr(position_manager, "cleanup_expired_contracts", lambda: None)
    manager = squareoff_manager.SquareOffManager()
    manager._cancel_open_mis_orders = Mock(return_value=0)
    manager._cancel_expired_contract_orders = Mock(return_value=0)
    manager._square_off_positions = Mock()
    clock[0] = time(15, 15)
    manager.check_and_square_off()
    submitted = [p for call in manager._square_off_positions.call_args_list for p in call.args[0]]
    assert all(p.user_id != owner for p in submitted)
    clock[0] = time(15, 16)
    manager.check_and_square_off()
    submitted = [p for call in manager._square_off_positions.call_args_list for p in call.args[0]]
    assert any(p.user_id == owner for p in submitted)


def test_pending_close_reserved_and_not_auto_cancelled(account, monkeypatch):
    from database.sandbox_db import SandboxOrders, db_session
    from sandbox import order_manager, squareoff_manager

    owner, place, clock = account
    tag = "Four10K_nifty500_fixed"
    assert place("BUY", tag)[0]
    db_session.add(
        SandboxOrders(
            orderid="pending-" + uuid.uuid4().hex,
            user_id=owner,
            symbol="CLOSETST",
            exchange="NSE",
            product="MIS",
            action="SELL",
            quantity=10,
            pending_quantity=10,
            filled_quantity=0,
            price_type="MARKET",
            order_status="open",
            order_timestamp=datetime(2026, 10, 7, 15, 14),
            strategy=tag,
        )
    )
    db_session.commit()
    assert not scheduled_equity.permits_exit(owner, "CLOSETST", tag, "SELL", 10)
    cancel = Mock(return_value=(True, {}, 200))
    monkeypatch.setattr(order_manager.OrderManager, "cancel_order", cancel)
    manager = squareoff_manager.SquareOffManager()
    own = SandboxOrders.query.filter_by(user_id=owner, order_status="open").one().orderid
    manager._cancel_open_mis_orders(time(15, 15))
    assert own not in [c.args[0] for c in cancel.call_args_list]
    manager._cancel_open_mis_orders(time(15, 16))
    assert own in [c.args[0] for c in cancel.call_args_list]


def test_prior_day_unmatched_orders_cannot_authorize_new_exposure(account):
    from database.sandbox_db import SandboxOrders, db_session

    owner, place, clock = account
    long, short = "Four10K_nifty500_fixed", "Short10K_nifty500_short_fixed"
    assert place("BUY", long)[0] and place("SELL", short)[0]
    SandboxOrders.query.filter_by(user_id=owner).update(
        {SandboxOrders.order_timestamp: datetime(2026, 10, 6, 10, 0)}
    )
    db_session.commit()
    clock[0] = time(15, 15)
    assert not scheduled_equity.has_exposure(owner, "CLOSETST")
    assert not place("SELL", long)[0]
