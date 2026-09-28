"""NSE HA breakout forward test. Orders can reach ONLY the local sandbox service."""

import json
import math
import os
import queue
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent))
from engine import indicators
from run import metadata

IST = ZoneInfo("Asia/Kolkata")
TAG = "Narasimha_HA1m_Sep25_PAPER"


def candidate(signal, bar, ha_open, closes, pv, volume):
    """Forming-price predicate, with observed rather than modeled minute volume."""
    if signal is None or len(closes) < 19 or bar[5] <= 0:
        return False
    _, op, high, low, price, amount = bar
    hc = (op + high + low + price) / 4
    if low < ha_open - 1e-9 or hc <= ha_open or price <= signal[1]:
        return False
    window = np.array(list(closes)[-19:] + [hc])
    upper = window.mean() + 2 * window.std()
    vw = (pv + (high + low + price) / 3 * amount) / (volume + amount)
    return price > upper and price > vw


class Candles:
    def __init__(self, raw):
        ha = indicators(np.ascontiguousarray(raw, dtype=float))
        self.ho, self.hc = ha[-1, 0], ha[-1, 3]
        self.closes = deque(ha[-20:, 3], maxlen=20)
        self.bar = None
        self.signal = None
        self.pv = self.volume = self.previous_volume = 0.0
        self.last_tick = None
        self.disabled = False

    def tick(self, stamp, price, cumulative):
        minute = int(stamp // 60) * 60
        if self.last_tick is not None and (
            stamp < self.last_tick or cumulative < self.previous_volume
        ):
            self.disabled = True
            return False
        if self.last_tick is not None and stamp - self.last_tick > 90:
            self.disabled = True
        if self.bar is None or self.bar[0] != minute:
            signal = None
            if self.bar is not None:
                t, op, high, low, close, vol = self.bar
                ho = (self.ho + self.hc) / 2
                hc = (op + high + low + close) / 4
                hh, hl = max(high, ho, hc), min(low, ho, hc)
                self.closes.append(hc)
                self.pv += (high + low + close) / 3 * vol
                self.volume += vol
                upper = np.mean(self.closes) + 2 * np.std(self.closes)
                if (
                    t + 60 == minute
                    and hc > ho
                    and hl >= ho - 1e-9
                    and self.volume > 0
                    and hh > upper
                    and hh > self.pv / self.volume
                ):
                    signal = (t, hh, hl)
                self.ho, self.hc = ho, hc
            # An observed bar beginning late cannot qualify as a signal.
            if stamp - minute > 5:
                signal = None
                self.disabled = True
            self.signal = signal
            self.bar = [minute, price, price, price, price, 0.0]
        self.bar[2], self.bar[3], self.bar[4] = (
            max(self.bar[2], price),
            min(self.bar[3], price),
            price,
        )
        self.bar[5] += cumulative - self.previous_volume
        self.previous_volume, self.last_tick = cumulative, stamp
        return not self.disabled and candidate(
            self.signal, self.bar, (self.ho + self.hc) / 2, self.closes, self.pv, self.volume
        )


class Sandbox:
    """Direct sandbox path: never imports the live/mode-switching order service."""

    def __init__(self, key):
        self.key = key

    def call(self, operation, *args, **kwargs):
        from database.auth_db import db_session as auth_session
        from database.sandbox_db import db_session as sandbox_session
        from database.symbol import db_session as symbol_session

        try:
            ok, response, status = operation(*args, **kwargs)
            if not ok or response.get("mode") != "analyze":
                raise RuntimeError(f"Sandbox rejected operation ({status})")
            return response
        finally:
            sandbox_session.remove()
            auth_session.remove()
            symbol_session.remove()

    def place(self, symbol, side, qty, quote, price=0):
        from services.sandbox_service import sandbox_place_order

        order = {
            "symbol": symbol,
            "exchange": "NSE",
            "action": side,
            "quantity": qty,
            "pricetype": "LIMIT" if price else "MARKET",
            "price": price,
            "product": "MIS",
            "strategy": TAG,
        }
        return self.call(sandbox_place_order, order, self.key, order, prefetched_quote=quote)[
            "orderid"
        ]

    def status(self, orderid):
        from services.sandbox_service import sandbox_get_order_status

        return self.call(sandbox_get_order_status, {"orderid": orderid}, self.key, {})["data"]

    def cancel(self, orderid):
        from services.sandbox_service import sandbox_cancel_order

        self.call(sandbox_cancel_order, {"orderid": orderid}, self.key, {})


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from openalgo import api

    key = os.environ.get("OPENALGO_API_KEY")
    if not key:
        raise RuntimeError("Launch from OpenAlgo Python strategies: API key must be injected")
    now = datetime.now(IST)
    if now.hour * 60 + now.minute >= 15 * 60 + 20:
        print("Paper strategy: session entry/exit window has ended; no orders sent.", flush=True)
        return
    if now.hour * 60 + now.minute >= 555:
        raise RuntimeError("Start before 09:15 so today's VWAP is observed from session open")
    day = now.date().isoformat()
    state_dir = HERE / "paper_state"
    state_dir.mkdir(exist_ok=True)
    state_path = state_dir / f"{day}.json"
    # A separate process owns this byte lock until exit (including exceptions).
    import msvcrt

    with (state_dir / "runner.lock").open("a+b") as lock:
        lock.seek(0)
        if lock.read(1) == b"":
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        for prior in state_dir.glob("*.json"):
            prior_state = json.loads(prior.read_text())
            if any(p.get("phase") not in {"closed", "rejected"} for p in prior_state.values()):
                raise RuntimeError(
                    "An earlier paper run has unfinished orders: reconcile in Analyzer"
                )
        if any(p.get("phase") not in {"closed", "rejected"} for p in state.values()):
            raise RuntimeError(
                "Prior paper run has unfinished orders: reconcile in Analyzer before restarting"
            )
        selection = json.loads((HERE / "selection.json").read_text())
        symbols = selection["symbols"]
        meta = metadata(symbols)
        client = api(
            api_key=key,
            host="http://127.0.0.1:5000",
            ws_url=os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765"),
            verbose=0,
        )
        sink = Sandbox(key)
        candle_state = {}
        messages = queue.Queue(maxsize=20000)
        overflow = [False]

        def receive(message):
            try:
                messages.put_nowait(message)
            except queue.Full:
                overflow[0] = True

        def save():
            temp = state_path.with_suffix(".tmp")
            temp.write_text(json.dumps(state, indent=2))
            temp.replace(state_path)

        instruments = [{"symbol": s, "exchange": "NSE"} for s in symbols]
        try:
            for symbol in symbols:
                frame = client.history(
                    symbol=symbol,
                    exchange="NSE",
                    interval="1m",
                    start_date=(now.date() - timedelta(days=30)).isoformat(),
                    end_date=(now.date() - timedelta(days=1)).isoformat(),
                )
                if not hasattr(frame, "empty") or frame.empty:
                    print(f"SKIP {symbol}: no warmup", flush=True)
                    continue
                raw = np.column_stack(
                    [
                        frame.index.asi8 // 10**9,
                        frame[["open", "high", "low", "close", "volume"]].to_numpy(),
                    ]
                )
                minute = (raw[:, 0] + 19800) % 86400 // 60
                raw = raw[(minute >= 555) & (minute < 930)]
                if (
                    len(raw) < 20
                    or not np.isfinite(raw).all()
                    or (raw[:, 1:5] <= 0).any()
                    or (raw[:, 5] < 0).any()
                    or (raw[:, 2] < raw[:, [1, 3, 4]].max(axis=1)).any()
                    or (raw[:, 3] > raw[:, [1, 2, 4]].min(axis=1)).any()
                ):
                    print(f"SKIP {symbol}: invalid warmup", flush=True)
                    continue
                candle_state[symbol] = Candles(raw)
            if datetime.now(IST).hour * 60 + datetime.now(IST).minute >= 555:
                raise RuntimeError("Warmup completed after session open: skip today")
            client.connect()
            if not client.subscribe_quote(instruments, on_data_received=receive):
                raise RuntimeError("Quote subscription failed")
            print(
                f"PAPER ONLY: {len(candle_state)} fixed-basket symbols ready. Sandbox fills/fees may differ from modeled backtest.",
                flush=True,
            )
            last_check = 0
            while datetime.now(IST).strftime("%H:%M") < "15:24":
                if overflow[0]:
                    for candle in candle_state.values():
                        candle.disabled = True
                try:
                    message = messages.get(timeout=1)
                except queue.Empty:
                    message = None
                if message:
                    symbol, q = message.get("symbol"), message.get("data", {})
                    stamp = float(q.get("timestamp", 0))
                    if stamp > 1e12:
                        stamp /= 1000
                    price, vol = float(q.get("ltp", 0)), float(q.get("volume", -1))
                    minute = int((stamp + 19800) % 86400 // 60)
                    if (
                        symbol not in candle_state
                        or abs(time.time() - stamp) > 15
                        or not np.isfinite([stamp, price, vol]).all()
                        or price <= 0
                        or vol < 0
                        or minute < 555
                        or minute >= 930
                    ):
                        continue
                    c = candle_state[symbol]
                    qualifies = c.tick(stamp, price, vol)
                    cutoff = 905 if meta[symbol]["is_fo"] else 920
                    tick = meta[symbol]["tick"]
                    if qualifies and symbol not in state and minute < cutoff:
                        # Margin and fill semantics belong to OpenAlgo Sandbox.
                        qty = math.floor(100000 / (price * 1.001 + tick))
                        stop = math.floor((c.signal[2] - 0.10 + 1e-10) / tick) * tick
                        if qty <= 0 or stop <= 0 or stop >= price:
                            continue
                        state[symbol] = {"phase": "entry_pending", "quantity": qty, "stop": stop}
                        save()  # A crash after this point never blindly retries an order.
                        orderid = sink.place(symbol, "BUY", qty, q)
                        p = state[symbol]
                        p["entry_order"] = orderid
                        save()
                        fill = sink.status(orderid)
                        if fill["order_status"] != "complete" or fill["filled_quantity"] != qty:
                            raise RuntimeError(
                                "Paper entry not fully filled; inspect Analyzer before restart"
                            )
                        p["entry"] = fill["average_price"]
                        p["target"] = (
                            math.ceil((p["entry"] + 3 * (p["entry"] - stop) - 1e-10) / tick) * tick
                        )
                        p["target_order"] = sink.place(symbol, "SELL", qty, q, p["target"])
                        p["phase"] = "open"
                        save()
                        print(
                            f"PAPER BUY {symbol} {qty} @ {p['entry']} SL {stop} target {p['target']}",
                            flush=True,
                        )
                    p = state.get(symbol)
                    if (
                        p
                        and p["phase"] == "open"
                        and (price <= p["stop"] or price >= p["target"] or minute >= cutoff)
                    ):
                        close_position(sink, p, symbol, q, save)
                if time.monotonic() - last_check > 1:
                    last_check = time.monotonic()
                    clock_minute = datetime.now(IST).hour * 60 + datetime.now(IST).minute
                    for symbol, p in state.items():
                        if p["phase"] != "open":
                            continue
                        target = sink.status(p["target_order"])
                        if target["order_status"] == "complete":
                            p.update(phase="closed", exit=target["average_price"], reason="TARGET")
                            save()
                            print(f"PAPER TARGET {symbol}", flush=True)
                        elif clock_minute >= (905 if meta[symbol]["is_fo"] else 920):
                            # On clock exit the sandbox fetches a fresh quote itself.
                            close_position(sink, p, symbol, None, save)
            if any(p["phase"] == "open" for p in state.values()):
                raise RuntimeError("Paper positions remain: inspect Analyzer")
        finally:
            try:
                if client.connected:
                    client.unsubscribe_quote(instruments)
            finally:
                try:
                    client.disconnect()
                finally:
                    client.close()
                    from utils.httpx_client import cleanup_httpx_client

                    cleanup_httpx_client()


def close_position(sink, p, symbol, quote, save):
    target = sink.status(p["target_order"])
    if target["order_status"] == "complete":
        p.update(phase="closed", exit=target["average_price"], reason="TARGET")
        save()
        return
    try:
        sink.cancel(p["target_order"])
    except RuntimeError:
        target = sink.status(p["target_order"])
        if target["order_status"] == "complete":
            p.update(phase="closed", exit=target["average_price"], reason="TARGET")
            save()
            return
        raise
    if sink.status(p["target_order"])["order_status"] != "cancelled":
        raise RuntimeError("Target cancellation not confirmed")
    p["phase"] = "exit_pending"
    save()
    target_price = (
        p["target"] if quote and quote.get("ltp", 0) >= p.get("target", float("inf")) else 0
    )
    p["exit_order"] = sink.place(symbol, "SELL", p["quantity"], quote, target_price)
    save()
    fill = sink.status(p["exit_order"])
    if fill["order_status"] != "complete" or fill["filled_quantity"] != p["quantity"]:
        raise RuntimeError("Paper exit incomplete; inspect Analyzer")
    p.update(phase="closed", exit=fill["average_price"], reason="STOP_OR_CLOCK")
    save()
    print(f"PAPER EXIT {symbol} @ {p['exit']}", flush=True)


if __name__ == "__main__":
    main()
