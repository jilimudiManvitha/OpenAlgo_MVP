"""Persistent live orchestration around the existing scanner engine.

One elected coordinator per database; account-scoped jobs and snapshots are shared
by every web worker/tab. No broker credentials are persisted here.
"""

import atexit
import hashlib
import json
import os
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from database.engine_factory import create_db_engine
from services.market_scanner_provider import ScannerError, provider_for, universe_for
from services.market_scanner_service import ScannerManager, now_ist, rank_rows, validate_options
from services.stock_categories import INDEXES, import_categories, load_catalog, save_catalog
from utils.real_threading import Event, Lock, Thread


class LiveStore:
    def __init__(self, url=None):
        if url is None:
            path = Path(os.environ.get("SCANNER_LIVE_DB", "db/market_scanner_live.db")).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            url = "sqlite:///" + path.as_posix()
        self.engine = create_db_engine(url)
        with self.engine.begin() as c:
            c.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS scanner_live_accounts "
                    "(account TEXT PRIMARY KEY, user TEXT, broker TEXT, enabled INTEGER, "
                    "options TEXT, snapshot TEXT, due REAL DEFAULT 0)"
                )
            )
            c.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS scanner_live_lease "
                    "(id INTEGER PRIMARY KEY, owner TEXT, expires REAL)"
                )
            )
            c.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS scanner_live_categories "
                    "(id INTEGER PRIMARY KEY, payload TEXT)"
                )
            )

    def configure(self, user, broker, options=None, enabled=None):
        account = hashlib.sha256(f"{user}\0{broker}".encode()).hexdigest()
        with self.engine.begin() as c:
            row = (
                c.execute(
                    text("SELECT * FROM scanner_live_accounts WHERE account=:a"), {"a": account}
                )
                .mappings()
                .first()
            )
            if (
                row is None
                and c.execute(text("SELECT count(*) FROM scanner_live_accounts")).scalar() >= 16
            ):
                raise ScannerError("Scanner account capacity reached (16).", 409)
            selected = validate_options(
                options
                if options is not None
                else json.loads(row["options"])
                if row
                else {"limit": 50}
            )
            active = bool(enabled) if enabled is not None else bool(row["enabled"]) if row else True
            c.execute(
                text(
                    "INSERT INTO scanner_live_accounts(account,user,broker,enabled,options) "
                    "VALUES(:a,:u,:b,:e,:o) ON CONFLICT(account) DO UPDATE SET "
                    "enabled=:e, options=:o, due=CASE WHEN options!=:o OR enabled!=:e THEN 0 ELSE due END"
                ),
                {"a": account, "u": user, "b": broker, "e": int(active), "o": json.dumps(selected)},
            )
            # An account switch stops the old account, without sharing its snapshot.
            c.execute(
                text("UPDATE scanner_live_accounts SET enabled=0 WHERE user=:u AND broker!=:b"),
                {"u": user, "b": broker},
            )
        return account

    def accounts(self):
        with self.engine.connect() as c:
            return [
                dict(r) for r in c.execute(text("SELECT * FROM scanner_live_accounts")).mappings()
            ]

    def elect(self, owner, now, ttl=20):
        with self.engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO scanner_live_lease(id,owner,expires) VALUES(1,:o,:e) "
                    "ON CONFLICT(id) DO UPDATE SET owner=:o,expires=:e "
                    "WHERE scanner_live_lease.owner=:o OR scanner_live_lease.expires<=:n"
                ),
                {"o": owner, "e": now + ttl, "n": now},
            )
            return (
                c.execute(text("SELECT owner FROM scanner_live_lease WHERE id=1")).scalar() == owner
            )

    def owns(self, owner):
        with self.engine.connect() as c:
            return bool(
                c.execute(
                    text("SELECT 1 FROM scanner_live_lease WHERE id=1 AND owner=:o AND expires>:n"),
                    {"o": owner, "n": time.time()},
                ).scalar()
            )

    def release(self, owner):
        with self.engine.begin() as c:
            c.execute(text("DELETE FROM scanner_live_lease WHERE owner=:o"), {"o": owner})

    def publish(self, account, snapshot, due=None, owner=None):
        with self.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE scanner_live_accounts SET snapshot=:s, due=COALESCE(:d,due) "
                    "WHERE account=:a AND (:o IS NULL OR EXISTS "
                    "(SELECT 1 FROM scanner_live_lease WHERE id=1 AND owner=:o AND expires>:n))"
                ),
                {
                    "a": account,
                    "s": json.dumps(snapshot, allow_nan=False),
                    "d": due,
                    "o": owner,
                    "n": time.time(),
                },
            )

    def categories(self, imported=None):
        with self.engine.begin() as c:
            if imported is not None:
                c.execute(
                    text(
                        "INSERT INTO scanner_live_categories VALUES(1,:p) "
                        "ON CONFLICT(id) DO UPDATE SET payload=:p"
                    ),
                    {"p": json.dumps(imported)},
                )
            payload = c.execute(
                text("SELECT payload FROM scanner_live_categories WHERE id=1")
            ).scalar()
        return json.loads(payload) if payload else {}

    def import_catalog(self, root=None):
        catalog = load_catalog(root)
        save_catalog(self.engine, catalog)
        return catalog["categories"]


def view_snapshot(snapshot, options, categories, category="all", now=None):
    now = now or now_ist()
    result = dict(snapshot or {})
    rows = [dict(r) for r in result.pop("rows", [])]
    stale = result.get("session_date") != now.date().isoformat()
    if stale:
        rows = []
    if options.get("symbols") is not None:
        selected = set(options["symbols"])
        rows = [row for row in rows if row["symbol"] in selected]
    previous_options = result.get("options", {})
    if previous_options.get("lookback_days", options["lookback_days"]) != options["lookback_days"]:
        for row in rows:
            row.update(
                rvol=None,
                average_volume=None,
                baseline_dates=[],
                baseline_status="baseline_refresh_pending",
            )
    if category != "all":
        if category not in categories:
            raise ScannerError("Unknown or unavailable index category.")
        members = set(categories[category]["symbols"])
        rows = [r for r in rows if r["symbol"] in members]
    for row in rows:
        row["volume_change_percent"] = None if row["rvol"] is None else (row["rvol"] - 1) * 100
        stamp = datetime.fromisoformat(row["quote_fetched_at"])
        row["stale"] = (now - stamp).total_seconds() > 120
    result.update(rank_rows(rows, options))
    result.update(
        stale=stale,
        options=options,
        category=category,
        filtered_quotes=len(rows),
        market_open=market_open(now),
        server_time=now.isoformat(),
        transport=result.get("transport", "batched_polling"),
        refresh_seconds=1,
        membership=categories.get(category),
    )
    # Membership symbols are internal; provenance remains visible.
    if result["membership"]:
        result["membership"] = {k: v for k, v in result["membership"].items() if k != "symbols"}
    return result


def market_open(now):
    from database.market_calendar_db import db_session, get_effective_session_window

    try:
        window = get_effective_session_window(now.date(), "NSE")
        return bool(window and window["start_ms"] <= now.timestamp() * 1000 <= window["end_ms"])
    finally:
        db_session.remove()


class PublishingManager(ScannerManager):
    def __init__(self, store, account, owner, series, **kwargs):
        super().__init__(**kwargs)
        self.store, self.account, self.owner, self.series = store, account, owner, series
        self.last_publish = 0
        self.last_auth_check = 0
        self.feed = None
        self.prior_snapshot = None
        self.observation_lock = Lock()

    def _check_stop(self, job):
        super()._check_stop(job)
        if not self.store.owns(self.owner):
            raise ScannerError("Scanner ownership changed.", 499)
        if time.monotonic() - self.last_auth_check > 5:
            from services.market_scanner_provider import credentials

            credentials(job["user"], self.broker)
            self.last_auth_check = time.monotonic()

    def _update(self, job, **values):
        if "rows" in values:
            if self.feed:
                values["rows"] = self.feed.merge(values["rows"], self.clock())
            with self.observation_lock:
                for row in values["rows"]:
                    key = (job["session_date"], row["symbol"])
                    points = self.series.setdefault(key, deque(maxlen=120))
                    stamp = row["last_trade_at"]
                    if not points or stamp > points[-1][0]:
                        points.append([stamp, row["ltp"]])
                    row["sparkline"] = list(points)
                    row["sparkline_basis"] = "since connected"
        super()._update(job, **values)
        if self.store.owns(self.owner) and (
            time.monotonic() - self.last_publish >= 0.5 or values.get("state")
        ):
            self.last_publish = time.monotonic()
            with self.lock:
                result = self._snapshot(job)
                result["rows"] = list(job["rows"])
            if (
                not result["rows"]
                and self.prior_snapshot
                and self.prior_snapshot.get("session_date") == job["session_date"]
            ):
                result["rows"] = self.prior_snapshot.get("rows", [])
            if self.feed:
                result.update(transport=self.feed.status, streaming_symbols=self.feed.subscribed)
            self.store.publish(self.account, result, owner=self.owner)


class LiveCoordinator:
    def __init__(self, store=None):
        self.store = store or LiveStore()
        self.owner = uuid.uuid4().hex
        self.stop_event = Event()
        self.managers = {}
        self.series = {}
        self.feeds = {}
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = Thread(target=self._loop, daemon=True, name="scanner-live-coordinator")
            self.thread.start()
            atexit.register(self.close)

    def tick(self):
        if not self.store.elect(self.owner, time.time()):
            self._cancel_all()
            return
        now = now_ist()
        for key, manager in list(self.managers.items()):
            if manager.active:
                continue
            if manager.jobs:
                job = next(iter(manager.jobs.values()))
                result = manager._snapshot(job)
                result["rows"] = job["rows"]
                result["closed_snapshot"] = not market_open(now) and job["state"] == "completed"
                delay = 120 if job["state"] == "failed" else 60
                self.store.publish(key, result, time.time() + delay, owner=self.owner)
            if manager._cache is not None:
                manager._cache.engine.dispose()
            del self.managers[key]
        for account in self.store.accounts():
            key = account["account"]
            feed = self.feeds.get(key)
            if (not account["enabled"] or not market_open(now)) and feed:
                feed.close()
                del self.feeds[key]
                feed = None
            if account["enabled"] and market_open(now) and feed is None:
                from services.market_scanner_feed import ScannerFeed

                feed = ScannerFeed(account["user"], account["broker"], self.store, self.owner)
                self.feeds[key] = feed
                feed.start()
            existing = self.managers.get(key)
            if existing and existing.active:
                if (
                    not account["enabled"]
                    or json.loads(account["options"]) != existing.jobs[account["user"]]["options"]
                ):
                    existing.cancel(account["user"])
                elif feed:
                    with existing.lock:
                        rows = list(existing.jobs[account["user"]]["rows"])
                    updated = feed.merge(rows, now)
                    if any(a is not b for a, b in zip(rows, updated, strict=False)):
                        existing._update(existing.jobs[account["user"]], rows=updated)
                continue
            if account["enabled"] and feed and account["snapshot"]:
                saved = json.loads(account["snapshot"])
                if saved.get("session_date") == now.date().isoformat():
                    updated = feed.merge(saved.get("rows", []), now)
                    if updated != saved.get("rows", []):
                        for row in updated:
                            series_key = (saved["session_date"], row["symbol"])
                            points = self.series.setdefault(key, {}).setdefault(
                                series_key, deque(row.get("sparkline", []), maxlen=120)
                            )
                            if not points or row["last_trade_at"] > points[-1][0]:
                                points.append([row["last_trade_at"], row["ltp"]])
                            row["sparkline"] = list(points)
                        saved.update(
                            rows=updated,
                            updated_at=now.isoformat(),
                            transport=feed.status,
                            streaming_symbols=feed.subscribed,
                        )
                        self.store.publish(key, saved, owner=self.owner)
            if not account["enabled"] or account["due"] > time.time():
                continue
            old = json.loads(account["snapshot"]) if account["snapshot"] else {}
            # One closing snapshot, then wait for the next regular session.
            if (
                not market_open(now)
                and old.get("session_date") == now.date().isoformat()
                and old.get("closed_snapshot")
                and old.get("options") == json.loads(account["options"])
            ):
                continue
            try:
                provider = provider_for(account["user"], account["broker"])
                points = self.series.setdefault(key, {})
                for series_key in list(points):
                    if series_key[0] != now.date().isoformat():
                        del points[series_key]
                manager = PublishingManager(
                    self.store,
                    key,
                    self.owner,
                    points,
                    provider_factory=lambda user, p=provider: p,
                    universe_loader=lambda b=account["broker"]: universe_for(b),
                )
                manager.broker = account["broker"]
                manager.feed = feed
                manager.prior_snapshot = old
                self.managers[key] = manager
                manager.start(account["user"], json.loads(account["options"]))
            except ScannerError as exc:
                old.update(error=str(exc), state="failed", stale=True)
                self.store.publish(key, old, time.time() + 120, owner=self.owner)

    def _loop(self):
        from utils.logging import get_logger

        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                get_logger(__name__).exception("Live scanner coordinator failed")
            self.stop_event.wait(0.5)

    def _cancel_all(self):
        for feed in self.feeds.values():
            feed.close()
        self.feeds.clear()
        for manager in self.managers.values():
            if manager.active:
                manager.cancel(manager.active)

    def close(self):
        self.stop_event.set()
        self._cancel_all()
        self.store.release(self.owner)
        if self.thread:
            self.thread.join(timeout=6)
        self.store.engine.dispose()


_coordinator = None
_lock = Lock()


def coordinator():
    global _coordinator
    with _lock:
        if _coordinator is None:
            _coordinator = LiveCoordinator()
            _coordinator.start()
    return _coordinator
