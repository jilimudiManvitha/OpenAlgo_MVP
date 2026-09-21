"""Isolated localhost alert dashboard. Only market-data endpoints are called."""

import argparse
import json
import math
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import websocket
from dotenv import load_dotenv
from engine import INTERVALS, Crossing, epoch, history_rows, price
from flask import Flask, abort, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent


def validate_watch(data, connections):
    result = {}
    for field in ("connection", "symbol", "exchange", "interval", "mode", "side"):
        if not isinstance(data.get(field), str):
            raise ValueError(f"Missing {field}")
        result[field] = data[field].strip()
    if result["connection"] not in connections:
        raise ValueError("Choose a configured connection")
    for field in ("symbol", "exchange"):
        result[field] = result[field].upper()
        if not re.fullmatch(r"[A-Z0-9_.&+:/-]{1,64}", result[field]):
            raise ValueError(f"Invalid {field}")
    if result["interval"] not in INTERVALS:
        raise ValueError("Unsupported timeframe")
    if result["mode"] not in ("live", "close") or result["side"] not in ("both", "upper", "lower"):
        raise ValueError("Invalid trigger")
    period, deviation = data.get("period"), data.get("deviation")
    if type(period) is not int or not 2 <= period <= 200:
        raise ValueError("Period must be an integer from 2 to 200")
    if isinstance(deviation, bool) or not isinstance(deviation, (float, int)):
        raise ValueError("Invalid standard deviation")
    if not math.isfinite(deviation) or not 0.1 <= deviation <= 10:
        raise ValueError("Standard deviation must be from 0.1 to 10")
    result.update(period=period, deviation=float(deviation), enabled=True)
    return result


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS watches(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, watch TEXT, band TEXT, bar REAL, data TEXT,
                    UNIQUE(watch, band, bar));
            """)

    def connect(self):
        from contextlib import contextmanager

        @contextmanager
        def connection():
            db = sqlite3.connect(self.path, timeout=10)
            try:
                with db:
                    yield db
            finally:
                db.close()

        return connection()

    def watches(self):
        with self.connect() as db:
            return [
                dict(json.loads(data), id=key)
                for key, data in db.execute("SELECT id,data FROM watches")
            ]

    def save(self, item):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO watches VALUES (?,?)", (item["id"], json.dumps(item))
            )

    def delete(self, key):
        with self.connect() as db:
            db.execute("DELETE FROM watches WHERE id=?", (key,))

    def event(self, watch, event):
        data = dict(
            event,
            symbol=watch["symbol"],
            exchange=watch["exchange"],
            connection=watch["connection"],
            interval=watch["interval"],
            mode=watch["mode"],
        )
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO events(watch,band,bar,data) VALUES (?,?,?,?)",
                (watch["id"], event["band"], event["bar"], json.dumps(data)),
            )
            db.execute(
                "DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-10000 FROM events)"
            )

    def events(self):
        with self.connect() as db:
            return [
                dict(json.loads(data), id=key)
                for key, data in db.execute("SELECT id,data FROM events ORDER BY id DESC LIMIT 100")
            ]


class Feed:
    def __init__(self, connection, symbols):
        self.connection, self.symbols = connection, symbols
        self.messages = queue.Queue(maxsize=20000)
        self.stop = threading.Event()
        self.overflow = threading.Event()
        self.status = "Connecting"
        self.socket = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def put(self, data):
        try:
            self.messages.put_nowait(data)
        except queue.Full:
            self.overflow.set()

    def message(self, ws, raw):
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Invalid feed response")
            if data.get("type") == "auth" and data.get("status") == "success":
                self.status = "Subscribing"
                ws.send(json.dumps({"action": "subscribe", "symbols": self.symbols, "mode": "LTP"}))
            elif data.get("type") == "subscribe":
                self.status = (
                    "Streaming"
                    if data.get("status") == "success"
                    else "Subscription refused or partial"
                )
            elif data.get("type") == "market_data":
                self.put(data)
            elif data.get("status") == "error" or data.get("type") == "error":
                self.status = "Feed error; check broker login and symbols"
                ws.close()
        except (ValueError, TypeError):
            self.status = "Invalid feed response"

    def run(self):
        delay = 2
        while not self.stop.is_set():
            self.put({"type": "reset"})
            self.socket = websocket.WebSocketApp(
                self.connection["ws"],
                on_message=self.message,
                on_open=lambda ws: ws.send(
                    json.dumps({"action": "authenticate", "api_key": self.connection["key"]})
                ),
                on_error=lambda *_: setattr(self, "status", "Feed unavailable; reconnecting"),
                on_close=lambda *_: setattr(self, "status", "Disconnected; reconnecting"),
            )
            self.socket.run_forever(ping_interval=20, ping_timeout=10)
            self.stop.wait(delay)
            delay = min(60, delay * 2)

    def close(self):
        self.stop.set()
        if self.socket:
            self.socket.close()
        self.thread.join(timeout=2)


class Monitor:
    def __init__(self, store, connections):
        self.store, self.connections = store, connections
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.stop = threading.Event()
        self.rows, self.feeds, self.states = [], {}, {}
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return [
                dict(row, **self.states.get(row["id"], {}).get("display", {})) for row in self.rows
            ]

    def reload(self):
        for feed in self.feeds.values():
            feed.close()
        self.feeds = {}
        with self.lock:
            self.rows = self.store.watches()
            self.states = {
                row["id"]: {
                    "engine": Crossing(row["period"], row["deviation"], row["side"]),
                    "history": [],
                    "next_history": 0,
                    "last_closed": 0,
                    "display": {"status": "Warming up" if row["enabled"] else "Paused"},
                }
                for row in self.rows
            }
        for name, connection in self.connections.items():
            symbols = {
                (r["symbol"], r["exchange"])
                for r in self.rows
                if r["enabled"] and r["mode"] == "live" and r["connection"] == name
            }
            if symbols and connection["key"]:
                self.feeds[name] = Feed(
                    connection, [{"symbol": s, "exchange": e} for s, e in symbols]
                )

    def fetch_history(self, client, row, now):
        connection = self.connections[row["connection"]]
        if not connection["key"]:
            raise ValueError("API key missing; configure the local .env and restart")
        duration = INTERVALS[row["interval"]]
        # Calendar window covers weekends and holidays without synthesizing bars.
        market_zone = ZoneInfo("Asia/Kolkata") if row["connection"] == "stocks" else UTC
        end = datetime.fromtimestamp(now, market_zone)
        start = end - timedelta(days=max(10, math.ceil(row["period"] * duration / 22500) * 3 + 7))
        response = client.post(
            connection["host"] + "/api/v1/history",
            json={
                "apikey": connection["key"],
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "interval": row["interval"],
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
            },
        )
        if response.status_code != 200:
            raise ValueError(f"History HTTP {response.status_code}; check broker login and symbol")
        payload = response.json()
        if payload.get("status") != "success" or not isinstance(payload.get("data"), list):
            raise ValueError("History unavailable; check symbol, exchange and broker support")
        completed = [
            (ts, close) for ts, close in history_rows(payload["data"]) if ts + duration <= now - 2
        ]
        if len(completed) < row["period"] + 1:
            raise ValueError("Not enough completed candles; waiting for history")
        return completed

    def refresh(self, client, row, state, now):
        self.apply_history(row, state, self.fetch_history(client, row, now), now)

    def apply_history(self, row, state, completed, now):
        duration = INTERVALS[row["interval"]]
        state["history"] = completed
        if row["mode"] == "live" and not state["display"].get("timestamp"):
            state["display"]["status"] = "Waiting for fresh timestamped live ticks"
        if row["mode"] == "close":
            newest = completed[-1][0]
            if newest > state["last_closed"]:
                # Establish previous completed bar's relation, then evaluate only the latest
                # newly closed bar. Old/reconnect history is never replayed as live alerts.
                baseline = (
                    not state["last_closed"] or newest - state["last_closed"] > duration * 1.5
                )
                engine = state["engine"]
                engine.reset()
                closes = [close for _, close in completed]
                engine.observe(closes[:-1], completed[-2][0], completed[-2][0])
                event, display = engine.observe(closes, newest, newest)
                state["display"] = dict(display or {}, status="Monitoring candle closes")
                if event and not baseline and now - (newest + duration) <= 90:
                    self.store.event(row, event)
                state["last_closed"] = newest
            if now - (newest + duration) > 90:
                state["display"]["status"] = "No recent completed candle / market closed"
        state["next_history"] = now + (10 if row["mode"] == "close" else 30)

    def tick(self, row, state, message, now):
        data = message.get("data", {})
        if not isinstance(data, dict):
            return
        ts, current = epoch(data.get("timestamp")), price(data.get("ltp"))
        if not 0 <= now - ts <= 30:
            return
        engine = state["engine"]
        if ts < engine.last_timestamp:
            return
        duration = INTERVALS[row["interval"]]
        history = [(stamp, close) for stamp, close in state["history"] if stamp + duration <= ts]
        if len(history) < row["period"] - 1:
            return
        # Use provider candle alignment (e.g. NSE starts at 09:15), not UTC hour flooring.
        last_bar = history[-1][0]
        if not last_bar + duration <= ts < last_bar + 2 * duration:
            state["display"]["status"] = "Waiting for latest completed candle"
            state["next_history"] = min(state["next_history"], now + 2)
            return
        if engine.last_timestamp and ts - engine.last_timestamp > 30:
            engine.reset()
        closes = [close for _, close in history[-(row["period"] - 1) :]] + [current]
        event, display = engine.observe(closes, ts, last_bar + duration)
        if display:
            state["display"] = dict(display, status="Monitoring live ticks")
        if event:
            self.store.event(row, event)

    def run(self):
        with (
            httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client,
            ThreadPoolExecutor(max_workers=2, thread_name_prefix="bb-history") as executor,
        ):
            jobs = {}
            next_request = 0
            generation = 0
            self.reload()
            while not self.stop.is_set():
                if self.changed.is_set():
                    self.changed.clear()
                    generation += 1
                    self.reload()
                for key, (future, job_generation, row) in list(jobs.items()):
                    if not future.done():
                        continue
                    del jobs[key]
                    if job_generation != generation or key not in self.states:
                        continue
                    state = self.states[key]
                    try:
                        with self.lock:
                            self.apply_history(row, state, future.result(), time.time())
                    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
                        with self.lock:
                            state["display"]["status"] = (
                                "History unavailable; check login, symbol, timeframe and API key"
                            )
                            state["history"] = []
                            state["engine"].reset()
                            state["last_closed"] = 0
                            state["next_history"] = time.time() + 30
                for row in self.rows:
                    if not row["enabled"] or self.stop.is_set():
                        continue
                    state = self.states[row["id"]]
                    now = time.time()
                    if (
                        now >= state["next_history"]
                        and now >= next_request
                        and row["id"] not in jobs
                        and len(jobs) < 2
                        and not any(
                            job_row["connection"] == row["connection"]
                            for _, _, job_row in jobs.values()
                        )
                    ):
                        future = executor.submit(self.fetch_history, client, row, now)
                        jobs[row["id"]] = (future, generation, row)
                        next_request = now + 0.4
                for name, feed in self.feeds.items():
                    relevant = [
                        r
                        for r in self.rows
                        if r["enabled"] and r["mode"] == "live" and r["connection"] == name
                    ]
                    if feed.overflow.is_set():
                        feed.overflow.clear()
                        while not feed.messages.empty():
                            try:
                                feed.messages.get_nowait()
                            except queue.Empty:
                                break
                        for row in relevant:
                            self.states[row["id"]]["engine"].reset()
                    for _ in range(20000):
                        try:
                            message = feed.messages.get_nowait()
                        except queue.Empty:
                            break
                        for row in relevant:
                            state = self.states[row["id"]]
                            with self.lock:
                                if message.get("type") == "reset":
                                    state["engine"].reset()
                                    state["history"] = []
                                    state["next_history"] = 0
                                elif (
                                    message.get("symbol") == row["symbol"]
                                    and message.get("exchange") == row["exchange"]
                                ):
                                    try:
                                        self.tick(row, state, message, time.time())
                                    except (ValueError, TypeError, KeyError, OverflowError):
                                        pass
                    for row in relevant:
                        with self.lock:
                            display = self.states[row["id"]]["display"]
                            display["feed"] = feed.status
                            if display.get("timestamp") and time.time() - display["timestamp"] > 30:
                                display["status"] = "Stale / market closed / no recent ticks"
                self.stop.wait(0.2)
        for feed in self.feeds.values():
            feed.close()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=20)


def connections_from_env():
    result = {}
    for name, port, wsport in (("stocks", 5000, 8765), ("crypto", 5001, 8766)):
        prefix = "BB_" + name.upper()
        host = os.getenv(prefix + "_HOST", f"http://127.0.0.1:{port}").rstrip("/")
        ws = os.getenv(prefix + "_WS", f"ws://127.0.0.1:{wsport}")
        for url, protocols in ((host, ("http", "https")), (ws, ("ws", "wss"))):
            parsed = urlparse(url)
            if (
                parsed.scheme not in protocols
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError(f"Invalid {name} connection URL")
            if parsed.scheme in ("http", "ws") and parsed.hostname not in (
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                raise ValueError("Remote connections require HTTPS/WSS")
        result[name] = {"host": host, "ws": ws, "key": os.getenv(prefix + "_API_KEY", "")}
    return result


def create_app(store, monitor, port=8781):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16384
    token = secrets.token_urlsafe(32)
    mutation_lock = threading.Lock()

    @app.before_request
    def protect():
        if request.host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            abort(403)
        if request.method != "GET" and not secrets.compare_digest(
            request.headers.get("X-Alert-Token", ""), token
        ):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/")
    def index():
        return send_from_directory(ROOT, "index.html")

    @app.get("/api/state")
    def state():
        return jsonify(
            token=token,
            worker_running=bool(monitor.thread and monitor.thread.is_alive()),
            watches=monitor.snapshot(),
            events=store.events(),
            connections=[
                {"id": name, "configured": bool(c["key"])}
                for name, c in monitor.connections.items()
            ],
        )

    @app.post("/api/watches")
    def add():
        try:
            data = request.get_json()
            if not isinstance(data, dict):
                raise ValueError("Expected a watch object")
            row = validate_watch(data, monitor.connections)
            with mutation_lock:
                existing = store.watches()
                if len(existing) >= 20:
                    raise ValueError("Maximum 20 watches per monitor")
                if any(all(w[k] == row[k] for k in row if k != "enabled") for w in existing):
                    raise ValueError("This watch already exists")
                row["id"] = uuid.uuid4().hex
                store.save(row)
            monitor.changed.set()
            return jsonify(status="saved"), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.post("/api/watches/<key>/<action>")
    def change(key, action):
        with mutation_lock:
            row = next((w for w in store.watches() if w["id"] == key), None)
            if row is None:
                abort(404)
            if action == "delete":
                store.delete(key)
            elif action == "toggle":
                row["enabled"] = not row["enabled"]
                store.save(row)
            else:
                abort(400)
        monitor.changed.set()
        return jsonify(status="saved")

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8781)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    store = Store(ROOT / "alerts.sqlite3")
    monitor = Monitor(store, connections_from_env())
    # Bind before starting monitoring: a second instance on this port cannot run alerts.
    from werkzeug.serving import make_server

    server = make_server(
        "127.0.0.1", args.port, create_app(store, monitor, args.port), threaded=True
    )
    monitor.start()
    print(f"Bollinger alerts: http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    finally:
        monitor.close()
        server.server_close()
