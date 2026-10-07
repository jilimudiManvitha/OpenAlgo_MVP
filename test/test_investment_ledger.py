"""Real isolated SQLite replay, precision, ownership and rollback checks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

from database import investment_db as db
from database.engine_factory import create_db_engine
from services import investment_service as svc


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'investment.db'}")
    session = scoped_session(sessionmaker(bind=engine, autoflush=False))
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(svc, "db_session", session)
    monkeypatch.setattr(db, "db_session", session)
    yield session
    session.remove()
    engine.dispose()


def seed(user="alice"):
    account = svc.save_account(user, {"name": "Personal", "kind": "paper"})
    asset = svc.save_asset(
        user, {"account_id": account["id"], "symbol": "ATHER", "exchange": "NSE"}
    )
    return account, asset


def trade(asset, action="BUY", quantity="100", price="1000", day="2026-09-01", **extra):
    return svc.save_transaction(
        "alice",
        {
            "asset_id": asset["id"],
            "action": action,
            "quantity": quantity,
            "price": price,
            "trade_date": day,
            "trade_time": "09:30:00",
            **extra,
        },
    )


def holding(asset):
    return svc.holdings("alice", asset_id=asset["id"])[0]


def test_ather_example_quotes_never_change_cost(ledger):
    _, asset = seed()
    trade(asset)
    for price, gain, pct in [("1100", "10000.0000", "10.0000"), ("950", "-5000.0000", "-5.0000")]:
        svc.set_price("alice", asset["id"], price, datetime.utcnow())
        row = holding(asset)
        assert row["invested"] == "100000.0000"
        assert row["average_cost"] == "1000.0000"
        assert row["unrealized_gain"] == gain
        assert row["return_percent"] == pct
    assert holding(asset)["stale"] is True
    assert holding(asset)["today_gain"] is None


def test_partial_sale_weighted_average_and_fifo_are_separate(ledger):
    _, asset = seed()
    trade(asset, quantity="10", price="100", brokerage="10")
    trade(asset, quantity="10", price="200", day="2026-09-02")
    trade(asset, "SELL", "5", "250", "2026-09-03", brokerage="5")
    row = holding(asset)
    assert row["quantity"] == "15.000000"
    assert row["average_cost"] == "150.5000"
    assert row["invested"] == "2257.5000"
    assert row["trading_realized"] == "492.5000"
    assert row["fifo_realized"] == "740.0000"
    lots = ledger.query(db.InvestmentLot).all()
    assert sum(lot.quantity_remaining for lot in lots) == Decimal("15")
    assert lots[0].quantity_remaining == 5


def test_oversell_and_invalid_delete_leave_ledger_unchanged(ledger):
    _, asset = seed()
    buy = trade(asset)
    sell = trade(asset, "SELL", "10", "1100", "2026-09-02")
    before = holding(asset)
    with pytest.raises(svc.InvestmentError, match="Sale exceeds"):
        trade(asset, "SELL", "91", "1100", "2026-09-03")
    with pytest.raises(svc.InvestmentError, match="Sale exceeds"):
        svc.delete_transaction("alice", buy["id"])
    assert holding(asset) == before
    assert len(svc.transactions("alice")) == 2
    svc.delete_transaction("alice", sell["id"])
    assert holding(asset)["quantity"] == "100.000000"


def test_backdated_purchase_rebuilds_both_policies(ledger):
    _, asset = seed()
    trade(asset, quantity="10", price="100", day="2026-09-02")
    trade(asset, "SELL", "5", "200", "2026-09-03")
    trade(asset, quantity="10", price="50", day="2026-09-01")
    row = holding(asset)
    assert row["average_cost"] == "75.0000"
    assert row["trading_realized"] == "625.0000"
    assert row["fifo_realized"] == "750.0000"


def test_fractional_units_charges_and_restart(ledger):
    _, asset = seed()
    trade(asset, quantity="1.123456", price="10.1234", brokerage="0.0023")
    before = holding(asset)
    ledger.remove()
    assert holding(asset) == before
    assert before["quantity"] == "1.123456"
    trade(asset, "SELL", "0.123456", "20", "2026-09-02")
    assert holding(asset)["quantity"] == "1.000000"
    assert holding(asset)["average_cost"] == before["average_cost"]


def test_income_and_explicit_split_preserve_basis(ledger):
    _, asset = seed()
    trade(asset, quantity="10", price="100")
    trade(asset, "DIVIDEND", "1", "30", "2026-09-02", brokerage="1")
    trade(
        asset,
        "CORPORATE_ACTION",
        "1",
        "0",
        "2026-09-03",
        corporate_ratio="2",
        notes="2 for 1 split",
    )
    row = holding(asset)
    assert row["quantity"] == "20.000000"
    assert row["invested"] == "1000.0000"
    assert row["average_cost"] == "50.0000"
    assert row["realized_gain"] == "29.0000"
    trade(asset, "SELL", "20", "75", "2026-09-04")
    assert holding(asset)["fifo_realized"] == "500.0000"


@pytest.mark.parametrize(
    "field,value",
    [
        ("price", "NaN"),
        ("price", "Infinity"),
        ("price", "-1"),
        ("price", True),
        ("quantity", "0"),
        ("quantity", "1.0000001"),
        ("brokerage", "-2"),
        ("trade_date", "2099-01-01"),
        ("trade_time", "invalid"),
    ],
)
def test_reject_invalid_inputs(ledger, field, value):
    _, asset = seed()
    data = {
        "asset_id": asset["id"],
        "action": "BUY",
        "quantity": "10",
        "price": "100",
        "trade_date": "2026-09-01",
        "trade_time": "09:30",
    }
    data[field] = value
    with pytest.raises(svc.InvestmentError):
        svc.save_transaction("alice", data)
    assert svc.transactions("alice") == []


def test_all_owned_mutations_and_reads_refuse_other_user(ledger):
    account, asset = seed()
    tx = trade(asset)
    for call in [
        lambda: svc.save_asset("bob", {"account_id": account["id"], "symbol": "SBIN"}),
        lambda: svc.delete_transaction("bob", tx["id"]),
        lambda: svc.delete_asset("bob", asset["id"]),
        lambda: svc.save_account("bob", {"name": "Stolen"}, account["id"]),
        lambda: svc.holdings("bob", asset_id=asset["id"]),
        lambda: svc.set_price("bob", asset["id"], "1", datetime.utcnow()),
    ]:
        with pytest.raises(svc.InvestmentError) as error:
            call()
        assert error.value.status == 404
    assert svc.holdings("bob") == []


def test_watch_only_is_not_a_holding_or_purchase(ledger):
    _, asset = seed()
    svc.save_asset("alice", {"is_watch_only": True}, asset["id"])
    with pytest.raises(svc.InvestmentError, match="watch-only"):
        trade(asset)
    assert svc.dashboard("alice")["holdings"] == []
    assert ledger.query(db.InvestmentLot).count() == 0


def test_simultaneous_sells_cannot_oversell(ledger):
    _, asset = seed()
    trade(asset, quantity="10")

    def sell():
        try:
            trade(asset, "SELL", "7", "1200", "2026-09-02")
            return "ok"
        except svc.InvestmentError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sell(), range(2)))
    assert sorted(map(str, results)) == ["409", "ok"]
    assert holding(asset)["quantity"] == "3.000000"


def test_missing_stale_and_fresh_valuations_are_distinct(ledger):
    _, asset = seed()
    trade(asset)
    assert svc.dashboard("alice")["market_value"] is None
    svc.set_price(
        "alice",
        asset["id"],
        "1100",
        datetime.utcnow() - timedelta(days=1),
        "broker_timestamp",
        "1120",
    )
    assert holding(asset)["today_gain"] is None
    svc.set_price("alice", asset["id"], "1100", datetime.utcnow(), "broker_timestamp", "1120")
    assert svc.dashboard("alice")["today_gain"] == "-2000.0000"
    assert svc.dashboard("alice")["today_percent"] == "-1.7857"


def test_account_and_asset_cannot_silently_delete_history(ledger):
    account, asset = seed()
    trade(asset)
    for call in [
        lambda: svc.delete_account("alice", account["id"]),
        lambda: svc.delete_asset("alice", asset["id"]),
        lambda: svc.save_asset("alice", {"symbol": "SBIN"}, asset["id"]),
    ]:
        with pytest.raises(svc.InvestmentError) as error:
            call()
        assert error.value.status == 409


def test_refresh_failure_keeps_dated_price_and_entry_cost(ledger, monkeypatch):
    from database import auth_db
    from services import quotes_service

    _, asset = seed()
    trade(asset)
    svc.set_price("alice", asset["id"], "1050", datetime.utcnow())
    monkeypatch.setattr(auth_db, "get_auth_token", lambda _: "test-token")
    monkeypatch.setattr(quotes_service, "get_quotes", lambda *a, **k: (False, {}, 502))
    assert svc.refresh_prices("alice", "fyers")["failed"] == ["ATHER"]
    assert holding(asset)["price"] == "1050.0000"
    assert holding(asset)["invested"] == "100000.0000"


def test_score_reproducible_and_missing_history_not_invented(ledger):
    _, asset = seed()
    trade(asset)
    svc.set_price("alice", asset["id"], "1000", datetime.utcnow() - timedelta(days=30))
    svc.set_price("alice", asset["id"], "1100", datetime.utcnow())
    score = svc.dashboard("alice")["score"]
    assert score["quality"] == 0
    assert score["diversification"] == 0
    assert score["momentum"] == 100
    assert score["composite"] == 30
    svc.set_price("alice", asset["id"], "900", datetime.utcnow())
    assert svc.dashboard("alice")["score"]["momentum"] == 0


def test_sessions_released_after_repeated_success_and_failure(ledger):
    _, asset = seed()
    trade(asset)
    for _ in range(100):
        svc.dashboard("alice")
        with pytest.raises(svc.InvestmentError):
            svc.delete_account("bob", asset["account_id"])
        assert not ledger.registry.has()


def test_duplicate_account_and_instrument_do_not_create_partial_rows(ledger):
    account, asset = seed()
    with pytest.raises(svc.InvestmentError) as error:
        svc.save_account("alice", {"name": account["name"]})
    assert error.value.status == 409
    with pytest.raises(svc.InvestmentError):
        svc.save_asset("alice", {"account_id": account["id"], "symbol": asset["symbol"]})
    assert len(svc.accounts("alice")) == 1
    assert len(svc.assets("alice")) == 1
