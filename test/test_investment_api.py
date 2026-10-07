"""Exercise real Flask endpoints with isolated ledger and real CSRF enforcement."""

import pytest
from flask import Flask, jsonify
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf

from blueprints.investments import investments_bp
from test.test_investment_ledger import ledger


@pytest.fixture
def client(ledger, monkeypatch):  # noqa: F811 - imported pytest fixture
    from utils import session as auth

    monkeypatch.setattr(auth, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.config.update(SECRET_KEY="investment-test-key", TESTING=True)
    CSRFProtect(app)
    app.register_blueprint(investments_bp)

    @app.get("/csrf")
    def token():
        return jsonify(token=generate_csrf())

    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = "alice"
    client.csrf = client.get("/csrf").json["token"]
    return client


def post(client, path, body):
    return client.post("/investments/api/" + path, json=body, headers={"X-CSRFToken": client.csrf})


def test_api_workflow_oversell_and_persistence(client):
    account = post(client, "accounts", {"name": "My Account"}).json["data"]
    asset = post(client, "assets", {"account_id": account["id"], "symbol": "ATHER"}).json["data"]
    body = {
        "asset_id": asset["id"],
        "action": "BUY",
        "quantity": "100",
        "price": "1000",
        "trade_date": "2026-09-01",
        "trade_time": "09:30",
    }
    assert post(client, "transactions", body).status_code == 201
    assert (
        post(client, "transactions", {**body, "action": "SELL", "quantity": "101"}).status_code
        == 409
    )
    assert client.get("/investments/api/dashboard").json["data"]["invested"] == "100000.0000"
    assert client.get("/investments/api/transactions").json["data"][0]["trade_time"] == "09:30:00"
    assert (
        post(
            client,
            f"assets/{asset['id']}/price",
            {"price": "1100", "as_of": "2026-09-30T15:30:00+05:30"},
        ).status_code
        == 200
    )
    assert client.get("/investments/api/dashboard").json["data"]["unrealized_gain"] == "10000.0000"


def test_csrf_is_required_for_every_mutation(client):
    for method, path in [
        ("post", "/accounts"),
        ("patch", "/accounts/1"),
        ("delete", "/transactions/1"),
    ]:
        response = getattr(client, method)("/investments/api" + path, json={})
        assert response.status_code == 400
    assert client.get("/investments/api/accounts").json["data"] == []


def test_missing_identity_cannot_read_or_write(client):
    with client.session_transaction() as session:
        session.pop("user")
    assert client.get("/investments/api/accounts").status_code == 401
    assert post(client, "accounts", {"name": "No owner"}).status_code == 401


def test_cross_user_api_returns_not_found(client):
    row = post(client, "accounts", {"name": "Private"}).json["data"]
    with client.session_transaction() as session:
        session["user"] = "bob"
    response = client.patch(
        f"/investments/api/accounts/{row['id']}",
        json={"name": "Taken"},
        headers={"X-CSRFToken": client.csrf},
    )
    assert response.status_code == 404
    assert client.get("/investments/api/accounts").json["data"] == []


def test_bad_json_and_pagination_are_validation_errors(client):
    assert post(client, "accounts", []).status_code == 400
    assert client.get("/investments/api/transactions?offset=-1").status_code == 400
    assert post(client, "prices/refresh", {"asset_ids": "all"}).status_code == 400


def test_investment_spa_deep_links_are_registered(monkeypatch):
    from blueprints import react_app

    monkeypatch.setattr(react_app, "serve_react_app", lambda: "Investment SPA")
    app = Flask("investment-deep-links")
    app.register_blueprint(react_app.react_bp)
    client = app.test_client()
    for path in (
        "/portfolio",
        "/portfolio/stocks",
        "/portfolio/stocks/",
        "/portfolio/reports",
        "/portfolio/watchlists",
        "/portfolio/assets/MUTUAL_FUND",
        "/portfolio-backtester",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text == "Investment SPA"
