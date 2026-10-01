"""Regression tests for the Werkzeug dev-server startup guard.

Issue: Flask-SocketIO raises ``RuntimeError: The Werkzeug web server is not
designed to run in production`` from ``socketio.run()`` when stdin is not a TTY
and ``allow_unsafe_werkzeug`` was not passed. Any non-interactive launch
(``nohup``, launchd, IDE run configuration) therefore died before serving a
single request. These tests pin the decision helper and the app.py wiring.
"""

import ast
from pathlib import Path

import pytest

from utils.server_startup import LOOPBACK_HOSTS, allow_unsafe_werkzeug

APP_PY = Path(__file__).resolve().parents[1] / "app.py"


class TestLoopbackAlwaysAllowed:
    @pytest.mark.parametrize("host", sorted(LOOPBACK_HOSTS))
    def test_loopback_hosts_allowed(self, host, monkeypatch):
        monkeypatch.delenv("FLASK_ALLOW_UNSAFE_WERKZEUG", raising=False)
        assert allow_unsafe_werkzeug(host) is True

    @pytest.mark.parametrize("host", ["127.0.0.2", "localhost.localdomain"])
    def test_other_local_addresses_are_not_treated_as_loopback(self, host, monkeypatch):
        monkeypatch.delenv("FLASK_ALLOW_UNSAFE_WERKZEUG", raising=False)
        assert allow_unsafe_werkzeug(host) is False


class TestNonLoopbackNeedsOptIn:
    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.5"])
    def test_refused_without_opt_in(self, host, monkeypatch):
        monkeypatch.delenv("FLASK_ALLOW_UNSAFE_WERKZEUG", raising=False)
        assert allow_unsafe_werkzeug(host) is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "t", "yes", "on", "TrUe"])
    def test_opt_in_truthy_values(self, value, monkeypatch):
        monkeypatch.setenv("FLASK_ALLOW_UNSAFE_WERKZEUG", value)
        assert allow_unsafe_werkzeug("0.0.0.0") is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "maybe"])
    def test_opt_in_falsy_values(self, value, monkeypatch):
        monkeypatch.setenv("FLASK_ALLOW_UNSAFE_WERKZEUG", value)
        assert allow_unsafe_werkzeug("0.0.0.0") is False

    def test_opt_in_does_not_change_loopback(self, monkeypatch):
        monkeypatch.setenv("FLASK_ALLOW_UNSAFE_WERKZEUG", "false")
        assert allow_unsafe_werkzeug("127.0.0.1") is True

    def test_non_loopback_opt_in_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("FLASK_ALLOW_UNSAFE_WERKZEUG", "true")
        with caplog.at_level("WARNING", logger="utils.server_startup"):
            assert allow_unsafe_werkzeug("0.0.0.0") is True
        assert "FLASK_ALLOW_UNSAFE_WERKZEUG" in caplog.text


class TestAppPyWiring:
    def test_socketio_run_passes_the_flag(self):
        tree = ast.parse(APP_PY.read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "socketio"
        ]
        assert calls, "socketio.run() call not found in app.py"
        for call in calls:
            keywords = {kw.arg for kw in call.keywords}
            assert "allow_unsafe_werkzeug" in keywords, (
                "socketio.run() must pass allow_unsafe_werkzeug, otherwise a "
                "non-TTY launch aborts with the Werkzeug production error"
            )

    def test_helper_is_imported(self):
        source = APP_PY.read_text()
        assert "from utils.server_startup import allow_unsafe_werkzeug" in source
