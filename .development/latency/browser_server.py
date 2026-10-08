"""Real isolated latency API with synthetic data; no app, broker or scheduler."""

import json
import os
import runpy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "test/conftest.py"))
os.environ["LATENCY_DATABASE_URL"] = "sqlite:///" + str(ROOT / "log/test/latency/browser.db")
from flask import Flask, jsonify, send_from_directory, session
from flask_wtf.csrf import generate_csrf
from load import module

import utils.session as auth
from database.latency_db import LatencyBase, OrderLatency, latency_engine

auth.is_session_valid = lambda: session.get("user") == "latency_fixture"
module("services.latency_report")
bp = module("blueprints.latency")
LatencyBase.metadata.drop_all(latency_engine)
LatencyBase.metadata.create_all(latency_engine)
now = datetime.now(UTC).replace(tzinfo=None)
with latency_engine.begin() as conn:
    for i in range(125):
        conn.execute(
            OrderLatency.__table__.insert().values(
                timestamp=now - timedelta(seconds=125 - i),
                order_id=f"fixture-{i}",
                broker="fyers",
                symbol="SBIN",
                order_type="PLACE",
                total_latency_ms=100 if i < 105 else 800,
                rtt_ms=60,
                overhead_ms=40 if i < 105 else 740,
                status="SUCCESS",
                request_body={"latency_meta": {"version": 2, "mode": "sandbox", "http_calls": 2}},
            )
        )
    for _i in range(5):
        conn.execute(
            OrderLatency.__table__.insert().values(
                timestamp=now,
                order_id="unknown",
                broker="fyers",
                order_type="PLACE",
                total_latency_ms=2,
                rtt_ms=0,
                overhead_ms=2,
                status="FAILED",
                error="Invalid API key",
            )
        )
    for _i in range(12):
        conn.execute(
            OrderLatency.__table__.insert().values(
                timestamp=now,
                order_id="unknown",
                broker="fyers",
                symbol="SBIN",
                order_type="HISTORY",
                total_latency_ms=1000,
                rtt_ms=90,
                overhead_ms=910,
                status="SUCCESS",
            )
        )
PREVIEW = ROOT / ".development/latency/dist"
app = Flask(__name__, static_folder=str(PREVIEW / "assets"), static_url_path="/assets")
app.secret_key = "latency-isolated-fixture"
app.register_blueprint(bp.latency_bp)


@app.get("/auth/session-status")
def login():
    session["user"] = "latency_fixture"
    session["broker"] = "fyers"
    return jsonify(
        status="success", logged_in=True, user=session["user"], broker="fyers", active_sessions=1
    )


@app.get("/auth/csrf-token")
def csrf():
    return jsonify(csrf_token=generate_csrf())


@app.get("/auth/analyzer-mode")
def mode():
    return jsonify(status="success", data={"analyze_mode": True})


@app.get("/api/broker/capabilities")
def broker():
    return jsonify(
        status="success",
        data={
            "broker_name": "fyers",
            "broker_type": "IN_stock",
            "supported_exchanges": ["NSE", "NFO"],
        },
    )


@app.get("/logs/latency")
def page():
    return send_from_directory(PREVIEW, "index.html")


if __name__ == "__main__":
    (ROOT / "log/dev").mkdir(exist_ok=True, parents=True)
    (ROOT / "log/dev/latency-preview.json").write_text(
        json.dumps({"pid": os.getpid(), "port": 5011, "command": str(Path(__file__).resolve())})
    )
    app.run(host="127.0.0.1", port=5011, use_reloader=False)
