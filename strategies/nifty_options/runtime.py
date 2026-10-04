"""Scheduled, direct-Sandbox runner. State survives application/process restarts."""

import argparse
import hashlib
import math
import os
import queue
import signal
import time
from datetime import date, datetime

from strategies.top_gain_volumes.coordination import dispatch_lock

from .engine import IST, decision, initial_state, opening_plan, risk_decision, validate_state
from .execution import SandboxExecutor, cleanup_sessions
from .greeks import chain_options, session_close
from .profiles import PROFILES, ROOT, Policy
from .selection import DataUnavailable, select_legs
from .state import Store


def instruments(day, held_expiry=None):
    from database.symbol import SymToken, db_session

    rows = []
    try:
        for item in (
            db_session.query(SymToken)
            .filter(SymToken.exchange == "NFO", SymToken.name == "NIFTY")
            .all()
        ):
            if item.instrumenttype not in {"CE", "PE"}:
                continue
            expiry = datetime.strptime(item.expiry, "%d-%b-%y").date()
            if expiry < day:
                continue
            rows.append(
                {
                    "symbol": item.symbol,
                    "broker_symbol": item.brsymbol,
                    "expiry": str(expiry),
                    "strike": float(item.strike),
                    "kind": item.instrumenttype,
                    "lot_size": int(item.lotsize),
                }
            )
    finally:
        db_session.remove()
    expiries = sorted({r["expiry"] for r in rows})
    allowed = set(expiries[:2]) | ({held_expiry} if held_expiry else set())
    return [r for r in rows if r["expiry"] in allowed], [date.fromisoformat(e) for e in expiries]


def broker_margin(owner, selected, profile, lots=1):
    """Read-only broker basket margin, never an order API call."""
    from broker.fyers.api.rate_limiter import apply_rate_limit
    from broker.fyers.mapping.margin_data import transform_margin_positions
    from services.market_scanner_provider import credentials
    from utils.httpx_client import get_httpx_client

    try:
        token, _ = credentials(owner, "fyers")
        legs = [
            {
                "symbol": o.symbol,
                "exchange": "NFO",
                "action": "BUY" if side > 0 else "SELL",
                "quantity": o.lot_size * lots,
                "product": "NRML",
                "pricetype": "MARKET",
                "price": 0.0,
            }
            for o, side in selected
        ]
        payload = transform_margin_positions(legs)
        if len(payload) != len(legs):
            raise DataUnavailable("Broker master rejected a basket leg")
        # Serialize twelve processes' relatively infrequent margin queries.
        with dispatch_lock(ROOT / "db/nifty_options/margin.lock", timeout=20):
            # Per-process provider limiters cannot pace twelve independent
            # runners. Hold the shared lock during a short spacing interval.
            time.sleep(0.35)
            apply_rate_limit()
            response = get_httpx_client().post(
                "https://api-t1.fyers.in/api/v3/multiorder/margin",
                headers={"Authorization": os.environ["BROKER_API_KEY"] + ":" + token},
                json={"data": payload},
                timeout=30,
            )
            if response.status_code != 200:
                raise DataUnavailable(f"Broker margin HTTP {response.status_code}")
            body = response.json()
            if body.get("s") != "ok":
                raise DataUnavailable("Broker margin request failed")
            # Conservatively retain the larger returned requirement, including
            # existing account positions when the broker includes those.
            values = [
                float(body.get("data", {}).get(k) or 0)
                for k in ("margin_total", "margin_new_order")
            ]
            margin = max(values)
            if not math.isfinite(margin) or margin <= 0:
                raise DataUnavailable("Broker returned no positive basket margin")
            return margin
    finally:
        cleanup_sessions()


def run(profile_name, policy_path):
    from dotenv import load_dotenv

    from database.auth_db import db_session, verify_api_key
    from services.websocket_client import WebSocketClient

    load_dotenv(ROOT / ".env")
    profile, policy = PROFILES[profile_name], Policy.load(policy_path)
    key = os.environ.get("OPENALGO_API_KEY")
    try:
        owner = verify_api_key(key) if key else None
    finally:
        db_session.remove()
    if not owner:
        raise RuntimeError("An authenticated scheduler OpenAlgo API key is required")
    store = Store(ROOT / "db/nifty_options/state.sqlite3")
    revision, state = store.load(owner, profile_name)
    state = state or initial_state(profile, policy)
    validate_state(state, profile, policy)

    def persist(kind, event):
        nonlocal revision
        revision = store.save(owner, profile_name, revision, state, [(kind, event)])

    suffix = hashlib.sha256((owner + profile_name).encode()).hexdigest()[:20]
    with dispatch_lock(ROOT / f"db/nifty_options/runner-{suffix}.lock", timeout=1):
        today = datetime.now(IST).date()
        contracts, expiries = instruments(today, state["expiry"])
        if state["legs"] and not {leg["symbol"] for leg in state["legs"]} <= {
            c["symbol"] for c in contracts
        }:
            raise RuntimeError(
                "Held contract absent from live master; reconcile expiry before resuming"
            )
        messages = queue.Queue(maxsize=10000)
        stopped, overflow = [False], [False]

        def receive(message):
            try:
                messages.put_nowait(message)
            except queue.Full:
                overflow[0] = True

        def stop(*_):
            stopped[0] = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        client = WebSocketClient(
            key,
            host=os.getenv("WEBSOCKET_HOST", "localhost"),
            port=int(os.getenv("WEBSOCKET_PORT", "8765")),
        )
        client.register_callback("market_data", receive)
        executor = SandboxExecutor(owner, profile, state, persist)
        quotes, subscribed_socket = {}, None
        last_eval = last_save = last_error = 0.0
        specs = [{"symbol": c["symbol"], "exchange": "NFO"} for c in contracts]
        specs.append({"symbol": "NIFTY", "exchange": "NSE_INDEX"})
        allowed = {s["symbol"] for s in specs}
        try:
            while not stopped[0]:
                now = datetime.now(IST)
                if now.date() != today or now.time() >= session_close(today):
                    break
                if not client.connected:
                    quotes.clear()
                    if not client.thread or not client.thread.is_alive():
                        client.disconnect()
                        client.connect()
                    time.sleep(0.5)
                    continue
                if client.authenticated and subscribed_socket is not client.ws:
                    quotes.clear()
                    for offset in range(0, len(specs), 50):
                        reply = client.subscribe(specs[offset : offset + 50], "Quote")
                        if reply.get("status") != "success":
                            raise DataUnavailable("Option subscription failed")
                    subscribed_socket = client.ws
                try:
                    message = messages.get(timeout=0.1)
                except queue.Empty:
                    message = None
                if overflow[0]:
                    quotes.clear()
                    overflow[0] = False
                    while not messages.empty():
                        messages.get_nowait()
                if message and message.get("symbol") in allowed:
                    q = message.get("data", {})
                    try:
                        stamp, price = float(q["timestamp"]), float(q["ltp"])
                        stamp = stamp / 1000 if stamp > 1e12 else stamp
                        traded = float(
                            q.get("last_traded_time") or q.get("last_trade_time") or stamp
                        )
                        traded = traded / 1000 if traded > 1e12 else traded
                        if (
                            all(math.isfinite(v) for v in (stamp, price, traded))
                            and price > 0
                            and 0 <= now.timestamp() - min(stamp, traded) <= 15
                        ):
                            quotes[message["symbol"]] = (min(stamp, traded), q)
                    except (KeyError, TypeError, ValueError):
                        pass
                if time.monotonic() - last_eval < 0.5:
                    continue
                last_eval = time.monotonic()
                fresh = {s: q for s, (ts, q) in quotes.items() if 0 <= now.timestamp() - ts <= 15}
                try:
                    if state["pending"]:
                        executor.advance(fresh, now)
                        continue
                    action = risk_decision(
                        profile, policy, state, {s: float(q["ltp"]) for s, q in fresh.items()}, now
                    )
                    if action:
                        legs = [
                            leg
                            for leg in state["legs"]
                            if action["action"] == "close_all" or leg["symbol"] in action["symbols"]
                        ]
                        executor.begin(action, legs, now)
                        continue
                    if "NIFTY" not in fresh:
                        continue
                    prices = {s: float(q["ltp"]) for s, q in fresh.items()}
                    options = chain_options(
                        contracts,
                        prices,
                        prices["NIFTY"],
                        now,
                        {c["symbol"]: c["lot_size"] for c in contracts},
                    )
                    action = decision(profile, policy, state, options, now, expiries)
                    if action["action"] == "open":
                        expiry = date.fromisoformat(action["expiry"])
                        selected = select_legs(profile, policy, options, expiry)
                        margin = broker_margin(owner, selected, profile)
                        legs = opening_plan(profile, policy, options, expiry, margin / 0.90)
                        lots = legs[0]["quantity"] // legs[0]["lot_size"]
                        full_margin = broker_margin(owner, selected, profile, lots)
                        if full_margin > profile.capital * 0.90:
                            raise DataUnavailable("Full basket margin exceeds strategy allocation")
                        dispatch_time = datetime.now(IST)
                        deadline = "09:31" if action["new_cycle"] else policy.reentry_cutoff
                        if (
                            dispatch_time.date() != now.date()
                            or dispatch_time.strftime("%H:%M") >= deadline
                        ):
                            raise DataUnavailable(
                                "Margin verification finished after the entry deadline"
                            )
                        executor.begin(action, legs, dispatch_time)
                    elif action["action"] in {"close_all", "close_legs"}:
                        legs = [
                            leg
                            for leg in state["legs"]
                            if action["action"] == "close_all" or leg["symbol"] in action["symbols"]
                        ]
                        executor.begin(action, legs, now)
                    elif action["action"] == "latch":
                        state.update(halted=True, needs_reentry=False)
                        persist("loss_latched", action)
                    state["last_timestamp"] = now.isoformat()
                    if time.monotonic() - last_save >= 10:
                        persist("heartbeat", {"open_legs": len(state["legs"])})
                        last_save = time.monotonic()
                except DataUnavailable as exc:
                    if time.monotonic() - last_error >= 60:
                        persist("data_unavailable", {"message": str(exc)})
                        print(str(exc), flush=True)
                        last_error = time.monotonic()
        finally:
            client.unregister_callback("market_data", receive)
            client.disconnect()
            cleanup_sessions()
            persist(
                "runner_stopped",
                {"open_legs": len(state["legs"]), "pending": bool(state["pending"])},
            )


def main(profile_name):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=str(ROOT / "strategies/nifty_options/policy.json"))
    parser.add_argument(
        "--check", action="store_true", help="Validate local rules without data access or orders"
    )
    args = parser.parse_args()
    if args.check:
        Policy.load(args.policy)
        print(profile_name + ": configuration valid; Sandbox only")
        return
    run(profile_name, args.policy)
