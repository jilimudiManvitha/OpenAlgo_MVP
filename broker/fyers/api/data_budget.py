"""Plan-aware data quota shared by this installation's processes, without credentials.

FYERS data quotas differ from transaction/user-info quotas. Persistent counters
survive restarts; no token is stored. A rejected request establishes a common
cooldown. Callers fail promptly instead of waiting a minute with stale quotes.
"""

import hashlib
import json
import math
import os
import time
from pathlib import Path

from utils.file_lock import exclusive_file_lock

# Headroom below published Standard 5/s, 50/min, 5000/day and Prime
# 10/s, 500/min, 500000/day. History shares the same data category.
PLANS = {"standard": (0.22, 45, 4800), "prime": (0.13, 450, 480000)}


class DataRateLimited(RuntimeError):
    def __init__(self, delay, message="FYERS data budget/cooldown active"):
        self.retry_after = max(1, math.ceil(delay))
        super().__init__(message)


def plan():
    value = os.getenv("FYERS_API_PLAN", "standard").strip().lower()
    if value not in PLANS:
        raise ValueError("FYERS_API_PLAN must be standard or prime")
    return value


def state_path():
    # A stable hash partitions applications; no credentials appear in filenames.
    key = hashlib.sha256(os.getenv("BROKER_API_KEY", "unconfigured").encode()).hexdigest()[:24]
    root = Path(
        os.getenv("FYERS_DATA_BUDGET_DIR", Path(__file__).resolve().parents[3] / "log/fyers-budget")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{key}.json"


def read(path, now):
    if path.exists():
        state = json.loads(path.read_text())  # Corruption fails closed; never reset quota silently.
    else:
        state = {"day": None, "count": 0, "calls": [], "cooldown": 0}
    day = int((now + 19800) // 86400)
    if state["day"] != day:
        state.update(day=day, count=0)
    state["calls"] = [t for t in state["calls"] if t > now - 60]
    return state


def write(path, state):
    # Same stable lock protects this temporary name and atomic replacement.
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(state, allow_nan=False))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def acquire():
    interval, per_minute, per_day = PLANS[plan()]
    path = state_path()
    deadline = time.monotonic() + 1.0
    while True:
        with exclusive_file_lock(str(path) + ".lock", timeout=2):
            now = time.time()
            state = read(path, now)
            if state["cooldown"] > now:
                raise DataRateLimited(state["cooldown"] - now)
            if state["count"] >= per_day:
                raise DataRateLimited(
                    (state["day"] + 1) * 86400 - 19800 - now, "FYERS data daily budget reached"
                )
            calls = state["calls"]
            if len(calls) >= per_minute:
                raise DataRateLimited(calls[-per_minute] + 60 - now)
            delay = max(0, calls[-1] + interval - now) if calls else 0
            if delay <= 0:
                calls.append(now)
                state["count"] += 1
                write(path, state)
                return
        if time.monotonic() + delay > deadline:
            raise DataRateLimited(delay, "FYERS data request queue busy")
        time.sleep(delay)


def cooldown(delay=60):
    delay = float(delay)
    # A short Retry-After must not restart a depth storm within the same minute.
    if not math.isfinite(delay) or delay < 60:
        delay = 60
    path = state_path()
    with exclusive_file_lock(str(path) + ".lock", timeout=2):
        now = time.time()
        state = read(path, now)
        state["cooldown"] = max(state["cooldown"], now + delay)
        write(path, state)
    return delay
