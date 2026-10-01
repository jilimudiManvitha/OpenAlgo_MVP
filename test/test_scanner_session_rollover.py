"""Background scanner must not contact a broker with yesterday's session."""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services import market_scanner_live as live
from services import market_scanner_provider as provider
from services.market_scanner_service import IST


@pytest.fixture
def auth(monkeypatch):
    from database import auth_db
    from utils import session

    current = Mock(return_value=False)
    token = Mock(return_value="fixture-token")
    cleanup = Mock()
    monkeypatch.setattr(session, "has_login_this_trading_session", current)
    monkeypatch.setattr(
        auth_db, "get_auth_token_dbquery", lambda user: SimpleNamespace(broker="fyers")
    )
    monkeypatch.setattr(auth_db, "get_auth_token", token)
    monkeypatch.setattr(auth_db, "get_feed_token", lambda user: "fixture-feed")
    monkeypatch.setattr(auth_db, "db_session", SimpleNamespace(remove=cleanup))
    return current, token, cleanup


@pytest.mark.parametrize("entry", ["credentials", "get_fyers_token"])
def test_stale_login_blocks_token_use_and_fresh_login_resumes(entry, auth):
    current, token, cleanup = auth

    def call():
        if entry == "credentials":
            return provider.credentials("alice", "fyers")
        return provider.get_fyers_token("alice")

    with pytest.raises(provider.ScannerError, match="Log in") as caught:
        call()
    assert caught.value.status_code == 401
    token.assert_not_called()
    cleanup.assert_called_once()

    current.return_value = True
    assert call() == (
        ("fixture-token", "fixture-feed") if entry == "credentials" else "fixture-token"
    )
    token.assert_called_once_with("alice", bypass_cache=True)
    assert cleanup.call_count == 2


def test_background_boot_pauses_before_provider_creation_and_resumes(auth, tmp_path, monkeypatch):
    current, token, cleanup = auth
    now = datetime(2026, 10, 1, 8, 30, tzinfo=IST)
    monkeypatch.setattr(live, "now_ist", lambda: now)
    monkeypatch.setattr(live, "market_open", lambda now: False)
    factory = Mock(return_value=object())
    monkeypatch.setattr(provider, "FyersScannerProvider", factory)
    manager = SimpleNamespace(start=Mock(), active=None)
    monkeypatch.setattr(live, "PublishingManager", Mock(return_value=manager))
    store = live.LiveStore("sqlite:///" + (tmp_path / "scanner.db").as_posix())
    coordinator = live.LiveCoordinator(store)
    key = store.configure("alice", "fyers")
    try:
        coordinator.tick()
        factory.assert_not_called()
        manager.start.assert_not_called()
        snapshot = json.loads(store.accounts()[0]["snapshot"])
        assert snapshot["state"] == "failed" and snapshot["stale"]
        assert "Log in" in snapshot["error"]
        assert not coordinator.managers
        current.return_value = True
        store.publish(key, snapshot, due=0)
        coordinator.tick()
        factory.assert_called_once_with("fixture-token")
        manager.start.assert_called_once()
        assert coordinator.managers[key] is manager
        assert cleanup.call_count == 2
    finally:
        coordinator.close()
