"""Remaining portfolio classes, reports, watches and sandbox linkage in isolated DBs."""
# ruff: noqa: F811 - imported pytest fixtures

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

from database import investment_db as db
from database.engine_factory import create_db_engine
from services import investment_paper as paper
from services import investment_reports as reports
from services import investment_service as s
from services import investment_watchlists as watches
from test.test_investment_api import client, post
from test.test_investment_ledger import holding, ledger, seed, trade


@pytest.mark.parametrize("kind", s.ASSET_CLASSES)
def test_all_asset_classes_crud_valuation_and_sign(ledger, kind):
    account = s.save_account("alice", {"name": "Assets"})
    asset = s.save_asset(
        "alice",
        {
            "account_id": account["id"],
            "asset_class": kind,
            "symbol": "ITEM",
            "details": dict.fromkeys(s.ASSET_CLASSES[kind], ""),
        },
    )
    s.save_asset("alice", {"name": "Updated", "scheme_code": ""}, asset["id"])
    trade(asset, quantity="10", price="100")
    s.save_asset("alice", {"name": "Updated again", "scheme_code": ""}, asset["id"])
    s.set_price("alice", asset["id"], "110", datetime(2026, 10, 1))
    row = holding(asset)
    sign = -1 if kind in s.LIABILITIES else 1
    assert Decimal(row["invested"]) == sign * 1000
    assert Decimal(row["market_value"]) == sign * 1100
    assert Decimal(s.dashboard("alice")["market_value"]) == sign * 1100
    with pytest.raises(s.InvestmentError):
        s.save_asset("bob", {"name": "stolen"}, asset["id"])


def test_fractional_mf_sips_redemption_and_liability_interest(ledger):
    account, _ = seed()
    mf = s.save_asset(
        "alice",
        {
            "account_id": account["id"],
            "asset_class": "MUTUAL_FUND",
            "symbol": "MF",
            "scheme_code": "123",
        },
    )
    trade(mf, quantity="1.123456", price="100")
    trade(mf, quantity="2.111111", price="120", day="2026-09-02")
    trade(mf, "SELL", "0.001", "130", "2026-09-03")
    assert holding(mf)["quantity"] == "3.233567"
    assert reports.build("alice", "consolidated")["rows"][0]["quantity"] == "3.233567"
    loan = s.save_asset(
        "alice", {"account_id": account["id"], "asset_class": "LOAN", "symbol": "LOAN"}
    )
    trade(loan, quantity="100", price="1")
    trade(loan, "SELL", "20", "1", "2026-09-02")
    trade(loan, "INTEREST", "1", "5", "2026-09-03")
    s.set_price("alice", loan["id"], "1", datetime(2026, 10, 1))
    assert holding(loan)["market_value"] == "-80.0000"
    assert holding(loan)["income"] == "-5.0000"


def test_csv_is_atomic_ambiguous_duplicates_and_foreign_rows_fail(ledger):
    account, asset = seed()
    header = "symbol,scheme_code,price,as_of\n"
    valid = "ATHER,,1100,2026-10-01T15:30:00+05:30\n"
    with pytest.raises(s.InvestmentError):
        reports.import_prices("alice", header + valid + "UNKNOWN,,1,2026-10-01T15:30:00+05:30\n")
    assert holding(asset)["price"] is None
    with pytest.raises(s.InvestmentError):
        reports.import_prices("bob", header + valid)
    with pytest.raises(s.InvestmentError):
        reports.import_prices("alice", header + valid + valid)
    assert reports.import_prices("alice", header + valid, account["id"])["updated"] == 1
    assert holding(asset)["price"] == "1100.0000"
    for bad in ("NaN", "-1", "inf"):
        with pytest.raises(s.InvestmentError):
            reports.import_prices("alice", header + valid.replace("1100", bad))


@pytest.mark.parametrize("name", reports.REPORTS)
def test_all_reports_use_owned_ledger_and_export_safe_csv(ledger, name):
    account, asset = seed()
    trade(asset, quantity="10", price="100", brokerage="10")
    trade(asset, quantity="10", price="200", day="2026-09-02")
    trade(asset, "SELL", "5", "250", "2026-09-03", brokerage="5")
    trade(asset, "DIVIDEND", "1", "10", "2026-09-04")
    s.set_price("alice", asset["id"], "210", datetime(2026, 9, 5))
    result = reports.build("alice", name, account["id"], "2026-09-01", "2026-10-01")
    assert result["name"] == name and isinstance(reports.csv_export(result), str)
    assert reports.build("bob", name)["rows"] == [] or name == "performance"
    if name == "capital-gains":
        assert sum(Decimal(r["gain"]) for r in result["rows"]) == 740
        assert "FIFO" in result["method"]
    if name == "holdings":
        assert result["rows"][0]["invested"] == holding(asset)["invested"]
    if name == "profit-loss":
        assert result["rows"][0]["realized_gain"] == "502.5000"
    text = reports.csv_export(
        {"columns": ["name", "amount"], "rows": [{"name": "=DANGEROUS()", "amount": "-100.00"}]}
    )
    assert "'=DANGEROUS()" in text and "'-100" not in text


def test_watch_only_thresholds_never_make_ledger_entries(ledger):
    _, asset = seed()
    s.save_asset("alice", {"is_watch_only": True}, asset["id"])
    watch = watches.save("alice", {"name": "Long term", "category": "Long-term"})
    watches.save_item(
        "alice", watch["id"], {"asset_id": asset["id"], "stop_price": "90", "target_price": "110"}
    )
    s.set_price("alice", asset["id"], "111", datetime(2026, 10, 1))
    item = watches.lists("alice")[0]["items"][0]
    assert "at/above" in item["observation"]
    assert holding(asset)["quantity"] == "0.000000"
    assert s.transactions("alice") == []
    with pytest.raises(s.InvestmentError):
        watches.save_item("bob", watch["id"], {"asset_id": asset["id"]})


def setup_paper():
    _, asset = seed()
    watch = watches.save("alice", {"name": "Long term", "category": "Long-term"})
    watches.save_item("alice", watch["id"], {"asset_id": asset["id"]})
    return asset, {
        "asset_id": asset["id"],
        "watchlist_id": watch["id"],
        "quantity": "10",
        "action": "BUY",
        "direction": "below",
        "reference_price": "100",
        "trigger_price": "95",
        "limit_price": "96",
        "request_key": "stable-key-123",
    }


def test_paper_crash_recovery_never_resubmits_and_imports_once(ledger, monkeypatch):
    asset, payload = setup_paper()
    calls = []

    def ambiguous(user, data):
        calls.append(data)
        raise RuntimeError("crashed after Sandbox commit")

    monkeypatch.setattr(paper, "dispatch", ambiguous)
    first = paper.place("alice", payload)
    assert first["status"] == "dispatching"
    assert paper.place("alice", payload)["id"] == first["id"] and len(calls) == 1
    with pytest.raises(s.InvestmentError):
        paper.place("alice", {**payload, "quantity": "11"})
    snapshot = {
        "gtt_id": "GTT-TEST",
        "status": "triggered",
        "fills": [
            {
                "order_id": "ORDER-1",
                "symbol": "ATHER",
                "exchange": "NSE",
                "product": "CNC",
                "action": "BUY",
                "quantity": 10,
                "price": "95.00",
                "timestamp": datetime(2026, 10, 1, 10),
            }
        ],
    }
    monkeypatch.setattr(paper, "sandbox_snapshot", lambda *_: snapshot)
    assert paper.reconcile("alice")["imported"] == 1
    assert paper.reconcile("alice")["imported"] == 0
    assert holding(asset)["quantity"] == "10.000000"
    with pytest.raises(s.InvestmentError):
        s.delete_transaction("alice", s.transactions("alice")[0]["id"])
    assert paper.orders("bob") == []


def test_extensions_api_requires_csrf_and_valid_identity(client):
    for path in ("prices/import", "watchlists", "watchlists/1/items", "paper/gtt", "paper/sync"):
        assert client.post("/investments/api/" + path, json={}).status_code == 400
    assert client.get("/investments/api/asset-classes").status_code == 200
    for name in reports.REPORTS:
        assert client.get("/investments/api/reports/" + name).status_code == 200
    with client.session_transaction() as sess:
        sess.pop("user")
    for path in ("reports/holdings", "watchlists", "paper/gtt"):
        assert client.get("/investments/api/" + path).status_code == 401


@pytest.fixture
def sandbox_ledger(tmp_path, monkeypatch):
    from database import sandbox_db as sandbox
    from sandbox import fund_manager, gtt_manager

    engine = create_db_engine(f"sqlite:///{tmp_path / 'paper.db'}")
    session = scoped_session(sessionmaker(bind=engine, autoflush=False))
    sandbox.Base.metadata.create_all(engine)
    monkeypatch.setattr(sandbox, "db_session", session)
    original_query = sandbox.Base.__dict__["query"]
    sandbox.Base.query = session.query_property()
    monkeypatch.setattr(gtt_manager, "db_session", session)
    monkeypatch.setattr(fund_manager, "db_session", session)
    monkeypatch.setattr(gtt_manager, "_notify_websocket_engine", lambda *_: None)
    monkeypatch.setattr(
        gtt_manager.GTTManager,
        "_leg_margin",
        lambda self, symbol, exchange, product, quantity, price, action: (
            Decimal(str(price)) * quantity,
            None,
        ),
    )
    session.add(
        sandbox.SandboxFunds(
            user_id="alice", total_capital=100000, available_balance=100000, used_margin=0
        )
    )
    session.commit()
    try:
        yield sandbox, session
    finally:
        sandbox.Base.query = original_query
        session.remove()
        engine.dispose()


def test_real_sandbox_gtt_balance_cancellation_and_reset_protection(
    ledger, sandbox_ledger, monkeypatch
):
    from database import token_db
    from sandbox.fund_manager import FundManager
    from services.investment_sandbox_guard import has_protected_portfolio

    sandbox, session = sandbox_ledger
    monkeypatch.setattr(
        token_db, "get_symbol_info", lambda *_: SimpleNamespace(tick_size=Decimal(".05"))
    )
    _, payload = setup_paper()
    before = session.query(sandbox.SandboxFunds).filter_by(user_id="alice").one().available_balance
    session.remove()
    placed = paper.place("alice", payload)
    assert placed["status"] == "active", placed
    funds = session.query(sandbox.SandboxFunds).filter_by(user_id="alice").one()
    assert funds.available_balance == before - Decimal("960")
    assert funds.used_margin == Decimal("960")
    assert has_protected_portfolio("alice") and not has_protected_portfolio("bob")
    # Exercise the actual manual-reset handler before it can touch config or balances.
    import inspect

    from flask import Flask
    from flask import session as web_session

    from blueprints import sandbox as sandbox_routes

    app = Flask(__name__)
    app.secret_key = "isolated-reset-test"
    with app.test_request_context("/sandbox/reset", method="POST"):
        web_session["user"] = "alice"
        response, status = inspect.unwrap(sandbox_routes.reset_config)()
        assert status == 409 and "preserve" in response.json["message"]
    FundManager("alice")._reset_funds(funds)
    session.expire_all()
    assert funds.available_balance == before - Decimal("960")
    session.remove()
    paper.cancel("alice", placed["id"])
    funds = session.query(sandbox.SandboxFunds).filter_by(user_id="alice").one()
    assert funds.available_balance == before and funds.used_margin == 0
    assert not has_protected_portfolio("alice")


def test_real_sandbox_fill_import_is_account_scoped_and_repeatable(
    ledger, sandbox_ledger, monkeypatch
):
    from database import token_db

    sandbox, session = sandbox_ledger
    monkeypatch.setattr(
        token_db, "get_symbol_info", lambda *_: SimpleNamespace(tick_size=Decimal(".05"))
    )
    asset, payload = setup_paper()
    placed = paper.place("alice", payload)
    assert placed["status"] == "active"
    gtt = session.query(sandbox.SandboxGTT).filter_by(gtt_id=placed["gtt_id"]).one()
    gtt.gtt_status = "triggered"
    session.add(
        sandbox.SandboxOrders(
            user_id="alice",
            orderid="FILLED",
            strategy=paper.tag(placed["id"]),
            symbol="ATHER",
            exchange="NSE",
            product="CNC",
            action="BUY",
            quantity=10,
            filled_quantity=10,
            pending_quantity=0,
            average_price=95,
            price_type="LIMIT",
            order_status="complete",
        )
    )
    session.add(
        sandbox.SandboxTrades(
            user_id="alice",
            tradeid="TRADE",
            orderid="FILLED",
            symbol="ATHER",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=95,
            product="CNC",
            trade_timestamp=datetime(2026, 10, 1, 10),
        )
    )
    session.commit()
    session.remove()
    assert paper.reconcile("bob")["imported"] == 0
    assert paper.reconcile("alice")["imported"] == 1
    assert paper.reconcile("alice")["imported"] == 0
    assert holding(asset)["invested"] == "950.0000"


def test_concurrent_idempotent_paper_requests_dispatch_once(ledger, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    _, payload = setup_paper()
    calls = []
    monkeypatch.setattr(
        paper,
        "dispatch",
        lambda *_: calls.append(1) or (True, {"mode": "analyze", "trigger_id": "ONE"}, 200),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: paper.place("alice", payload), range(2)))
    assert len(calls) == 1
    assert results[0]["id"] == results[1]["id"]


def test_split_requires_a_price_in_post_split_units(ledger):
    account, asset = seed()
    trade(asset, quantity="10", price="100")
    s.set_price("alice", asset["id"], "110", datetime(2026, 9, 2))
    trade(asset, "CORPORATE_ACTION", "1", "0", "2026-09-03", corporate_ratio="2", notes="2 for 1")
    assert holding(asset)["quantity"] == "20.000000"
    assert holding(asset)["market_value"] is None
    curve = reports.build("alice", "performance", account["id"], "2026-09-01", "2026-09-04")
    assert (
        next(r for r in curve["rows"] if r["date"] == "2026-09-02")["market_value"] == "1100.0000"
    )
    assert curve["rows"][-1]["market_value"] is None
    s.set_price("alice", asset["id"], "55", datetime(2026, 9, 4))
    assert holding(asset)["market_value"] == "1100.0000"


def test_tiny_fractional_cost_does_not_break_portfolio_score(ledger):
    _, asset = seed()
    trade(asset, quantity="0.000001", price="0.0001")
    assert s.dashboard("alice")["score"]["quality"] is None


def test_fill_reconciliation_rolls_back_mismatched_order_without_reporting_import(
    ledger, monkeypatch
):
    asset, payload = setup_paper()
    monkeypatch.setattr(
        paper, "dispatch", lambda *_: (True, {"mode": "analyze", "trigger_id": "GTT"}, 200)
    )
    paper.place("alice", payload)
    fill = {
        "order_id": "ONE",
        "symbol": "ATHER",
        "exchange": "NSE",
        "product": "CNC",
        "action": "BUY",
        "quantity": 10,
        "price": "95",
        "timestamp": datetime(2026, 10, 1, 10),
    }
    monkeypatch.setattr(
        paper,
        "sandbox_snapshot",
        lambda *_: {
            "gtt_id": "GTT",
            "status": "triggered",
            "fills": [fill, {**fill, "order_id": "TWO", "symbol": "WRONG"}],
        },
    )
    result = paper.reconcile("alice")
    assert result["imported"] == 0 and result["updated"] == 0
    assert "identity mismatch" in result["errors"][0]
    assert holding(asset)["quantity"] == "0.000000"
