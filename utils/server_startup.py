import logging
import os

logger = logging.getLogger(__name__)

# Hosts that only this machine can reach. Werkzeug is a development server, but
# on loopback it is reachable from nothing except the operator's own browser.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})


def _env_flag(name: str) -> bool:
    return os.getenv(name, "False").lower() in ("true", "1", "t", "yes", "on")


def allow_unsafe_werkzeug(host_ip: str) -> bool:
    """Whether Flask-SocketIO may serve on Werkzeug's development server.

    Flask-SocketIO raises ``RuntimeError: The Werkzeug web server is not
    designed to run in production`` whenever the process has no TTY on stdin
    and ``allow_unsafe_werkzeug`` was not passed. That kills the whole OpenAlgo
    instance before it can serve a request, so any non-interactive launch
    (``nohup``, launchd, an IDE run configuration, ``uv run app.py &`` from a
    script) dies with the error instead of starting. Interactive terminals pass
    the check and were unaffected, which is why the failure looked random.

    Loopback binds are allowed unconditionally: the listener is reachable only
    from this machine, which is the documented local-development setup. Any
    other bind keeps Flask-SocketIO's refusal, so exposing OpenAlgo on a LAN or
    public address still requires an explicit opt-in via
    ``FLASK_ALLOW_UNSAFE_WERKZEUG=true`` in .env, with a warning logged
    because Werkzeug is not a production WSGI server.

    Args:
        host_ip: The address Flask-SocketIO will bind (``FLASK_HOST_IP``).

    Returns:
        bool: True to pass ``allow_unsafe_werkzeug=True`` to ``socketio.run()``.
    """
    if host_ip in LOOPBACK_HOSTS:
        return True
    if _env_flag("FLASK_ALLOW_UNSAFE_WERKZEUG"):
        logger.warning(
            "FLASK_ALLOW_UNSAFE_WERKZEUG is set: serving FLASK_HOST_IP=%s on "
            "Werkzeug's development server. Put a production WSGI server and a "
            "TLS-terminating reverse proxy in front before exposing this.",
            host_ip,
        )
        return True
    return False
