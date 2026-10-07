"""Live Quote driven Sandbox strategies with independent per-strategy reports."""

import json
import math
import os
import queue
import signal
import sqlite3
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from services.market_scanner_service import rank_rows, validate_options
from services.scanner_strategy_reports import ReportStore
from strategies.top_gain_volumes.fast_math import BACKEND, bands
from strategies.top_gain_volumes.history import fetch_intraday_history
from strategies.top_gain_volumes.profiles import ROOT, nifty500_symbols, weekday_symbols

from .profiles import PROFILES

IST = ZoneInfo("Asia/Kolkata")
SQUARE_OFF_MINUTE = 15 * 60 + 15
SHUTDOWN_GRACE_SECONDS = 60
OPTIONS = validate_options({"limit": 50, "positive_only": False})


def eligible_symbols(rows, now, allowed=None):
    fresh = [
        r
        for r in rows.values()
        if 0 <= now - r.get("live_stamp", 0) <= 15
        and r.get("change_percent", 0) < 0
        and (allowed is None or r["symbol"] in allowed)
    ]
    # Mirror the long ranking, including the volume-shocker change% tie-break:
    # most negative changes become the largest positive ranking scores.
    ranked = rank_rows([{**r, "change_percent": -r["change_percent"]} for r in fresh], OPTIONS)
    return {r["symbol"] for group in ("top_gainers", "volume_shockers") for r in ranked[group]}


class TickCandles:
    """Completed historical seed followed by causal forming candles."""

    def __init__(self, raw, now, strict_vwap=True, timeframe_minutes=1):
        from strategies.top_gain_volumes.history import aggregate_minutes

        if timeframe_minutes not in (1, 5):
            raise ValueError("Supported candle timeframes are 1 and 5 minutes")
        self.interval = timeframe_minutes * 60
        if not strict_vwap:
            raise ValueError("Short profiles require every signal/entry HA OHLC below VWAP")
        self.strict_vwap = True
        self.middle = None
        self.last_completed = None
        self.closes = deque(maxlen=20)
        self.chart = deque(maxlen=390)
        self.bar = None
        self.signal = None
        self.ho = self.hc = None
        self.pv = self.volume = 0.0
        self.previous_volume = None
        self.last_tick = now
        self.invalid = False
        self.complete = False
        day = datetime.fromtimestamp(now, IST).date()
        boundary = int(now // self.interval) * self.interval
        # Validate source minutes before aggregation: a missing minute must not
        # silently become an apparently complete 5-minute bar.
        opening = int(datetime.combine(day, datetime.min.time(), IST).timestamp()) + 555 * 60
        expected_minutes = set(range(opening, int(now // 60) * 60, 60))
        actual_minutes = {int(r[0]) for r in raw if opening <= r[0] < int(now // 60) * 60}
        if actual_minutes != expected_minutes:
            raise ValueError("Today's warmup minutes are incomplete")
        raw = aggregate_minutes(raw, timeframe_minutes, now)
        completed = [r for r in raw if r[0] < boundary]
        partial = [r for r in raw if r[0] == boundary]
        current = [r for r in completed if datetime.fromtimestamp(r[0], IST).date() == day]
        expected = set(range(opening, boundary, self.interval))
        if {int(r[0]) for r in current} != expected:
            raise ValueError("Today's warmup minutes are incomplete")
        for row in completed:
            same_day = datetime.fromtimestamp(row[0], IST).date() == day
            self._finish(row, same_day)
        self.signal = None  # Joining mid-minute cannot enter retrospectively.
        self.seeded_at = now
        if partial:
            self.bar = list(partial[0])
            self.previous_volume = self.volume + self.bar[5]
            self.complete = True
        elif now >= opening and now - boundary > 2:
            raise ValueError("Current minute history is needed to bridge live ticks")

    def _finish(self, bar, same_day=True):
        stamp, op, high, low, close, volume = bar
        ho = (op + close) / 2 if self.ho is None else (self.ho + self.hc) / 2
        hc = (op + high + low + close) / 4
        hh, hl = max(high, ho, hc), min(low, ho, hc)
        self.closes.append(hc)
        self.ho, self.hc = ho, hc
        middle, upper = bands(self.closes)
        lower = 2 * middle - upper
        self.middle = middle
        self.signal = None
        if same_day:
            self.pv += (high + low + close) / 3 * volume
            self.volume += volume
            vw = self.pv / self.volume if self.volume else 0
            self.chart.append(
                {
                    "timestamp": stamp,
                    "open": op,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "ha_open": ho,
                    "ha_high": hh,
                    "ha_low": hl,
                    "ha_close": hc,
                    "bb_upper": upper,
                    "bb_lower": lower,
                    "bb_middle": middle,
                    "vwap": vw,
                }
            )
            self.last_completed = (stamp, close, middle)
            if (
                len(self.closes) == 20
                and volume > 0
                and hc < ho
                and hh <= ho + 1e-9
                and hl < lower
                and hh < vw
            ):
                self.signal = (stamp, hh, hl)

    def tick(self, stamp, price, cumulative):
        if stamp < self.seeded_at:
            return False
        minute = int(stamp // self.interval) * self.interval
        if self.previous_volume is not None and cumulative < self.previous_volume:
            self.invalid = True
            return False
        if self.last_tick is not None:
            if (
                stamp < self.last_tick
                or (self.previous_volume is not None and cumulative < self.previous_volume)
                or stamp - self.last_tick > 90
            ):
                self.invalid = True
                return False
        if self.bar is None or minute != self.bar[0]:
            if self.bar is not None:
                prior = self.bar[0]
                self._finish(self.bar)
                if not self.complete or prior + self.interval != minute:
                    self.signal = None
            # Need the start of a complete observed minute for a valid signal.
            self.complete = stamp - minute <= 2
            self.bar = [minute, price, price, price, price, 0.0]
        if self.previous_volume is None:
            # Exclude the unseen part of the joining minute from signal eligibility.
            delta = max(0, cumulative - self.volume)
            self.complete = stamp - minute <= 2
        else:
            delta = cumulative - self.previous_volume
        self.bar[2] = max(self.bar[2], price)
        self.bar[3] = min(self.bar[3], price)
        self.bar[4] = price
        self.bar[5] += delta
        self.previous_volume, self.last_tick = cumulative, stamp
        lower = -math.inf
        if self.ho is not None and len(self.closes) >= 19:
            self.middle, upper = bands(list(self.closes)[-19:] + [sum(self.bar[1:5]) / 4])
            lower = 2 * self.middle - upper
        if (
            self.invalid
            or self.signal is None
            or self.signal[0] + self.interval != minute
            or len(self.closes) < 19
        ):
            return False
        _, op, high, low, close, vol = self.bar
        ho = (self.ho + self.hc) / 2
        hc = (op + high + low + close) / 4
        vw = (
            (self.pv + (high + low + close) / 3 * vol) / (self.volume + vol)
            if self.volume + vol
            else -math.inf
        )
        return bool(
            vol > 0
            and high <= ho + 1e-9
            and hc < ho
            and price < self.signal[2]
            and price < lower
            and max(high, ho, hc) < vw
        )


def fill_price(price, tick, buy):
    return (
        math.ceil(price * 1.0005 / tick - 1e-9) if buy else math.floor(price * 0.9995 / tick + 1e-9)
    ) * tick


def enter(symbol, stamp, price, candle, tick, capital=10000):
    fill = fill_price(price, tick, False)
    qty = int(capital // fill)
    # Three basis points above signal HA high; round away from entry.
    stop = math.ceil((candle.signal[1] * 1.0003) / tick - 1e-9) * tick
    target = math.floor((fill - 3 * (stop - fill)) / tick + 1e-9) * tick
    if qty <= 0 or not 0 < target < fill < stop:
        return None
    return {
        "symbol": symbol,
        "path": "PAPER",
        "direction": "SHORT",
        "side": "SELL",
        "signal_ts": candle.signal[0],
        "timeframe_minutes": getattr(candle, "interval", 60) // 60,
        "entry_ts": stamp,
        "exit_ts": None,
        "entry": fill,
        "exit": None,
        "quantity": qty,
        "stop": stop,
        "target": target,
        "fees": fill * qty * 0.0005,
        "gross_pnl": 0,
        "net_pnl": -fill * qty * 0.0005,
        "reason": "OPEN",
    }


def exit_trade(
    trade,
    stamp,
    price,
    tick,
    cutoff,
    trailing=False,
    middle=None,
    closed_bar=None,
    trail_on_close=False,
):
    minute = int((stamp + 19800) % 86400 // 60)
    if trailing and price <= trade["target"] and not trade.get("trail_armed"):
        trade.update(trail_armed=True, trail_armed_at=stamp)
    trail_exit = False
    if trailing and trade.get("trail_armed"):
        if trail_on_close:
            trail_exit = bool(
                closed_bar
                and closed_bar[0] + 60 > trade["trail_armed_at"]
                and closed_bar[1] > closed_bar[2]
            )
        else:
            trail_exit = middle is not None and price > middle
    reason = (
        "STOP"
        if price >= trade["stop"]
        else "TARGET"
        if not trailing and price <= trade["target"]
        else "BB_MIDDLE"
        if trail_exit
        else "SQUARE_OFF"
        if minute >= cutoff
        else None
    )
    if reason is None:
        return False
    fill = (
        min(trade["target"], fill_price(price, tick, True))
        if reason == "TARGET"
        else fill_price(price, tick, True)
    )
    fees = (trade["entry"] + fill) * trade["quantity"] * 0.0005
    gross = (trade["entry"] - fill) * trade["quantity"]
    trade.update(
        exit_ts=stamp, exit=fill, reason=reason, fees=fees, gross_pnl=gross, net_pnl=gross - fees
    )
    return True


def shutdown_runtime(client, receive, executor, store, persist, cleanup_http):
    """Attempt every cleanup even if saving, disconnecting or joining raises."""
    with ExitStack() as cleanup:
        cleanup.callback(cleanup_http)
        cleanup.callback(store.close)
        cleanup.callback(persist)
        cleanup.callback(executor.shutdown, wait=True, cancel_futures=True)
        cleanup.callback(client.disconnect)
        cleanup.callback(client.unregister_callback, "market_data", receive)
        persist()  # Durable snapshot before any potentially slow worker join.


def maintain_positions(sink, traded, report, quotes, now, stopping=False):
    """Reconcile even without ticks; clock square-off cannot depend on a new tick."""
    cutoff = (
        stopping
        or datetime.fromtimestamp(now, IST).hour * 60 + datetime.fromtimestamp(now, IST).minute
        >= SQUARE_OFF_MINUTE
    )
    for symbol, trade in list(traded.items()):
        if trade["exit_ts"] is not None:
            continue
        state = sink.reconcile(trade, now, cancel_entry=cutoff)
        if state == "rejected":
            report["trades"].remove(trade)
            report.setdefault("rejected_entries", []).append(trade)
            del traded[symbol]
        elif state == "open" and cutoff:
            quote = quotes.get(symbol)
            if quote and 0 <= now - quote[0] <= 15:
                sink.exit(trade, now, quote[1], "SQUARE_OFF")


def stopping_phase(report, now, clock, deadline, persist):
    """Persist a visible stopping state before a potentially slow exit batch."""
    if deadline is None and now.hour * 60 + now.minute >= SQUARE_OFF_MINUTE:
        deadline = clock + SHUTDOWN_GRACE_SECONDS
    if deadline is not None and report["status"] != "stopping — reconciling positions":
        report["status"] = "stopping — reconciling positions"
        report["updated_at"] = now.isoformat()
        persist()
    return deadline


def entries_blocked(traded):
    return any(
        t.get(field + "_state") in ("pending", "uncertain", "dispatch_intent")
        for t in traded.values()
        if t["exit_ts"] is None
        for field in ("entry_order", "exit_order")
    )


def restore_quote_feed(client, symbols, subscribed_socket):
    """Restore subscriptions after the local proxy replaces a client socket."""
    if not client.connected:
        if client.thread and client.thread.is_alive():
            return None  # Its own bounded reconnect loop is still in progress.
        client.disconnect()  # Close before starting another event-loop thread.
        if not client.connect():
            return None
    if not client.authenticated:
        return None
    if client.ws is subscribed_socket:
        return subscribed_socket
    for offset in range(0, len(symbols), 50):
        reply = client.subscribe(
            [{"symbol": s, "exchange": "NSE"} for s in symbols[offset : offset + 50]], "Quote"
        )
        if reply.get("status") != "success":
            return None
    return client.ws


def main(profile_id="nifty500_short_fixed"):
    from pathlib import Path

    if Path(__file__).resolve().parent != ROOT / "strategies" / "short_equity":
        raise RuntimeError(
            "Staged short strategies cannot run; merge after the user stops OpenAlgo"
        )
    from dotenv import load_dotenv

    load_dotenv()
    from database.auth_db import db_session, verify_api_key
    from database.symbol import SymToken
    from database.symbol import db_session as symbols_db
    from services.market_scanner_provider import (
        FyersScannerProvider,
        get_fyers_token,
        load_universe,
    )
    from services.websocket_client import WebSocketClient

    key = os.environ.get("OPENALGO_API_KEY")
    try:
        owner = verify_api_key(key) if key else None
    finally:
        db_session.remove()
    if not owner:
        raise RuntimeError("An authenticated OpenAlgo scheduler API key is required")
    now = datetime.now(IST)
    day = now.date().isoformat()
    profile = PROFILES[profile_id]
    allowed = (
        nifty500_symbols()
        if profile["universe"] == "nifty500"
        else weekday_symbols(owner, now.date())
    )
    report_id = f"paper-{day}-{profile_id}"
    report = {
        "id": report_id,
        "day": day,
        "kind": "Sandbox · " + profile["name"],
        "strategy_id": profile_id,
        "direction": "SHORT",
        "capital_per_trade": 10000,
        "timeframe_minutes": profile["timeframe_minutes"],
        "calculation_backend": BACKEND,
        "status": "starting",
        "paths": ["PAPER"],
        "trades": [],
        "candles": {},
        "coverage": [],
        "note": profile["name"] + ". ₹10,000 per trade; fresh signals may re-enter after exits. "
        "Short SELL entry / BUY cover. Stop: 0.03% above signal HA high, rounded up to tick. "
        "Observed Quote ticks; actual OpenAlgo Sandbox order IDs and confirmed fills. "
        "09:15–15:15 IST; fresh quotes are required to square off at 15:15. "
        "Sandbox does not book brokerage; reported P&L excludes charges. "
        "Realized drawdown excludes intratrade equity. No live broker orders.",
    }
    universe = {r["symbol"]: r for r in load_universe()}
    instruments = [universe[s] for s in sorted(allowed) if s in universe]
    report["unavailable_symbols"] = sorted(allowed - set(universe))
    subscribed = {r["symbol"] for r in instruments}
    try:
        ticks = {
            r[0]: float(r[1])
            for r in symbols_db.query(SymToken.symbol, SymToken.tick_size).filter(
                SymToken.exchange == "NSE"
            )
            if r[1] and r[1] > 0
        }
    finally:
        symbols_db.remove()
    client = WebSocketClient(
        key,
        host=os.getenv("WEBSOCKET_HOST", "localhost"),
        port=int(os.getenv("WEBSOCKET_PORT", "8765")),
    )
    messages = queue.Queue(maxsize=20000)
    overflow = [False]
    stopped = [False]
    stop_deadline = [None]

    def receive(message):
        try:
            messages.put_nowait(message)
        except queue.Full:
            overflow[0] = True

    def stop(*_):
        if stop_deadline[0] is None:
            stop_deadline[0] = time.monotonic() + SHUTDOWN_GRACE_SECONDS

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    rows, trackers, pending, traded = {}, {}, {}, {}
    last_snapshot = last_rank = last_save = last_reconcile = last_feed = 0
    subscribed_socket = None
    quotes = {}
    last_quote_at = 0
    attempted = {}
    eligible = set()
    used_signals = {}
    latencies = deque(maxlen=10000)
    from .sandbox_execution import SandboxExecution

    sink = SandboxExecution(owner, profile_id, lambda: store.save(owner, report))
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paper-warmup")

    def warmup(symbol):
        # A refreshed broker login must take effect without restarting a run.
        provider = FyersScannerProvider(get_fyers_token(owner))
        raw = fetch_intraday_history(
            provider, universe[symbol]["broker_symbol"], day, shared=True, owner=owner
        )
        fetched_at = time.time()
        boundary = int(fetched_at // 60) * 60
        raw = [r for r in raw if r[0] <= boundary and 555 <= (r[0] + 19800) % 86400 // 60 < 930]
        if (
            len(raw) < 20
            or not np.isfinite(raw).all()
            or any(
                r[1] <= 0 or r[3] <= 0 or r[5] < 0 or r[2] < max(r[1:5]) or r[3] > min(r[1:5])
                for r in raw
            )
        ):
            raise ValueError("Invalid warmup")
        if any(a[0] >= b[0] for a, b in zip(raw, raw[1:], strict=False)):
            raise ValueError("Unordered warmup")
        return TickCandles(
            raw,
            fetched_at,
            strict_vwap=True,
            timeframe_minutes=profile["timeframe_minutes"],
        )

    store = ReportStore()
    claimed = False
    try:
        if store.get(owner, report_id):
            raise RuntimeError(
                "This day's paper run already exists; inspect its report before restarting"
            )
        claimed = store.claim(owner, report)
        if not claimed:
            raise RuntimeError("A paper run already owns this session")
        client.register_callback("market_data", receive)
        report["status"] = "running"
        while not stopped[0]:
            clock = time.monotonic()
            stop_deadline[0] = stopping_phase(
                report,
                datetime.now(IST),
                clock,
                stop_deadline[0],
                lambda: store.save(owner, report),
            )
            if stop_deadline[0] is not None and (
                clock >= stop_deadline[0] or not any(t["exit_ts"] is None for t in traded.values())
            ):
                break
            if client._dispatch_dropped:
                overflow[0] = True
            if clock - last_feed >= 5 and stop_deadline[0] is None:
                last_feed = clock
                subscribed_socket = restore_quote_feed(
                    client, sorted(subscribed), subscribed_socket
                )
            if clock - last_reconcile >= 1:
                last_reconcile = clock
                maintain_positions(
                    sink, traded, report, quotes, time.time(), stop_deadline[0] is not None
                )
            if clock - last_snapshot >= 2:
                last_snapshot = clock
                if profile["universe"] == "watchlist":
                    allowed = weekday_symbols(owner, now.date())
                    additions = allowed.intersection(universe) - subscribed
                    if additions:
                        reply = client.subscribe(
                            [{"symbol": s, "exchange": "NSE"} for s in sorted(additions)], "Quote"
                        )
                        if reply.get("status") == "success":
                            subscribed.update(additions)
                with closing(
                    sqlite3.connect("file:db/market_scanner_live.db?mode=ro", uri=True, timeout=2)
                ) as conn:
                    saved = conn.execute(
                        "SELECT snapshot FROM scanner_live_accounts WHERE user=? AND broker='fyers'",
                        (owner,),
                    ).fetchone()
                snapshot = json.loads(saved[0]) if saved and saved[0] else {}
                if snapshot.get("session_date") == day:
                    for row in snapshot.get("rows", []):
                        if row["symbol"] not in subscribed:
                            continue
                        existing = rows.get(row["symbol"])
                        if existing:
                            existing["average_volume"] = row.get("average_volume")
                        else:
                            rows[row["symbol"]] = dict(row)
            for symbol, future in list(pending.items()):
                if future.done():
                    try:
                        trackers[symbol] = future.result()
                        report.setdefault("warmup_skipped", {}).pop(symbol, None)
                    except Exception as exc:
                        from services.market_scanner_provider import ScannerError

                        if isinstance(exc, ScannerError) and exc.status_code in (401, 403):
                            report.setdefault("warmup_skipped", {})[symbol] = (
                                "Broker login required; retrying after one minute"
                            )
                        else:
                            report.setdefault("warmup_skipped", {})[symbol] = (
                                "Incomplete or unavailable history; retrying after one minute"
                            )
                    del pending[symbol]
            if clock - last_rank >= 0.25:
                last_rank = clock
                eligible = (
                    eligible_symbols(rows, time.time(), allowed)
                    if profile["universe"] == "nifty500"
                    else allowed.intersection(universe)
                )
                for symbol in list(trackers):
                    if trackers[symbol].invalid or (
                        symbol not in eligible
                        and (symbol not in traded or traded[symbol]["exit_ts"] is not None)
                    ):
                        if symbol in traded:
                            report["candles"][symbol] = list(trackers[symbol].chart)
                        del trackers[symbol]
                active = {s for s, t in traded.items() if t["exit_ts"] is None}
                for symbol in sorted(eligible | active, key=lambda s: (s not in active, s)):
                    if (
                        symbol not in trackers
                        and symbol not in pending
                        and len(pending) < 8
                        and clock - attempted.get(symbol, -60) >= 60
                    ):
                        attempted[symbol] = clock
                        pending[symbol] = executor.submit(warmup, symbol)
            try:
                message = messages.get(timeout=0.05)
            except queue.Empty:
                message = None
            if message:
                decision_start = time.perf_counter_ns()
                symbol, q = message.get("symbol"), message.get("data", {})
                try:
                    stamp = float(q["timestamp"])
                    if stamp > 1e12:
                        stamp /= 1000
                    traded_at = float(q.get("last_traded_time") or q.get("last_trade_time") or 0)
                    if traded_at > 1e12:
                        traded_at /= 1000
                    price, volume = float(q["ltp"]), float(q["volume"])
                    valid = (
                        message.get("mode") in (2, "2", "Quote", "QUOTE")
                        and np.isfinite([stamp, price, volume, traded_at]).all()
                        and 0 <= time.time() - stamp <= 15
                        and 0 <= time.time() - traded_at <= 15
                        and price > 0
                        and volume >= 0
                        and datetime.fromtimestamp(stamp, IST).date().isoformat() == day
                    )
                except (KeyError, ValueError, TypeError, OverflowError):
                    valid = False
                if valid and symbol in subscribed and symbol in ticks:
                    last_quote_at = time.time()
                    quotes[symbol] = (min(stamp, traded_at), q)
                    if symbol not in rows and profile["universe"] == "watchlist":
                        rows[symbol] = {"symbol": symbol, "previous_close": price}
                    if symbol not in rows:
                        continue
                    row = rows[symbol]
                    if stamp < row.get("live_stamp", 0):
                        continue
                    row.update(
                        ltp=price,
                        volume=volume,
                        live_stamp=stamp,
                        change_percent=(price / row["previous_close"] - 1) * 100,
                        rvol=volume / row["average_volume"] if row.get("average_volume") else None,
                    )
                    minute = int((stamp + 19800) % 86400 // 60)
                    cutoff = SQUARE_OFF_MINUTE
                    candle = trackers.get(symbol)
                    qualifies = (
                        candle.tick(stamp, price, volume)
                        if candle and 555 <= minute < 930
                        else False
                    )
                    if symbol in traded and traded[symbol]["exit_ts"] is None:
                        trade = traded[symbol]
                        if trade.get("entry_order_state") != "complete" or trade.get(
                            "exit_order_state"
                        ) in ("pending", "uncertain", "dispatch_intent"):
                            continue
                        decision = dict(trade)
                        should_exit = exit_trade(
                            decision,
                            stamp,
                            price,
                            ticks[symbol],
                            cutoff,
                            profile["trailing"],
                            candle.middle if candle and not candle.invalid else None,
                            candle.last_completed if candle else None,
                        )
                        for field in ("trail_armed", "trail_armed_at"):
                            if field in decision:
                                trade[field] = decision[field]
                        if should_exit:
                            sink.exit(trade, stamp, q, decision["reason"])
                    elif (
                        qualifies
                        and symbol
                        in (
                            eligible_symbols(rows, time.time(), allowed)
                            if profile["universe"] == "nifty500"
                            else allowed
                        )
                        and candle.signal[0] != used_signals.get(symbol)
                        and minute < cutoff
                        and not overflow[0]
                        and stop_deadline[0] is None
                        and not entries_blocked(traded)
                        and client.connected
                        and client.authenticated
                        and subscribed_socket is client.ws
                    ):
                        from sandbox.execution_engine import quote_looks_stale

                        if quote_looks_stale(q):
                            continue  # Do not consume the signal; await a coherent quote.
                        trade = enter(symbol, stamp, price, candle, ticks[symbol])
                        if trade:
                            used_signals[symbol] = candle.signal[0]
                            report["trades"].append(trade)
                            if sink.enter(trade, q, ticks[symbol]):
                                traded[symbol] = trade
                            else:
                                report["trades"].remove(trade)
                                report.setdefault("rejected_entries", []).append(trade)
                                store.save(owner, report)
                    latencies.append((time.perf_counter_ns() - decision_start) / 1000)
            if stop_deadline[0] is not None:
                report["status"] = "stopping — reconciling positions"
            elif overflow[0]:
                report["status"] = "feed overflow — entries disabled"
            else:
                report["status"] = (
                    "awaiting order reconciliation — entries paused"
                    if entries_blocked(traded)
                    else "running"
                )
                if (
                    subscribed_socket is None
                    or not client.connected
                    or not client.authenticated
                    or (subscribed and time.time() - last_quote_at > 15)
                ):
                    report["status"] = "waiting for quote feed — entries paused"
            if clock - last_save >= 5:
                last_save = clock
                report["candles"].update(
                    {s: list(trackers[s].chart) for s in traded if s in trackers}
                )
                report["updated_at"] = datetime.now(IST).isoformat()
                report["streaming_symbols"] = client.get_subscriptions()["count"]
                report["eligible_symbols"] = len(eligible)
                report["ready_symbols"] = len(trackers)
                report["warming_symbols"] = len(pending)
                if latencies:
                    report["decision_latency_us"] = {
                        "p50": float(np.percentile(latencies, 50)),
                        "p95": float(np.percentile(latencies, 95)),
                        "samples": len(latencies),
                    }
                store.save(owner, report)
        report["status"] = (
            "unresolved positions"
            if any(t["exit_ts"] is None for t in report["trades"])
            else "complete"
        )
    except BaseException:
        report["status"] = "interrupted — inspect open positions"
        raise
    finally:
        from utils.httpx_client import cleanup_httpx_client

        def persist_final():
            if claimed:
                report["updated_at"] = datetime.now(IST).isoformat()
                report["candles"].update(
                    {s: list(trackers[s].chart) for s in traded if s in trackers}
                )
                store.save(owner, report)

        shutdown_runtime(client, receive, executor, store, persist_final, cleanup_httpx_client)
