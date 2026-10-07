"""Explicit published retail examples and integration with isolated report data."""

import importlib.util
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from services.report_brokerage import (
    capture_context,
    charges_csv,
    estimate_report,
    order_cost,
    tariff,
)
from services.report_journal import journal, journal_detail
from services.scanner_strategy_reports import ReportStore
from test.test_report_journal import report, stamp, trade


def sample(broker="fyers", **changes):
    t = {
        **trade(gross=100, fees=0),
        "exit": 110,
        "side": 1,
        "exchange": "NSE",
        "product": "MIS",
        "entry_order": "buy-1",
        "exit_order": "sell-1",
        **changes,
    }
    r = report("2026-10-07", "demo", [t])
    if broker:
        r["broker"] = broker
    return r


@pytest.mark.parametrize(
    "broker,expected",
    [
        ("fyers", 6.3),
        ("zerodha", 6.3),
        ("dhan", 6.3),
        ("groww", 21),
        ("angel", 21),
        ("upstox", 21),
        ("shoonya", 6.3),
        ("flattrade", 0),
    ],
)
def test_standard_intraday_brokerage_both_executed_orders(broker, expected):
    r = sample(broker, quantity=100)
    result = estimate_report(r)
    assert result["trades"][0]["charge_breakdown"]["brokerage"] == expected
    assert r["trades"][0]["fees"] == 0  # Original payload is untouched.


def test_fyers_exact_example_and_net_after_all_costs():
    t = estimate_report(sample(quantity=100))["trades"][0]
    assert t["charge_breakdown"] == {
        "brokerage": 6.3,
        "stt": 2.75,
        "exchange": 0.65,
        "sebi": 0.02,
        "stamp": 0.3,
        "ipft": 0,
        "clearing": 0,
        "gst": 1.26,
    }
    assert t["fees"] == 11.28
    assert t["net_pnl"] == 88.72


@pytest.mark.parametrize(
    "broker,want", [("fyers", 40), ("zerodha", 40), ("dhan", 40), ("shoonya", 10), ("flattrade", 0)]
)
def test_option_long_and_short_brokerage(broker, want):
    r = sample(
        broker,
        symbol="NIFTY13OCT2626000CE",
        exchange="NFO",
        product="NRML",
        quantity=75,
        side=-1,
        entry=100,
        exit=80,
        gross_pnl=1500,
    )
    result = estimate_report(r)["trades"][0]
    assert result["charge_breakdown"]["brokerage"] == want
    assert result["charge_breakdown"]["stt"] == 11.25  # Tax short entry sale, not the buy-to-close.
    assert result["charge_breakdown"]["stamp"] == 0.18
    if broker == "fyers":
        assert result["charge_breakdown"]["clearing"] == 1.22


def test_order_cap_partial_rows_and_zero_broker_not_zero_total_cost():
    r = sample("fyers", quantity=1000)
    t = deepcopy(r["trades"][0])
    r["trades"].append(t)
    rows = estimate_report(r)["trades"]
    assert sum(t["charge_breakdown"]["brokerage"] for t in rows) == 40
    assert estimate_report(sample("flattrade"))["trades"][0]["fees"] > 0


def test_actual_fees_override_estimates_without_double_deduction():
    r = sample(fees=9, net_pnl=91, fees_actual=True)
    t = estimate_report(r)["trades"][0]
    assert (t["fees"], t["net_pnl"], t["charge_status"]) == (9, 91, "actual")
    assert "charge_breakdown" not in t
    r["trades"][0]["charge_breakdown"] = {"brokerage": 2.0, "gst": 0.36}
    assert estimate_report(r)["trades"][0]["charge_breakdown"]["brokerage"] == 2.0


def test_unfilled_orders_are_not_charged_and_open_trade_only_has_entry_cost():
    r = sample(exit_ts=None, exit=None, entry_order_state="pending")
    assert estimate_report(r)["trades"][0]["charge_status"] == "unfilled"
    r["trades"][0]["entry_order_state"] = "complete"
    t = estimate_report(r)["trades"][0]
    assert t["charge_breakdown"]["brokerage"] == 0.3
    assert t["entry_estimated_fees"] == t["fees"]
    assert t["net_pnl"] == 0


def test_broker_snapshot_survives_login_and_tariff_changes():
    r = sample("fyers", quantity=1000)
    capture_context("alice", r)
    original = estimate_report(r, "zerodha")
    newer = sample("shoonya", quantity=1000)
    capture_context("alice", newer, r)
    assert newer["brokerage_context"]["broker"] == "fyers"
    assert estimate_report(newer, "dhan")["trades"][0]["fees"] == original["trades"][0]["fees"]
    assert not original["charge_info"]["broker_inferred"]
    from services.report_brokerage import PROFILES

    old_profile = PROFILES["fyers"]
    try:
        PROFILES["fyers"] = tariff("shoonya")
        assert estimate_report(r)["trades"][0]["fees"] == original["trades"][0]["fees"]
    finally:
        PROFILES["fyers"] = old_profile
    legacy = sample(None)
    assert estimate_report(legacy, "groww")["charge_info"]["broker_inferred"]


def test_retail_delivery_differences_and_tax_date_boundaries():
    assert (
        order_cost(10000, "BUY", "NSE", "delivery", "2026-10-07", tariff("fyers"))["brokerage"]
        == 20
    )
    assert (
        order_cost(10000, "BUY", "NSE", "delivery", "2026-10-07", tariff("zerodha"))["brokerage"]
        == 0
    )
    assert order_cost(10000, "SELL", "NFO", "options", "2026-03-31", tariff("zerodha"))["stt"] == 10
    assert order_cost(10000, "SELL", "NFO", "options", "2026-04-01", tariff("zerodha"))["stt"] == 15
    assert (
        order_cost(10000, "BUY", "NSE", "intraday", "2026-02-28", tariff("zerodha"))["exchange"]
        == 0.3
    )
    assert (
        order_cost(10000, "BUY", "NSE", "intraday", "2026-03-01", tariff("zerodha"))["exchange"]
        == 0.31
    )


def test_small_groww_minimum_and_cash_brokerage_ceiling():
    assert (
        order_cost(1000, "BUY", "NSE", "intraday", "2026-10-07", tariff("groww"))["brokerage"] == 5
    )
    assert (
        order_cost(100, "BUY", "NSE", "intraday", "2026-10-07", tariff("groww"))["brokerage"] == 2.5
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"exchange": "MCX"},
        {"entry": float("nan")},
        {"side": None},
        {"exchange": None, "product": None},
    ],
)
def test_missing_or_unsupported_execution_is_explicit(changes):
    assert estimate_report(sample(**changes))["trades"][0]["charge_status"] == "unavailable"


def test_unknown_broker_never_receives_fyers_rates(tmp_path):
    db = tmp_path / "reports.db"
    store = ReportStore(db)
    try:
        store.save("alice", sample("unknown"))
    finally:
        store.close()
    data = journal("alice", 2026, path=db, session_broker="fyers", charge_basis="estimated")
    assert data["totals"]["net_pnl"] is None
    assert data["totals"]["wins"] is None
    assert data["days"][0]["metrics"]["unestimated_trades"] == 1
    assert data["streaks"]["current"] == 0


def test_sandbox_and_live_use_same_fee_rules_and_detail_csv(tmp_path):
    db = tmp_path / "reports.db"
    store = ReportStore(db)
    try:
        paper = sample(None, quantity=100)
        paper["id"] = "paper"
        store.save("alice", paper)
        live = deepcopy(paper)
        live["id"] = "live"
        live["paths"] = ["LIVE"]
        live["trades"][0]["path"] = "LIVE"
        store.save("alice", live)
    finally:
        store.close()
    for scenario in ("PAPER", "LIVE"):
        data = journal(
            "alice", 2026, scenario, path=db, session_broker="fyers", charge_basis="estimated"
        )
        assert data["totals"]["net_pnl"] == 88.72
        assert data["totals"]["brokerage"] == 6.3
    detail = journal_detail("alice", "paper", "fyers", path=db)
    assert detail["metrics"]["PAPER"]["net_pnl"] == 88.72
    csv = charges_csv(detail)
    assert "fyers" in csv and "11.28" in csv and "88.72" in csv
    assert journal_detail("bob", "paper", "fyers", path=db) is None
    assert journal("alice", 2026, path=db, charge_basis="recorded")["totals"]["net_pnl"] == 100


def test_overlay_persists_broker_without_touching_live_reportstore(tmp_path):
    file = Path(".development/report-journal/overlays/services/scanner_strategy_reports.py")
    spec = importlib.util.spec_from_file_location("isolated_report_store", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.ReportStore(tmp_path / "reports.db")
    try:
        r = sample("fyers")
        store.save("alice", r)
        changed = sample("zerodha")
        store.save("alice", changed)
        assert store.get("alice", r["id"])["brokerage_context"]["broker"] == "fyers"
    finally:
        store.close()


def test_context_uses_logged_account_broker_and_releases_session(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from database import auth_db

    query = Mock()
    query.filter.return_value.scalar.return_value = "dhan"
    remove = Mock()
    monkeypatch.setattr(
        auth_db, "db_session", SimpleNamespace(query=lambda *args: query, remove=remove)
    )
    r = sample(None)
    capture_context("alice", r)
    assert r["brokerage_context"]["broker"] == "dhan"
    remove.assert_called_once()
    query.filter.return_value.scalar.side_effect = RuntimeError("database failure")
    with pytest.raises(RuntimeError):
        capture_context("alice", sample(None))
    assert remove.call_count == 2


def test_estimated_api_uses_session_broker_and_scopes_detail_csv(tmp_path, monkeypatch):
    from functools import partial

    from flask import Flask

    from blueprints import market_scanner as routes
    from services import report_journal as service

    db = tmp_path / "reports.db"
    store = ReportStore(db)
    try:
        store.save("alice", sample(None, quantity=100))
    finally:
        store.close()
    monkeypatch.setattr(routes, "is_session_valid", lambda: True)
    monkeypatch.setattr(service, "journal", partial(journal, path=db))
    monkeypatch.setattr(service, "journal_detail", partial(journal_detail, path=db))
    app = Flask(__name__)
    app.secret_key = "isolated"
    app.register_blueprint(routes.market_scanner_bp)
    app.before_request_funcs.clear()
    client = app.test_client()
    url = "/market-scanner/api/report-journal"
    reportid = sample()["id"]
    assert client.get(url + "/" + reportid).status_code == 401
    with client.session_transaction() as session:
        session.update(user="alice", broker="groww")
    result = client.get(url + "?year=2026").json["data"]
    assert result["totals"]["brokerage"] == 21
    detail = client.get(url + "/" + reportid).json["data"]
    assert detail["charge_info"]["broker"] == "groww"
    assert detail["metrics"]["PAPER"]["net_pnl"] == result["totals"]["net_pnl"]
    assert client.get(url + "/" + reportid + "?download=csv").mimetype == "text/csv"
    assert client.get(url + "?charges=wrong").status_code == 400
    assert client.get(url + "/" + reportid + "?charges=wrong").status_code == 400
    with client.session_transaction() as session:
        session["user"] = "bob"
    assert client.get(url + "/" + reportid + "?download=csv").status_code == 404


def test_estimated_net_changes_win_to_loss(tmp_path):
    db = tmp_path / "reports.db"
    store = ReportStore(db)
    try:
        store.save("alice", sample(gross_pnl=1, net_pnl=1, quantity=100))
    finally:
        store.close()
    data = journal("alice", 2026, path=db, charge_basis="estimated")
    assert data["totals"]["wins"] == 0
    assert data["totals"]["losses"] == 1
    assert data["streaks"]["current"] == -1


def test_overlay_metadata_failure_does_not_block_report_persistence(tmp_path, monkeypatch):
    from services import report_brokerage

    def unavailable(*args):
        raise RuntimeError("auth temporarily unavailable")

    monkeypatch.setattr(report_brokerage, "capture_context", unavailable)
    spec = importlib.util.spec_from_file_location(
        "isolated_report_store_failure",
        Path(".development/report-journal/overlays/services/scanner_strategy_reports.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.ReportStore(tmp_path / "reports.db")
    try:
        r = sample(None)
        assert store.claim("alice", r)
        store.save("alice", r)
        saved = store.get("alice", r["id"])
        assert saved["brokerage_capture_status"] == "unavailable"
        assert len(saved["trades"]) == 1
    finally:
        store.close()
