"""Durable, bounded local copier. One engine owns the local database lock.

The transaction commits intent BEFORE fan-out. Interrupted SUBMITTING becomes
UNKNOWN on restart. No startup replay/resubmission. Arming baselines existing
master orders, so connecting a child never copies historical trades.
"""

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from decimal import Decimal

from sqlalchemy import event as sql_event
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from database.engine_factory import create_db_engine
from services.trade_copier import models as m
from services.trade_copier.adapters import BrokerFailure, Gateway, Native, Paper
from services.trade_copier.domain import CopierError, digest, number, order, packed, policy, today

TERMINAL = ("COMPLETE", "CANCELLED", "REJECTED", "EXPIRED", "BLOCKED")


class Engine:
    def __init__(
        self, url, encrypt, decrypt, source, context, instrument, transport=None, workers=16
    ):
        self.db = create_db_engine(url)
        if self.db.dialect.name == "sqlite":
            # Override the application's NORMAL setting only for the copier audit
            # DB: an acknowledged intent must survive a host power interruption.
            def durable_connection(connection, _record):
                cursor = connection.cursor()
                try:
                    cursor.execute("PRAGMA synchronous=FULL")
                finally:
                    cursor.close()

            sql_event.listen(self.db, "connect", durable_connection)
        m.Base.metadata.create_all(self.db)
        self.sessions = sessionmaker(bind=self.db, expire_on_commit=False)
        self.encrypt, self.decrypt = encrypt, decrypt
        self.source, self.context, self.instrument = source, context, instrument
        self.transport = transport or self._transport
        self.lock = threading.RLock()
        self.maintenance = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trade-copier")
        self.pending = threading.BoundedSemaphore(256)
        self.stop = threading.Event()
        self.thread = None
        self.bus = None
        self.account_locks = {}
        self.risk_cache = {}  # Account bounded (max 50); refreshed/replaced, not event keyed.
        self.closed = False
        with self.sessions.begin() as s:
            s.execute(
                update(m.Control).values(armed=False, note="Restarted; reconcile and arm again")
            )
            s.execute(
                update(m.Attempt)
                .where(m.Attempt.status.in_(["QUEUED", "SUBMITTING"]))
                .values(status="UNKNOWN", message="Interrupted by restart; no retry sent")
            )

    def _transport(self, a):
        if a.mode == "paper":
            return Paper("cp_" + a.id)
        secret = json.loads(self.decrypt(a.secret))
        if secret.get("connection") == "openalgo":
            return Gateway(secret, a.mode, a.broker)
        return Native(a.broker, secret)

    @staticmethod
    def scope(owner, mode, broker):
        if mode not in ("live", "paper"):
            raise CopierError("Invalid mode")
        return digest(owner, mode, broker)

    def audit(self, s, owner, mode, action, detail):
        s.add(m.Audit(owner=owner, mode=mode, action=action, detail=detail, created=time.time()))

    def account(self, owner, mode, data, account_id=None):
        config = policy(data)
        name, broker, client_id = (
            str(data.get(k, "")).strip() for k in ("name", "broker", "client_id")
        )
        if (
            not name
            or len(name) > 80
            or not broker
            or len(broker) > 40
            or not client_id
            or len(client_id) > 80
        ):
            raise CopierError("Name, broker and client ID are required")
        import re

        if not re.fullmatch(r"[a-z0-9_]+", broker):
            raise CopierError("Invalid broker")
        secret = data.get("credentials", {})
        if not isinstance(secret, dict):
            raise CopierError("Invalid credentials")
        if mode == "live" and secret:
            if secret.get("connection") == "openalgo":
                from services.trade_copier.adapters import gateway_url

                secret = {
                    "connection": "openalgo",
                    "url": gateway_url(str(secret.get("url", ""))),
                    "api_key": str(secret.get("api_key", "")),
                }
                if not secret["api_key"]:
                    raise CopierError("Child OpenAlgo API key is required")
            else:
                if broker not in ("fyers", "zerodha", "dhan"):
                    raise CopierError("Select OpenAlgo connection for this broker")
                secret = {
                    "connection": "native",
                    "app_id": str(secret.get("app_id", "")),
                    "access_token": str(secret.get("access_token", "")),
                    "client_id": client_id,
                    "instruments": secret.get("instruments", {}),
                }
                if not secret["access_token"] or (broker != "dhan" and not secret["app_id"]):
                    raise CopierError("Broker app ID and access token are required")
                if not isinstance(secret["instruments"], dict) or len(secret["instruments"]) > 100:
                    raise CopierError(
                        "Instrument mappings must be an object with at most 100 symbols"
                    )
                for key, value in secret["instruments"].items():
                    if (
                        key not in config["symbols"]
                        or not isinstance(value, str)
                        or not value
                        or len(value) > 100
                    ):
                        raise CopierError(
                            "Instrument mapping must use an allowed symbol and broker instrument ID"
                        )
        with self.lock, self.sessions.begin() as s:
            if s.scalar(
                select(m.Control).where(m.Control.owner == owner, m.Control.armed.is_(True))
            ):
                raise CopierError("Disarm copying before changing child accounts")
            a = s.get(m.Account, account_id) if account_id else None
            if account_id and (not a or a.owner != owner or a.mode != mode):
                raise CopierError("Child account not found")
            if a and (a.broker != broker or a.client_id != client_id):
                raise CopierError("Create a new child to change its broker/client identity")
            if not a:
                if s.scalar(select(func.count()).select_from(m.Account)) >= 50:
                    raise CopierError("Local copier supports at most 50 child accounts")
                if s.scalar(
                    select(m.Account).where(
                        m.Account.owner == owner,
                        m.Account.mode == mode,
                        m.Account.broker == broker,
                        m.Account.client_id == client_id,
                    )
                ):
                    raise CopierError("This child account is already connected")
                a = m.Account(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    mode=mode,
                    name=name,
                    broker=broker,
                    client_id=client_id,
                    secret="",
                )
                s.add(a)
            if mode == "live" and secret:
                a.secret = self.encrypt(packed(secret))
            if mode == "live" and not a.secret:
                raise CopierError("Connect the child account credentials")
            a.name, a.config, a.enabled, a.health, a.verified_until = (
                name,
                packed(config),
                data.get("enabled", True) is True,
                "AUTH_REQUIRED" if mode == "live" else "READY",
                0,
            )
            self.risk_cache.pop(a.id, None)
            for control in s.scalars(select(m.Control).where(m.Control.owner == owner)):
                control.generation += 1
            self.audit(s, owner, mode, "ACCOUNT_UPDATED", a.id)
            return a.id

    def control(self, owner, mode, broker, action):
        if action != "arm":
            return self._control(owner, mode, broker, action)
        if not self.maintenance.acquire(blocking=False):
            raise CopierError("Preflight or reconciliation is already running")
        try:
            return self._control(owner, mode, broker, action)
        finally:
            self.maintenance.release()

    def _control(self, owner, mode, broker, action):
        key = self.scope(owner, mode, broker)
        if action not in ("arm", "disarm", "kill"):
            raise CopierError("Invalid control action")
        if action == "arm":
            if not self.context(owner, mode, broker):
                raise CopierError("Master session or mode changed")
            # Baseline is deliberately collected with trading disabled.
            self.control(owner, mode, broker, "disarm")
            with self.sessions() as s:
                generation = s.get(m.Control, key).generation
            baseline, identity = self.source(owner, mode, broker)
            with self.sessions() as s:
                accounts = s.scalars(
                    select(m.Account).where(
                        m.Account.owner == owner,
                        m.Account.mode == mode,
                        m.Account.enabled.is_(True),
                    )
                ).all()
                uncertain = s.scalar(
                    select(m.Attempt.id)
                    .where(
                        m.Attempt.owner == owner,
                        m.Attempt.mode == mode,
                        m.Attempt.status == "UNKNOWN",
                    )
                    .limit(1)
                )
            if uncertain:
                raise CopierError(
                    "Resolve UNKNOWN attempts before arming; no automatic retry is allowed"
                )
            if not accounts:
                raise CopierError("Add and enable at least one child account")
            futures = [
                self.pool.submit(self.refresh_account, a, identity, broker) for a in accounts
            ]
            checked = [f.result() for f in futures]
            if not all(checked):
                raise CopierError("Child preflight failed. Check account health and credentials")
            with self.lock, self.sessions.begin() as s:
                c = s.get(m.Control, key)
                if c.generation != generation or not self.context(owner, mode, broker):
                    raise CopierError(
                        "Configuration or control changed during preflight; review and arm again"
                    )
                identities = [
                    a.verified_identity
                    for a in s.scalars(
                        select(m.Account).where(
                            m.Account.owner == owner,
                            m.Account.mode == mode,
                            m.Account.enabled.is_(True),
                        )
                    )
                ]
                if len(set(identities)) != len(identities):
                    raise CopierError("Two children connect to the same broker account")
                c.identity = packed(identity)
                for raw in baseline:
                    o = order(raw)
                    state_key = digest(key, c.identity, today(), o["orderid"])
                    row = s.get(m.MasterState, state_key)
                    if not row:
                        s.add(
                            m.MasterState(
                                key=state_key,
                                scope=key,
                                orderid=o["orderid"],
                                payload=packed(o),
                                baseline=True,
                            )
                        )
                    else:
                        row.payload, row.baseline = packed(o), True
                c.armed, c.killed, c.day, c.note, c.heartbeat = (
                    True,
                    False,
                    today(),
                    "Armed; following new master orders",
                    time.time(),
                )
                self.audit(s, owner, mode, "ARM", "Preflight passed; existing orders baselined")
            return
        with self.lock, self.sessions.begin() as s:
            c = s.get(m.Control, key)
            if not c:
                c = m.Control(key=key, owner=owner, mode=mode, broker=broker)
                s.add(c)
            # Kill is owner-wide, including the currently hidden mode/broker.
            controls = (
                s.scalars(select(m.Control).where(m.Control.owner == owner)).all()
                if action == "kill"
                else [c]
            )
            for row in controls:
                row.generation = (row.generation or 0) + 1
                row.armed = False
                row.killed = action == "kill" or bool(row.killed)
                row.note = (
                    "Kill switch engaged; in-flight broker requests may complete"
                    if action == "kill"
                    else "Disarmed"
                )
            self.audit(s, owner, mode, action.upper(), c.note)

    def refresh_account(self, a, master_identity="", master_broker=""):
        try:
            adapter = self.transport(a)
            identity = adapter.verify()
            if a.mode == "live" and a.broker == master_broker and identity in master_identity:
                raise BrokerFailure("DISABLED", "Master account cannot also be a child")
            if isinstance(adapter, Native):
                for symbol in json.loads(a.config)["symbols"]:
                    exchange, name = symbol.split(":", 1)
                    adapter.instrument({"exchange": exchange, "symbol": name})
            risk = adapter.risk()
            number(risk["pnl"], "P&L", -1e12)
            number(risk["quantity"], "position quantity", 0, 1e10, True)
            with self.lock, self.sessions.begin() as s:
                current = s.get(m.Account, a.id)
                current.health, current.verified_until = "READY", time.time() + 30
                current.verified_identity = a.broker + ":" + identity
                self.risk_cache[a.id] = (time.time(), risk)
            return True
        except Exception as exc:
            with self.lock, self.sessions.begin() as s:
                current = s.get(m.Account, a.id)
                current.health = exc.state if isinstance(exc, BrokerFailure) else "DEGRADED"
                current.verified_until = 0
                self.audit(s, a.owner, a.mode, "PREFLIGHT_FAILED", a.id + ": " + current.health)
            return False

    def ingest(self, owner, mode, broker, raw, authoritative=False):
        received = time.monotonic()
        o = order(raw)
        key = self.scope(owner, mode, broker)
        work = []
        with self.sessions() as precheck:
            control = precheck.get(m.Control, key)
            if not control or not control.armed or control.killed or self.stop.is_set():
                return []
        meta = None
        meta_error = "Instrument mapping unavailable"
        try:
            meta = self.instrument(o, broker, owner)
        except Exception:
            pass
        with self.lock, self.sessions.begin() as s:
            c = s.get(m.Control, key)
            if self.stop.is_set() or not c or not c.armed or c.killed:
                return []
            if (
                c.day != today()
                or not self.context(owner, mode, broker, c.identity)
                or time.time() - c.heartbeat > 15
            ):
                c.armed, c.note = (
                    False,
                    "Master session, mode or heartbeat changed; re-arm required",
                )
                return []
            state_key = digest(key, c.identity, today(), o["orderid"])
            old = s.get(m.MasterState, state_key)
            previous = json.loads(old.payload) if old else None
            if old and (
                old.baseline
                or previous["order_status"] in ("complete", "cancelled", "rejected", "expired")
                or o["filled_quantity"] < previous["filled_quantity"]
            ):
                return []
            if previous == o:
                return []
            revision = old.revision + 1 if old else 0
            event_id = digest(state_key, revision, o, authoritative)
            if s.get(m.EventRecord, event_id):
                return []
            s.add(
                m.EventRecord(
                    id=event_id,
                    scope=key,
                    orderid=o["orderid"],
                    received=time.time(),
                    payload=packed(o),
                )
            )
            if old:
                saved = dict(o)
                if not authoritative:
                    for field in ("price", "trigger_price", "pricetype", "quantity"):
                        saved[field] = previous[field]
                old.payload = packed(saved)
                old.revision = revision
            else:
                s.add(
                    m.MasterState(
                        key=state_key,
                        scope=key,
                        orderid=o["orderid"],
                        payload=packed(o),
                        baseline=False,
                    )
                )
            children = s.scalars(
                select(m.Account).where(
                    m.Account.owner == owner, m.Account.mode == mode, m.Account.enabled.is_(True)
                )
            ).all()
            for a in children:
                p = json.loads(a.config)
                instrument_key = f"{o['exchange']}:{o['symbol']}"
                if instrument_key not in p["symbols"]:
                    continue
                fast = p["copy_mode"] == "fast" or (
                    p["copy_mode"] == "hybrid"
                    and o["pricetype"] == "MARKET"
                    and instrument_key in p["fast_symbols"]
                )
                cursor_key = digest(state_key, a.id)
                cursor = s.get(m.Cursor, cursor_key)
                if not cursor:
                    cursor = m.Cursor(key=cursor_key, target=0)
                    s.add(cursor)
                placements = s.scalars(
                    select(m.Attempt).where(
                        m.Attempt.account_id == a.id,
                        m.Attempt.day == today(),
                        m.Attempt.master_key == state_key,
                        m.Attempt.action == "PLACE",
                    )
                ).all()
                if o["order_status"] in ("cancelled", "expired", "rejected"):
                    for placed in placements:
                        if placed.status not in TERMINAL:
                            # Even an in-flight PLACE gets a durable dependent cancel.
                            job = self._intent(
                                s,
                                a,
                                event_id,
                                o,
                                "CANCEL",
                                json.loads(placed.payload),
                                0,
                                placed.id,
                            )
                            work.append((job.id, key, received))
                    if o["order_status"] == "rejected" and placements:
                        self.audit(
                            s,
                            owner,
                            mode,
                            "MASTER_REJECTED",
                            "Master "
                            + o["orderid"]
                            + " rejected after copying; review child exposure",
                        )
                    if fast or o["filled_quantity"] <= (
                        previous["filled_quantity"] if previous else 0
                    ):
                        continue
                try:
                    if meta is None:
                        raise CopierError(meta_error)
                    lot = int(number(meta["lot"], "lot size", 1, 1000000, True))
                    target = (
                        int(
                            Decimal(o["quantity"] if fast else o["filled_quantity"])
                            * Decimal(str(p["multiplier"]))
                            / Decimal(lot)
                        )
                        * lot
                    )
                    qty = target - cursor.target
                    if fast and placements:
                        # Only current orderbook snapshots drive modifications; WS delivery can reorder.
                        if (
                            authoritative
                            and previous
                            and any(
                                o[x] != previous[x]
                                for x in ("quantity", "price", "trigger_price", "pricetype")
                            )
                        ):
                            for placed in placements:
                                if placed.status in ("ACKNOWLEDGED", "OPEN", "TRIGGER PENDING"):
                                    updated = dict(
                                        o, quantity=target, filled_quantity=0, order_status="open"
                                    )
                                    self._risk(s, a, p, updated, meta)
                                    job = self._intent(
                                        s, a, event_id, o, "MODIFY", updated, 0, placed.id
                                    )
                                    work.append((job.id, key, received))
                        continue
                    if qty <= 0:
                        continue
                    cursor.target = target  # Never implicitly retry a rejected/blocked delta.
                    payload = dict(o, quantity=qty, filled_quantity=0, order_status="open")
                    if not fast:
                        payload.update(pricetype="MARKET", price=0, trigger_price=0)
                    notional = self._risk(s, a, p, payload, meta)
                    job = self._intent(s, a, event_id, o, "PLACE", payload, notional)
                    work.append((job.id, key, received))
                except (CopierError, KeyError, ValueError) as exc:
                    self._intent(
                        s,
                        a,
                        event_id,
                        o,
                        "PLACE",
                        o,
                        0,
                        blocked=str(exc)
                        if isinstance(exc, CopierError)
                        else "Instrument mapping unavailable",
                    )
        for job in work:
            if self.pending.acquire(blocking=False):
                self.pool.submit(self._execute, *job)
            else:
                with self.sessions.begin() as s:
                    a = s.get(m.Attempt, job[0])
                    a.status, a.message = "BLOCKED", "Copier queue capacity reached"
        return [j[0] for j in work]

    def _risk(self, s, a, p, o, meta):
        if a.health != "READY" or a.verified_until < time.time():
            raise CopierError("Child session not READY; run preflight")
        snapshot = self.risk_cache.get(a.id)
        if not snapshot or time.time() - snapshot[0] > 30:
            raise CopierError("Child risk snapshot is stale")
        if snapshot[1]["pnl"] <= -p["max_daily_loss"]:
            raise CopierError("Child daily loss limit reached")
        qty = o["quantity"]
        if qty <= 0 or qty > p["max_quantity"]:
            raise CopierError("Child order quantity limit reached")
        price = max(o["price"], o["trigger_price"], o["average_price"], float(meta.get("price", 0)))
        if not price > 0:
            raise CopierError("A current reference price is required for the notional check")
        value = qty * price * 1.05  # Risk buffer for market slippage, not a guaranteed fill price.
        if value > p["max_order_value"]:
            raise CopierError("Child order value limit reached")
        used = s.scalar(
            select(func.coalesce(func.sum(m.Attempt.notional), 0)).where(
                m.Attempt.account_id == a.id,
                m.Attempt.day == today(),
                m.Attempt.action == "PLACE",
                m.Attempt.status.notin_(["BLOCKED", "REJECTED"]),
            )
        )
        if used + value > p["max_daily_value"]:
            raise CopierError("Child daily value limit reached")
        # Conservative: count current exposure plus all unresolved/copied quantities.
        pending = s.scalars(
            select(m.Attempt).where(
                m.Attempt.account_id == a.id,
                m.Attempt.day == today(),
                m.Attempt.action == "PLACE",
                m.Attempt.status.notin_(TERMINAL),
            )
        ).all()
        reserved = sum(json.loads(x.payload)["quantity"] for x in pending)
        if snapshot[1]["quantity"] + reserved + qty > p["max_position_quantity"]:
            raise CopierError("Child position quantity limit reached")
        return value

    def _intent(self, s, a, event_id, master, action, payload, notional, parent="", blocked=""):
        ident = digest(event_id, a.id, action, parent)
        job = m.Attempt(
            id=ident,
            owner=a.owner,
            mode=a.mode,
            account_id=a.id,
            event_id=event_id,
            generation=s.get(m.Control, s.get(m.EventRecord, event_id).scope).generation,
            master_orderid=master["orderid"],
            master_key=digest(
                s.get(m.EventRecord, event_id).scope,
                s.get(m.Control, s.get(m.EventRecord, event_id).scope).identity,
                today(),
                master["orderid"],
            ),
            day=today(),
            action=action,
            payload=packed(dict(payload, _parent=parent)),
            status="BLOCKED" if blocked else "QUEUED",
            message=blocked,
            created=time.time(),
            notional=notional,
        )
        s.add(job)
        return job

    def _execute(self, ident, scope, received):
        # Serialize mutations within a child while different children run concurrently.
        with self.sessions() as s:
            account_id = s.get(m.Attempt, ident).account_id
        with self.lock:
            mutex = self.account_locks.setdefault(account_id, threading.Lock())
        try:
            with mutex:
                self._dispatch(ident, scope, received)
        finally:
            self.pending.release()

    def _dispatch(self, ident, scope, received):
        try:
            with self.lock, self.sessions.begin() as s:
                job = s.get(m.Attempt, ident)
                if job.status != "QUEUED":
                    return
                c = s.get(m.Control, scope)
                a = s.get(m.Account, job.account_id)
                if (
                    self.stop.is_set()
                    or not c.armed
                    or c.killed
                    or job.generation != c.generation
                    or c.day != today()
                    or not self.context(a.owner, a.mode, c.broker, c.identity)
                    or not a.enabled
                ):
                    job.status, job.message = "BLOCKED", "Copying disarmed before submission"
                    return
                if a.health != "READY" or a.verified_until < time.time():
                    job.status, job.message = "BLOCKED", "Child not ready at dispatch"
                    return
                payload = json.loads(job.payload)
                parent = (
                    s.get(m.Attempt, payload.pop("_parent", "")) if job.action != "PLACE" else None
                )
                if job.action != "PLACE":
                    if not parent or not parent.broker_orderid:
                        job.status, job.message = (
                            "QUEUED",
                            "Waiting for parent acknowledgement; no mutation submitted",
                        )
                        return
                    if parent.status in TERMINAL:
                        job.status, job.message = (
                            "BLOCKED",
                            "Child already terminal; review any remaining exposure",
                        )
                        return
                recent = s.scalar(
                    select(func.count())
                    .select_from(m.Attempt)
                    .where(m.Attempt.account_id == a.id, m.Attempt.submitted > time.time() - 1)
                )
                minute = s.scalar(
                    select(func.count())
                    .select_from(m.Attempt)
                    .where(m.Attempt.account_id == a.id, m.Attempt.submitted > time.time() - 60)
                )
                if recent >= 5 or minute >= 120:
                    job.status, job.message = (
                        "BLOCKED",
                        "Per-child request limit reached (5/second, 120/minute)",
                    )
                    a.health, a.verified_until = "RATE_LIMITED", 0
                    return
                job.status, job.submitted = "SUBMITTING", time.time()
                job.dispatch_ms = (time.monotonic() - received) * 1000
                oid = parent.broker_orderid if parent else ""
            started = time.monotonic()
            try:
                result = self.transport(a).execute(job.action, payload, "cp" + ident[:18], oid)
            except Exception as exc:
                result = {
                    "status": "REJECTED"
                    if isinstance(exc, BrokerFailure)
                    and exc.state in ("REJECTED", "AUTH_REQUIRED", "RATE_LIMITED")
                    else "UNKNOWN",
                    "orderid": "",
                    "message": str(exc)
                    if isinstance(exc, CopierError)
                    else "Submission outcome unknown; no retry sent",
                }
            with self.lock, self.sessions.begin() as s:
                row = s.get(m.Attempt, ident)
                row.status, row.broker_orderid, row.message = (
                    result["status"],
                    result.get("orderid", ""),
                    result.get("message", ""),
                )
                row.completed, row.response_ms = time.time(), (time.monotonic() - started) * 1000
                if row.status in ("REJECTED", "UNKNOWN"):
                    child = s.get(m.Account, a.id)
                    child.health = "DEGRADED"
                    child.verified_until = 0
                    self.audit(s, a.owner, a.mode, "CHILD_PAUSED", a.id + ": " + row.status)
        except Exception:
            # A DB failure must not leave new work executing without durable state.
            self.stop.set()
            raise

    def reconcile(self, owner, mode, broker):
        if not self.maintenance.acquire(blocking=False):
            return
        try:
            return self._reconcile(owner, mode, broker)
        finally:
            self.maintenance.release()

    def _reconcile(self, owner, mode, broker):
        key = self.scope(owner, mode, broker)
        baseline, identity = self.source(owner, mode, broker)
        with self.lock, self.sessions.begin() as s:
            c = s.get(m.Control, key)
            if c:
                c.heartbeat = time.time()
            accounts = s.scalars(
                select(m.Account).where(
                    m.Account.owner == owner, m.Account.mode == mode, m.Account.enabled.is_(True)
                )
            ).all()
        futures = [self.pool.submit(self._reconcile_child, a, identity, broker) for a in accounts]
        for f in futures:
            f.result()
        with self.sessions() as s:
            waiting = s.scalars(
                select(m.Attempt).where(
                    m.Attempt.owner == owner,
                    m.Attempt.mode == mode,
                    m.Attempt.status == "QUEUED",
                    m.Attempt.action != "PLACE",
                )
            ).all()
        for job in waiting:
            if self.pending.acquire(blocking=False):
                self.pool.submit(self._execute, job.id, key, time.monotonic())
        for raw in baseline:
            self.ingest(owner, mode, broker, raw, authoritative=True)

    def _reconcile_child(self, a, identity, broker):
        try:
            rows = self.transport(a).orders()
            with self.lock, self.sessions.begin() as s:
                attempts = s.scalars(
                    select(m.Attempt).where(
                        m.Attempt.account_id == a.id,
                        m.Attempt.day == today(),
                        m.Attempt.action == "PLACE",
                        m.Attempt.status.notin_(TERMINAL),
                    )
                ).all()
                for job in attempts:
                    matches = [
                        r
                        for r in rows
                        if (job.broker_orderid and r["orderid"] == job.broker_orderid)
                        or r.get("tag") == "cp" + job.id[:18]
                    ]
                    if len(matches) == 1:
                        r = matches[0]
                        job.broker_orderid = r["orderid"]
                        job.status = r["status"].upper()
                        job.filled = int(r.get("filled", 0))
                        job.average_price = float(r.get("average_price", 0))
                        job.message = "Reconciled with child orderbook"
                uncertain = s.scalar(
                    select(m.Attempt.id)
                    .where(m.Attempt.account_id == a.id, m.Attempt.status == "UNKNOWN")
                    .limit(1)
                )
            # Unresolved mutations pause the child, including after periodic refresh.
            with self.sessions() as s:
                health = s.get(m.Account, a.id).health
            if not uncertain and health == "READY":
                self.refresh_account(a, identity, broker)
        except Exception:
            with self.lock, self.sessions.begin() as s:
                child = s.get(m.Account, a.id)
                child.health = "DEGRADED"
                child.verified_until = 0

    def snapshot(self, owner, mode, broker):
        with self.sessions() as s:
            c = s.get(m.Control, self.scope(owner, mode, broker))
            accounts = s.scalars(
                select(m.Account).where(m.Account.owner == owner, m.Account.mode == mode)
            ).all()
            attempts = s.scalars(
                select(m.Attempt)
                .where(m.Attempt.owner == owner, m.Attempt.mode == mode)
                .order_by(m.Attempt.created.desc())
                .limit(250)
            ).all()
            audits = s.scalars(
                select(m.Audit)
                .where(m.Audit.owner == owner, m.Audit.mode == mode)
                .order_by(m.Audit.id.desc())
                .limit(100)
            ).all()

            def costs(attempt):
                if attempt.action != "PLACE" or not attempt.filled or not attempt.average_price:
                    return None
                from services.report_brokerage import instrument, order_cost, tariff

                account = next((a for a in accounts if a.id == attempt.account_id), None)
                try:
                    payload = json.loads(attempt.payload)
                    exchange, segment = instrument(payload, {})
                    rates = tariff(account.broker if account else "")
                    if not rates:
                        return None
                    return order_cost(
                        attempt.filled * attempt.average_price,
                        payload["action"],
                        exchange,
                        segment,
                        attempt.day,
                        rates,
                    )
                except (ValueError, KeyError, TypeError):
                    return None

            latency = sorted(a.dispatch_ms for a in attempts if a.dispatch_ms is not None)

            def percentile(p):
                return (
                    round(latency[min(len(latency) - 1, int((len(latency) - 1) * p))], 2)
                    if latency
                    else None
                )

            return {
                "mode": mode,
                "broker": broker,
                "armed": bool(c and c.armed),
                "killed": bool(c and c.killed),
                "note": c.note if c else "Add child accounts, run preflight and arm to begin",
                "heartbeat": c.heartbeat if c else 0,
                "accounts": [
                    dict(
                        id=a.id,
                        name=a.name,
                        broker=a.broker,
                        client_id=a.client_id,
                        enabled=a.enabled,
                        health=a.health,
                        verified_until=a.verified_until,
                        **json.loads(a.config),
                    )
                    for a in accounts
                ],
                "attempts": [
                    {
                        "id": a.id,
                        "account_id": a.account_id,
                        "master_orderid": a.master_orderid,
                        "action": a.action,
                        "status": a.status,
                        "order": json.loads(a.payload),
                        "broker_orderid": a.broker_orderid,
                        "message": a.message,
                        "created": a.created,
                        "filled": a.filled,
                        "average_price": a.average_price,
                        "dispatch_ms": a.dispatch_ms,
                        "response_ms": a.response_ms,
                        "estimated_charges": costs(a),
                    }
                    for a in attempts
                ],
                "audit": [
                    {"action": a.action, "detail": a.detail, "created": a.created} for a in audits
                ],
                "latency": {
                    "p50": percentile(0.5),
                    "p95": percentile(0.95),
                    "p99": percentile(0.99),
                    "samples": len(latency),
                },
            }

    def start(self, bus):
        if self.thread:
            return
        self.bus = bus
        bus.subscribe("order.update", self.on_event, "trade-copier")
        self.thread = threading.Thread(target=self._monitor, daemon=True, name="copier-reconcile")
        self.thread.start()

    def on_event(self, event):
        owner = event.request_data.get("user_id")
        if not owner:
            return
        mode = "paper" if event.mode == "analyze" else "live"
        with self.sessions() as s:
            controls = s.scalars(
                select(m.Control).where(
                    m.Control.owner == owner, m.Control.mode == mode, m.Control.armed.is_(True)
                )
            ).all()
        for c in controls:
            if mode == "live" and event.broker != c.broker:
                continue
            try:
                self.ingest(owner, mode, c.broker, asdict(event))
            except Exception:
                self.control(owner, mode, c.broker, "disarm")

    def _monitor(self):
        while not self.stop.wait(5):
            with self.sessions() as s:
                controls = s.scalars(select(m.Control).where(m.Control.armed.is_(True))).all()
            for c in controls:
                try:
                    if not self.context(c.owner, c.mode, c.broker, c.identity):
                        raise CopierError("Master session changed")
                    self.reconcile(c.owner, c.mode, c.broker)
                except Exception:
                    self.control(c.owner, c.mode, c.broker, "disarm")

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.bus:
            self.bus.unsubscribe("order.update", self.on_event)
        with self.lock, self.sessions.begin() as s:
            s.execute(update(m.Control).values(armed=False, note="Copier stopped"))
        if self.thread:
            self.thread.join(timeout=15)
        self.pool.shutdown(wait=True, cancel_futures=False)
        self.db.dispose()
