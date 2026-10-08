"""Scheduled, direct-Sandbox runner. State survives application/process restarts."""

import argparse
import hashlib
import math
import os
import queue
import signal
import time
from contextlib import ExitStack
from datetime import date, datetime

from strategies.top_gain_volumes.coordination import dispatch_lock

from .engine import IST, decision, initial_state, opening_plan, risk_decision, validate_state
from .execution import SandboxExecutor, cleanup_sessions
from .feed import QuoteSubscriptions, connection_delay, required_contracts
from .greeks import chain_options, session_close
from .hedges import missing_hedges
from .profiles import PROFILES, ROOT, Policy
from .selection import DataUnavailable, select_legs
from .state import Store


def shutdown_run(client, receive, persist, finish_report, report):
    """Persist carried risk and final report even if transport cleanup fails."""
    from utils.httpx_client import cleanup_httpx_client

    with ExitStack() as cleanup:
        cleanup.callback(cleanup_httpx_client)
        cleanup.callback(report.close)
        cleanup.callback(finish_report)
        cleanup.callback(persist)
        cleanup.callback(cleanup_sessions)
        cleanup.callback(client.disconnect)
        cleanup.callback(client.unregister_callback, "market_data", receive)


def publish_report(report, state, status, now, feed):
    """Report storage must not interrupt management of an existing basket."""
    try:
        return report.save(state, status, now, feed)
    except Exception as exc:
        print(f"Daily report update failed ({type(exc).__name__}); will retry", flush=True)
        return None


def recover_hedges(executor, contracts, fresh, now):
    """Called after clock/price exits and before entries or delta adjustments."""
    hedges = missing_hedges(executor.profile, executor.state["legs"], contracts)
    if not hedges:
        return False
    if not all(leg["symbol"] in fresh for leg in hedges):
        raise DataUnavailable("Waiting for fresh quotes to protect carried shorts")
    executor.begin(
        {
            "action": "add_hedges",
            "reason": "protect_carried_shorts",
            "expiry": executor.state["expiry"],
        },
        hedges,
        now,
    )
    return True


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


def broker_margin(owner, selected, profile, lots=1, *, details=False):
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
            if not isinstance(body, dict) or body.get("s") != "ok":
                raise DataUnavailable("Broker margin request failed")
            # Conservatively retain the larger returned requirement, including
            # existing account positions when the broker includes those.
            data = body.get("data", {})
            values = [float(data[k]) for k in ("margin_total", "margin_new_order")]
            if any(not math.isfinite(v) or v < 0 for v in values):
                raise DataUnavailable("Broker returned invalid basket margin")
            margin = max(values)
            if not math.isfinite(margin) or margin <= 0:
                raise DataUnavailable("Broker returned no positive basket margin")
            if details:
                return {
                    "broker": "fyers",
                    "quoted_at": datetime.now(IST).isoformat(),
                    "margin_total": values[0],
                    "margin_new_order": values[1],
                    "sizing_requirement": margin,
                    "legs": legs,
                }
            return margin
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DataUnavailable):
            raise
        raise DataUnavailable("Broker margin response is incomplete or invalid") from None
    finally:
        cleanup_sessions()


def prepare_opening(owner, profile, policy, options, expiry):
    """Verify complete one-lot/full baskets before any execution intent exists."""
    selected = select_legs(profile, policy, options, expiry)
    one_lot = broker_margin(owner, selected, profile, details=True)
    legs = opening_plan(profile, policy, options, expiry, one_lot["sizing_requirement"] / 0.90)
    lots = legs[0]["quantity"] // legs[0]["lot_size"]
    full_margin = broker_margin(owner, selected, profile, lots, details=True)
    if full_margin["sizing_requirement"] > profile.capital * 0.90:
        raise DataUnavailable("Full basket margin exceeds strategy allocation")
    return legs, {
        "allocation": profile.capital,
        "deployable_budget": profile.capital * 0.90,
        "lots_per_leg": lots,
        "one_lot": one_lot,
        "basket": full_margin,
        "utilization_pct": full_margin["sizing_requirement"] / profile.capital * 100,
    }


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
        active_expiry = state["expiry"] if state["legs"] or state["needs_reentry"] else None
        if state["pending"]:
            active_expiry = state["pending"]["action"].get("expiry") or state["expiry"]
        contracts, expiries = instruments(today, active_expiry)
        contracts = required_contracts(
            contracts, expiries, profile, today, state["legs"], active_expiry
        )
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
        quotes = {}
        last_eval = last_save = last_error = 0.0
        # Subscribe held risk first, then the index and this profile's expiry chain.
        specs = [{"symbol": leg["symbol"], "exchange": "NFO"} for leg in state["legs"]]
        specs.append({"symbol": "NIFTY", "exchange": "NSE_INDEX"})
        specs.extend({"symbol": c["symbol"], "exchange": "NFO"} for c in contracts)
        allowed = {s["symbol"] for s in specs}
        feed = QuoteSubscriptions(specs)
        from .daily_reports import DailyReport

        report = DailyReport(owner, profile, today, store, ROOT / "db/scanner_strategy_reports.db")
        final_status = "stopped"
        profile_index = list(PROFILES).index(profile_name)
        next_connect = time.monotonic() + connection_delay(profile_index, bool(state["legs"]))
        try:
            publish_report(report, state, "starting", datetime.now(IST), feed)
            executor = SandboxExecutor(owner, profile, state, persist)
            while not stopped[0]:
                now = datetime.now(IST)
                if now.date() != today or now.time() >= session_close(today):
                    break
                clock = time.monotonic()
                if time.monotonic() - last_save >= 10:
                    status = feed.error or "running"
                    if feed.ready and not any(
                        0 <= now.timestamp() - ts <= 15 for ts, _ in quotes.values()
                    ):
                        status = "waiting for fresh quotes — entries paused"
                    if now.strftime("%H:%M") >= "09:31" and not state["last_entry_day"]:
                        status += "; initial 09:30–09:31 entry window missed"
                    publish_report(report, state, status, now, feed)
                    persist("heartbeat", {"open_legs": len(state["legs"])})
                    last_save = clock
                if not client.connected:
                    quotes.clear()
                    feed.reset()
                    if clock >= next_connect and (
                        not client.thread or not client.thread.is_alive()
                    ):
                        client.disconnect()
                        client.connect()
                        next_connect = time.monotonic() + connection_delay(
                            profile_index, retry=True
                        )
                    time.sleep(0.5)
                    continue
                if feed.socket is not client.ws:
                    quotes.clear()
                feed.step(client, clock)
                if feed.failures and clock - last_error >= 60:
                    persist("data_unavailable", {"message": feed.error})
                    print(feed.error, flush=True)
                    last_error = clock
                # Acknowledgements may block; freshness must use the current clock.
                now = datetime.now(IST)
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
                    if state["legs"] and recover_hedges(executor, contracts, fresh, now):
                        continue
                    if not feed.ready or "NIFTY" not in fresh:
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
                        legs, snapshot = prepare_opening(owner, profile, policy, options, expiry)
                        dispatch_time = datetime.now(IST)
                        deadline = "09:31" if action["new_cycle"] else policy.reentry_cutoff
                        if (
                            dispatch_time.date() != now.date()
                            or dispatch_time.strftime("%H:%M") >= deadline
                        ):
                            raise DataUnavailable(
                                "Margin verification finished after the entry deadline"
                            )
                        executor.begin(
                            {**action, "capital_snapshot": snapshot}, legs, dispatch_time
                        )
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
                except DataUnavailable as exc:
                    if time.monotonic() - last_error >= 60:
                        persist("data_unavailable", {"message": str(exc)})
                        print(str(exc), flush=True)
                        last_error = time.monotonic()
            final_status = (
                "stopped — inspect pending orders"
                if state["pending"]
                else "session ended — open positions carried"
                if state["legs"]
                else "complete"
                if state["last_entry_day"] == str(today)
                else "no entry — entry window missed or market data unavailable"
            )
        except BaseException as exc:
            final_status = f"failed — {type(exc).__name__}: {exc}"
            raise
        finally:
            shutdown_run(
                client,
                receive,
                lambda: persist(
                    "runner_stopped",
                    {"open_legs": len(state["legs"]), "pending": bool(state["pending"])},
                ),
                lambda: publish_report(report, state, final_status, datetime.now(IST), feed),
                report,
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
