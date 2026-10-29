"""Resumable annual archive; read-only broker calls, shared quota, no app writes."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from setup import OUT, ROOT, setup

START, END = date(2025, 10, 9), date(2026, 10, 8)
INDEX = "NSE:NIFTY50-INDEX"


class DeferredHistoryError(RuntimeError):
    """Provider data is malformed; preserve the missing range for later repair."""


def intervals(first, last, covered):
    """Missing inclusive ranges, bounded by the provider's 100-day limit."""
    day, end = date.fromisoformat(first), date.fromisoformat(last)
    while day <= end:
        if day.isoformat() in covered:
            day += timedelta(days=1)
            continue
        begin = day
        while day <= end and day.isoformat() not in covered and (day - begin).days < 100:
            day += timedelta(days=1)
        yield str(begin), str(day - timedelta(days=1))


def merge(rows, incoming, first, last):
    from strategies.nifty_options.engine import IST

    for row in incoming:
        stamp = row["timestamp"]
        if not first <= datetime.fromtimestamp(stamp, IST).date().isoformat() <= last:
            continue
        if stamp in rows and any(
            rows[stamp][k] != row[k] for k in ("open", "high", "low", "close")
        ):
            raise RuntimeError("Conflicting source prices; archive not combined")
        rows[stamp] = row


def source_index(h):
    sources = defaultdict(list)
    archives = [
        ROOT / "backtesting/nifty_options/2025-10-09_2026-10-08/manifest.json",
        ROOT / "backtesting/nifty_options/2026-07-08_2026-10-07/manifest.json",
        ROOT / "backtest/nifty_options/2026-07-03_2026-10-01/manifest.json",
        ROOT / "backtest/nifty_options/2021-10-03_2026-10-01/manifest.json",
        ROOT / "backtesting/all_scheduled_20261006/inputs/manifest.json",
        ROOT / "log/test/day-review-20261007/inputs/manifest.json",
    ]
    seen = set()
    for path in archives:
        if not path.exists():
            continue
        manifest = json.loads(path.read_text())
        for c in manifest["contracts"]:
            if c["end"] < str(START) or c["start"] > str(END):
                continue
            candidate = h.existing_cache_file(c["symbol"], c["start"], c["end"])
            if not candidate.exists():
                candidate = path.parent / "options/candles" / candidate.name
            key = (c["symbol"], c["start"], c["end"], str(candidate))
            if candidate.exists() and key not in seen:
                sources[c["symbol"]].append((c["start"], c["end"], candidate))
                seen.add(key)
    return sources


def collect(args):
    from broker.fyers.api import data_budget
    from strategies.nifty_options import history as h
    from strategies.nifty_options.data_probe import active_login, expired_call

    manifest = json.loads((OUT / "manifest.json").read_text())
    sources = source_index(h)
    spots = []
    day = START
    while day <= END:
        finish = min(day + timedelta(days=99), END)
        spots.append(dict(symbol=INDEX, start=str(day), end=str(finish), expired=False))
        day = finish + timedelta(days=1)
    work = spots + manifest["contracts"]
    progress = dict(
        status="preparing",
        contracts=len(manifest["contracts"]),
        spot_chunks=len(spots),
        completed=0,
        remaining=len(work),
        requests_this_run=0,
        reused_this_run=0,
        reserve_requests=args.reserve,
        deferred_ranges=[],
        pid=os.getpid(),
    )

    def save():
        progress["updated_at"] = datetime.now().astimezone().isoformat()
        h.atomic_json(OUT / "download_status.json", progress)
        print(json.dumps(progress), flush=True)

    def prepare(c):
        symbol, first, last = c["symbol"], c["start"], c["end"]
        target = h.existing_cache_file(symbol, first, last)
        if target.exists():
            h.validate_rows(h.read_candles(target)["candles"], check_ohlc=symbol != INDEX)
            return None
        rows, covered, used = {}, set(), []
        for a, b, path in sources[symbol]:
            if a > last or b < first:
                continue
            data = h.read_candles(path)
            h.validate_rows(data["candles"], check_ohlc=symbol != INDEX)
            merge(rows, data["candles"], first, last)
            day, end = max(a, first), min(b, last)
            d = date.fromisoformat(day)
            while d.isoformat() <= end:
                covered.add(d.isoformat())
                d += timedelta(days=1)
            used.append(
                dict(
                    file=str(path.relative_to(ROOT)),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        missing = list(intervals(first, last, covered))
        return rows, used, missing

    def write(c, rows, used):
        candles = [r for _, r in sorted(rows.items())]
        h.validate_rows(candles, check_ohlc=c["symbol"] != INDEX)
        h.write_candles(
            h.cache_file(c["symbol"], c["start"], c["end"]),
            dict(
                broker_symbol=c["symbol"],
                candles=candles,
                start_date=c["start"],
                end_date=c["end"],
                interval="1m",
                data_status="ok" if candles else "no_data",
                provenance=used,
                index_close_only=c["symbol"] == INDEX,
            ),
        )

    save()
    try:
        # First exhaust local reuse across the entire year, even when quota is unavailable.
        pending = []
        for i, c in enumerate(work):
            prepared = prepare(c)
            if prepared is None:
                progress["completed"] += 1
            elif not prepared[2]:
                write(c, prepared[0], prepared[1])
                progress["completed"] += 1
                progress["reused_this_run"] += 1
            else:
                pending.append(c)
            if i % 1000 == 0:
                progress["remaining"] = len(work) - progress["completed"]
                save()
        progress["remaining"] = len(pending)
        if args.prepare_only:
            progress["status"] = "prepared"
            return
        _, token = active_login()
        progress["status"] = "downloading"
        save()
        for c in pending:
            rows, used, missing = prepare(c)
            deferred = False
            for first, last in missing:
                chunk = h.existing_cache_file(c["symbol"], first, last)
                if chunk.exists():
                    data = h.read_candles(chunk)
                else:
                    now = time.time()
                    state = data_budget.read(data_budget.state_path(), now)
                    daily_limit = data_budget.PLANS[data_budget.plan()][2]
                    progress["shared_budget_used"] = state["count"]
                    if state["count"] >= daily_limit - args.reserve:
                        progress.update(
                            status="blocked",
                            reason="Daily data reserve reached; resume after quota reset and valid login",
                        )
                        return
                    if progress["requests_this_run"] >= args.max_requests:
                        progress.update(
                            status="paused",
                            reason="Configured request cap reached; rerun to resume",
                        )
                        return
                    if state["cooldown"] > now:
                        progress.update(
                            status="blocked", reason="Broker cooldown active; retry later"
                        )
                        return
                    # Default leaves capacity for the app; an offline quarter run may opt in.
                    time.sleep(getattr(args, "request_delay", 2.1 if data_budget.plan() == "standard" else 0.2))
                    if getattr(args, "before_request", None):
                        args.before_request()
                    # A multi-day download may outlive a formerly current contract.
                    expired = (
                        date.fromisoformat(c["expiry"]) < date.today()
                        if c.get("expiry")
                        else c["expired"]
                    )
                    if expired:
                        try:
                            data = getattr(args, "history_fetcher", expired_call)(
                                token,
                                "history",
                                dict(
                                    broker_symbol=c["symbol"],
                                    interval="1m",
                                    start_date=first,
                                    end_date=last,
                                    include_oi=True,
                                ),
                            )
                        except DeferredHistoryError:
                            progress["deferred_ranges"].append(dict(symbol=c["symbol"], start=first, end=last, reason="Invalid provider candles"))
                            deferred = True
                            save()
                            break
                    else:
                        data = h.regular_history(token, c["symbol"], first, last)
                    h.validate_rows(data["candles"], check_ohlc=c["symbol"] != INDEX)
                    chunk = h.cache_file(c["symbol"], first, last)
                    h.write_candles(chunk, data)
                    progress["requests_this_run"] += 1
                h.validate_rows(data["candles"], check_ohlc=c["symbol"] != INDEX)
                merge(rows, data["candles"], c["start"], c["end"])
                # Do not add a self-reference when this chunk is the entire requested range.
                if chunk != h.cache_file(c["symbol"], c["start"], c["end"]):
                    used.append(
                        dict(
                            file=str(chunk.relative_to(ROOT)),
                            sha256=hashlib.sha256(chunk.read_bytes()).hexdigest(),
                        )
                    )
            if deferred:
                continue
            write(c, rows, used)
            progress["completed"] += 1
            progress["remaining"] -= 1
            if progress["completed"] % 10 == 0:
                save()
        manifest["spot_files"] = [
            str(h.existing_cache_file(c["symbol"], c["start"], c["end"]).relative_to(ROOT))
            for c in spots
        ]
        h.atomic_json(OUT / "manifest.json", manifest)
        if progress["deferred_ranges"]:
            progress.update(status="blocked", reason="Invalid provider history remains; full replay withheld")
        else:
            progress["status"] = "download_complete"
    except KeyboardInterrupt:
        progress.update(
            status="interrupted", reason="Stopped; validated chunks retained for resume"
        )
        raise
    except Exception as exc:
        # Do not serialize exception text: network errors can contain authenticated URLs.
        progress.update(status="blocked", reason="Collection failed: " + type(exc).__name__)
        # These messages are generated locally and contain only status/code, never URLs.
        detail = str(exc)
        if re.fullmatch(r"Expired history history failed: HTTP \d{3}, code (?:-?\d+|None)", detail) or detail in {
            "Full-quota collection requires OpenAlgo stopped",
            "FYERS expired-history budget unavailable for more than five minutes",
            "Exactly one active FYERS login is required",
        }:
            progress["reason"] = detail
        raise RuntimeError(progress["reason"]) from None
    finally:
        save()
        from utils.httpx_client import cleanup_httpx_client

        cleanup_httpx_client()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--reserve", type=int, default=1000)
    parser.add_argument("--max-requests", type=int, default=4000)
    args = parser.parse_args()
    if args.reserve < 1000 or args.max_requests < 0:
        parser.error("Keep at least 1000 requests reserved and use a nonnegative request cap")
    setup()
    with (ROOT / "log/test/options-year/collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        collect(args)
