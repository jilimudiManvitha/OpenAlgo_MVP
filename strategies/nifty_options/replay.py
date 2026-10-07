"""Causal one-minute NIFTY option replay; local artifacts only, never app Reports.

Decisions use the prior completed minute, fills the following open. Intrabar
premium/capital stops use synchronized linear OLHC or OHLC paths and threshold
interpolation. These are alternative modeled paths, not observed tick sequences.
"""

import argparse
import hashlib
import json
import time as clock
from collections import OrderedDict, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .engine import (
    IST,
    apply_close,
    apply_open,
    decision,
    initial_state,
    opening_plan,
    risk_decision,
)
from .greeks import chain_options, historical_lot_size, historical_margin, session_close
from .history import atomic_json, existing_cache_file, read_candles
from .profiles import PROFILES, ROOT, Policy
from .selection import DataUnavailable, select_expiry, select_legs


class Archive:
    def __init__(self, manifest_path, wait_for_download=False):
        self.manifest_path = Path(manifest_path)
        self.wait_for_download = wait_for_download
        self.manifest = json.loads(self.manifest_path.read_text())
        self.expiries = [date.fromisoformat(e) for e in self.manifest["expiries"]]
        self.catalogues = defaultdict(list)
        for contract in self.manifest["contracts"]:
            self.catalogues[contract["expiry"]].append(contract)
        self.spot = {}
        self.anomalies = []
        self.sources = {}
        self.expiry_cache = OrderedDict()
        for filename in self.manifest["spot_files"]:
            path = ROOT / filename
            data = read_candles(path)
            self.anomalies.extend(data.get("source_ohlc_anomalies", []))
            for row in data["candles"]:
                stamp = int(row["timestamp"])
                if stamp in self.spot and self.spot[stamp] != row["close"]:
                    raise DataUnavailable("Conflicting index candle")
                self.spot[stamp] = row["close"]
            self.sources[filename] = hashlib.sha256(path.read_bytes()).hexdigest()

    def verify_calendar(self, start, end):
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        from database.market_calendar_db import db_session, get_holidays_by_year

        holidays = []
        try:
            for year in range(start.year, end.year + 1):
                records = get_holidays_by_year(year)
                if not records:
                    raise DataUnavailable(f"No exchange holiday calendar for {year}")
                holidays.extend(records)
        finally:
            db_session.remove()
        closed = {date.fromisoformat(h["date"]) for h in holidays if "NFO" in h["closed_exchanges"]}
        expected = {
            start + timedelta(days=i)
            for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5 and start + timedelta(days=i) not in closed
        }
        actual = {
            datetime.fromtimestamp(t, IST).date()
            for t in self.spot
            if start <= datetime.fromtimestamp(t, IST).date() <= end
        }
        if expected != actual:
            raise DataUnavailable(
                f"Session calendar mismatch: missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
            )
        return {
            "sessions": [str(d) for d in sorted(expected)],
            "holidays": holidays,
            "calendar_source": "OpenAlgo seeded NSE/NFO calendar; NSE/FAOP/71777 for 2026",
        }

    def expiry_data(self, expiry):
        if expiry in self.expiry_cache:
            self.expiry_cache.move_to_end(expiry)
            return self.expiry_cache[expiry]
        result = {}
        if expiry not in self.catalogues:
            raise DataUnavailable("Missing expiry catalogue " + expiry)
        deadline = clock.monotonic() + 3600
        while self.wait_for_download:
            missing = sum(
                not existing_cache_file(c["symbol"], c["start"], c["end"]).exists()
                for c in self.catalogues[expiry]
            )
            if not missing:
                break
            progress_path = self.manifest_path.parent / "download_status.json"
            progress = json.loads(progress_path.read_text())
            if progress["status"] in {"blocked", "interrupted"} or clock.monotonic() >= deadline:
                raise DataUnavailable(
                    "Archive unavailable: " + str(progress.get("error", progress["status"]))
                )
            print(
                json.dumps({"waiting_for_expiry": expiry, "missing_contracts": missing}), flush=True
            )
            clock.sleep(30)
        for contract in self.catalogues[expiry]:
            path = existing_cache_file(contract["symbol"], contract["start"], contract["end"])
            if not path.exists():
                raise DataUnavailable("History download incomplete for " + contract["symbol"])
            data = read_candles(path)
            # Numeric arrays bound memory while retaining exact timestamps.
            result[contract["symbol"]] = np.array(
                [
                    [r[k] for k in ("timestamp", "open", "high", "low", "close")]
                    for r in data["candles"]
                ],
                dtype=float,
            ).reshape(-1, 5)
            self.sources[str(path.relative_to(ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        self.expiry_cache[expiry] = result
        while len(self.expiry_cache) > 3:
            self.expiry_cache.popitem(last=False)
        return result

    def day(self, day, held_expiries):
        current = select_expiry(day, self.expiries, "current")
        following = select_expiry(day, self.expiries, "next")
        selected = {str(current), str(following)} | set(held_expiries)
        contracts, arrays = [], {}
        start = int(datetime.combine(day, time(9, 15), IST).timestamp())
        finish = int(datetime.combine(day, session_close(day), IST).timestamp())
        stamps = np.arange(start, finish, 60)
        for expiry in sorted(selected):
            for contract in self.catalogues[expiry]:
                data = self.expiry_data(expiry)[contract["symbol"]]
                indices = np.searchsorted(data[:, 0], stamps)
                values = np.full((len(stamps), 4), np.nan)
                valid = indices < len(data)
                valid[valid] = data[indices[valid], 0] == stamps[valid]
                values[valid] = data[indices[valid], 1:5]
                arrays[contract["symbol"]] = values
                contracts.append(contract)
        return stamps, contracts, arrays


def estimated_fill(price, side, quantity, slippage=0.05, rate=0.001, fixed=20):
    """Illustrative costs per fill; not a reconstruction of historical tax slabs."""
    fill = max(0.05, price + side * slippage)
    fill = round((np.ceil(fill / 0.05) if side > 0 else np.floor(fill / 0.05)) * 0.05, 2)
    return fill, round(fixed + rate * fill * quantity, 2)


def risk_crossing(profile, state, start, end):
    """Earliest stop crossing along a linear segment, including an opening gap."""
    if not state["legs"]:
        return None
    candidates = []
    pnl0 = state["cycle_realized"]
    pnl1 = state["cycle_realized"]
    for leg in state["legs"]:
        symbol = leg["symbol"]
        if symbol not in start or symbol not in end:
            raise DataUnavailable("Held option candle missing: " + symbol)
        a, b = start[symbol], end[symbol]
        pnl0 += (a - leg["entry"]) * leg["side"] * leg["quantity"]
        pnl1 += (b - leg["entry"]) * leg["side"] * leg["quantity"]
        if leg["side"] < 0 and profile.leg_stop_multiple:
            stop = leg["entry"] * profile.leg_stop_multiple
            if a >= stop:
                candidates.append((0.0, 1, symbol))
            elif b >= stop:
                candidates.append(((stop - a) / (b - a), 1, symbol))
    if pnl0 <= -profile.loss_limit:
        candidates.append((0.0, 0, None))
    elif pnl1 <= -profile.loss_limit:
        candidates.append(((-profile.loss_limit - pnl0) / (pnl1 - pnl0), 0, None))
    return min(candidates) if candidates else None


def close_action(state, action, prices, stamp, trades):
    legs = [
        leg
        for leg in state["legs"]
        if action["action"] == "close_all" or leg["symbol"] in action["symbols"]
    ]
    if any(leg["symbol"] not in prices for leg in legs):
        raise DataUnavailable("No contemporaneous price for a basket exit")
    fills = {
        leg["symbol"]: estimated_fill(prices[leg["symbol"]], -leg["side"], leg["quantity"])
        for leg in legs
    }
    trades.extend(
        apply_close(
            state,
            fills,
            stamp,
            action["reason"],
            action.get("reenter", False),
            action.get("halt", False),
        )
    )


def segment(profile, state, a, b, begin, end, trades):
    while state["legs"]:
        crossing = risk_crossing(profile, state, a, b)
        if crossing is None:
            break
        f, priority, symbol = crossing
        at = {s: a[s] + f * (b[s] - a[s]) for s in a.keys() & b.keys()}
        stamp = begin + (end - begin) * f
        if priority == 0:
            action = {"action": "close_all", "reason": "capital_stop", "halt": True}
        elif profile.family == "iron_condor":
            action = {"action": "close_all", "reason": "four_times_stop", "reenter": True}
        else:
            action = {"action": "close_legs", "reason": "thirty_percent_stop", "symbols": [symbol]}
        close_action(state, action, at, stamp, trades)
        # Exit fees can breach the basket loss limit; reevaluate survivors here.
        a, begin = at, stamp


def verify_vectorbt(trades, capital):
    """Independently replay all closed leg fills in bounded VectorBT batches."""
    import vectorbt as vbt

    for offset in range(0, len(trades), 1024):
        batch = trades[offset : offset + 1024]
        close = pd.DataFrame([[t["entry"] for t in batch], [t["exit"] for t in batch]])
        sizes = pd.DataFrame(
            [
                [t["side"] * t["quantity"] for t in batch],
                [-t["side"] * t["quantity"] for t in batch],
            ]
        )
        fees = pd.DataFrame(
            [[t.get("entry_fee", 0) for t in batch], [t["exit_fee"] for t in batch]]
        )
        portfolio = vbt.Portfolio.from_orders(
            close,
            size=sizes,
            price=close,
            fixed_fees=fees,
            fees=0,
            init_cash=capital,
            min_size=1,
            size_granularity=1,
        )
        expected = np.array([t["gross_pnl"] - t.get("entry_fee", 0) - t["exit_fee"] for t in batch])
        if portfolio.orders.count().sum() != 2 * len(batch) or not np.allclose(
            portfolio.total_profit().to_numpy(), expected, atol=0.001
        ):
            raise RuntimeError("VectorBT ledger reconciliation failed")


def replay(archive, start, end, path, policy=None):
    policy = policy or Policy.load(ROOT / "strategies/nifty_options/policy.json")
    states = {key: initial_state(profile, policy) for key, profile in PROFILES.items()}
    trades = {key: [] for key in PROFILES}
    curves = {key: [] for key in PROFILES}
    skipped = {key: [] for key in PROFILES}
    missing_streak = dict.fromkeys(PROFILES, 0)
    days = sorted(
        {
            datetime.fromtimestamp(t, IST).date()
            for t in archive.spot
            if start <= datetime.fromtimestamp(t, IST).date() <= end
        }
    )
    for day in days:
        held = {s["expiry"] for s in states.values() if s["legs"]}
        stamps, contracts, arrays = archive.day(day, held)
        if any(int(t) not in archive.spot for t in stamps[:375]):
            raise DataUnavailable("Incomplete NIFTY minute session: " + str(day))
        lots = {
            c["symbol"]: historical_lot_size(date.fromisoformat(c["expiry"]), day)
            for c in contracts
        }
        for index in range(len(stamps)):
            now = datetime.fromtimestamp(int(stamps[index]), IST)
            prices = [
                {s: float(a[index, col]) for s, a in arrays.items() if np.isfinite(a[index, col])}
                for col in (0, 1, 2, 3)
            ]
            previous = {
                s: float(a[index - 1, 3])
                for s, a in arrays.items()
                if index > 0 and np.isfinite(a[index - 1, 3]) and a[index - 1, 3] > 0
            }
            need_greeks = (
                index > 0
                and now.time() < time.fromisoformat(policy.reentry_cutoff)
                and (
                    time(9, 30) <= now.time() < time(9, 31)
                    or any(s["needs_reentry"] or s["legs"] for s in states.values())
                )
            )
            options = (
                chain_options(contracts, previous, archive.spot[int(stamps[index - 1])], now, lots)
                if need_greeks
                else []
            )
            for key, profile in PROFILES.items():
                state = states[key]
                missing = [
                    leg["symbol"]
                    for leg in state["legs"]
                    if any(leg["symbol"] not in phase for phase in prices)
                ]
                if missing:
                    missing_streak[key] += 1
                    skipped[key].append(
                        {
                            "timestamp": now.isoformat(),
                            "type": "missing_held_bar",
                            "symbols": missing,
                            "reason": "No complete observed basket; wait for next actual prices, no mark/fill invented",
                        }
                    )
                    if missing_streak[key] > 5 or (day == days[-1] and index == len(stamps) - 1):
                        raise DataUnavailable(
                            f"Held price gap exceeds replay policy: {key} {now.isoformat()} {missing}"
                        )
                    state["last_timestamp"] = now.isoformat()
                    continue
                missing_streak[key] = 0
                # Current open gaps/clock exits override prior-close signals.
                action = risk_decision(profile, policy, state, prices[0], now)
                if action is None and index == 0:
                    action = {"action": "wait", "reason": "opening_risk_only"}
                if action is None:
                    try:
                        action = decision(profile, policy, state, options, now, archive.expiries)
                    except DataUnavailable as exc:
                        if state["legs"]:
                            # Match the paper runner: price/clock stops keep
                            # running, while a delta adjustment waits for a
                            # usable Greek. Every such minute is disclosed.
                            skipped[key].append(
                                {
                                    "timestamp": now.isoformat(),
                                    "type": "greek_unavailable",
                                    "reason": str(exc),
                                }
                            )
                        action = {"action": "wait", "reason": str(exc)}
                if action["action"] == "open":
                    try:
                        expiry = date.fromisoformat(action["expiry"])
                        selected = select_legs(profile, policy, options, expiry)
                        margin = (
                            historical_margin(
                                profile, selected, archive.spot[int(stamps[index - 1])]
                            )
                            / 0.90
                        )
                        legs = opening_plan(profile, policy, options, expiry, margin)
                        if any(leg["symbol"] not in prices[0] for leg in legs):
                            raise DataUnavailable("Missing next-open fill")
                        fills = {
                            leg["symbol"]: estimated_fill(
                                prices[0][leg["symbol"]], leg["side"], leg["quantity"]
                            )
                            for leg in legs
                        }
                        apply_open(
                            state, profile, legs, fills, now, action["expiry"], action["new_cycle"]
                        )
                    except DataUnavailable as exc:
                        if now.time() == time(9, 30) or state["needs_reentry"]:
                            skipped[key].append({"timestamp": now.isoformat(), "reason": str(exc)})
                elif action["action"] in {"close_all", "close_legs"}:
                    close_action(state, action, prices[0], now, trades[key])
                elif action["action"] == "latch":
                    state.update(halted=True, needs_reentry=False)
                phase_indices = (0, 2, 1, 3) if path == "OLHC" else (0, 1, 2, 3)
                for phase in range(3):
                    a, b = prices[phase_indices[phase]], prices[phase_indices[phase + 1]]
                    segment(
                        profile,
                        state,
                        a,
                        b,
                        now + timedelta(seconds=phase * 20),
                        now + timedelta(seconds=(phase + 1) * 20),
                        trades[key],
                    )
                if any(leg["symbol"] not in prices[3] for leg in state["legs"]):
                    raise DataUnavailable("Missing held closing mark")
                equity = (
                    profile.capital
                    + state["total_realized"]
                    + sum(
                        (prices[3][leg["symbol"]] - leg["entry"]) * leg["side"] * leg["quantity"]
                        for leg in state["legs"]
                    )
                )
                curves[key].append(
                    {"timestamp": (now + timedelta(minutes=1)).isoformat(), "equity": equity}
                )
                state["last_timestamp"] = now.isoformat()
        print(
            json.dumps(
                {
                    "replay_day": str(day),
                    "path": path,
                    "closed_legs": sum(map(len, trades.values())),
                }
            ),
            flush=True,
        )
    return states, trades, curves, skipped


def export_run(folder, path, states, trades, curves, skipped):
    summaries = []
    for key, profile in PROFILES.items():
        output = folder / path / key
        output.mkdir(parents=True, exist_ok=True)
        verify_vectorbt(trades[key], profile.capital)
        table = pd.DataFrame(trades[key])
        if not table.empty:
            table["net_pnl"] = table["gross_pnl"] - table["entry_fee"] - table["exit_fee"]
        table.to_csv(output / "trades.csv", index=False)
        curve = pd.DataFrame(curves[key])
        curve.to_csv(output / "equity.csv", index=False)
        equity = pd.Series([float(profile.capital), *curve["equity"].tolist()])
        drawdown = equity - equity.cummax()
        summary = {
            "strategy": key,
            "path": path,
            "capital": profile.capital,
            "net_pnl": float(equity.iloc[-1] - profile.capital),
            "realized_pnl": states[key]["total_realized"],
            "fees": states[key]["fees"],
            "return_pct": float((equity.iloc[-1] / profile.capital - 1) * 100),
            "max_drawdown_inr": float(drawdown.min()),
            "closed_legs": len(trades[key]),
            "open_legs": len(states[key]["legs"]),
            "skipped_entries": sum(s.get("type") is None for s in skipped[key]),
            "greek_unavailable_minutes": sum(
                s.get("type") == "greek_unavailable" for s in skipped[key]
            ),
            "missing_held_bar_minutes": sum(
                s.get("type") == "missing_held_bar" for s in skipped[key]
            ),
            "vectorbt_reconciled": True,
        }
        atomic_json(output / "state.json", states[key])
        atomic_json(output / "skipped_entries.json", skipped[key])
        atomic_json(output / "summary.json", summary)
        summaries.append(summary)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument(
        "--wait-for-download",
        action="store_true",
        help="Wait up to one hour per expiry for an active local collector",
    )
    parser.add_argument("--paths", nargs="+", choices=["OLHC", "OHLC"], default=["OLHC", "OHLC"])
    args = parser.parse_args()
    archive = Archive(args.manifest, args.wait_for_download)
    start = args.start or date.fromisoformat(archive.manifest["start"])
    end = args.end or date.fromisoformat(archive.manifest["end"])
    if str(start) < archive.manifest["start"] or str(end) > archive.manifest["end"] or start > end:
        parser.error("Replay dates must be inside the data manifest")
    from .profiles import BACKTEST_ROOT

    folder = BACKTEST_ROOT / f"{start}_{end}" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    source_folder = folder / "source"
    source_folder.mkdir(exist_ok=True)
    code_hashes = {}
    for source in [*Path(__file__).parent.glob("*.py"), Path(__file__).with_name("policy.json")]:
        content = source.read_bytes()
        (source_folder / source.name).write_bytes(content)
        code_hashes[source.name] = hashlib.sha256(content).hexdigest()
    policy = Policy.load(source_folder / "policy.json")
    status = {"status": "running", "start": str(start), "end": str(end)}
    atomic_json(folder / "status.json", status)
    try:
        calendar = archive.verify_calendar(start, end)
        atomic_json(folder / "calendar.json", calendar)
        summaries = []
        for path in args.paths:
            summaries.extend(export_run(folder, path, *replay(archive, start, end, path, policy)))
        table = pd.DataFrame(summaries)
        table.to_csv(folder / "summary.csv", index=False)
        atomic_json(folder / "summary.json", summaries)
        spot = [
            (t, p)
            for t, p in sorted(archive.spot.items())
            if start <= datetime.fromtimestamp(t, IST).date() <= end
        ]
        benchmark = (spot[-1][1] / spot[0][1] - 1) * 100
        pd.DataFrame(
            [
                {"timestamp": datetime.fromtimestamp(t, IST).isoformat(), "close": price}
                for t, price in spot
            ]
        ).to_csv(folder / "benchmark.csv", index=False)
        metadata = {
            "status": "complete",
            "start": str(start),
            "end": str(end),
            "strategies": 12,
            "paths": args.paths,
            "manifest_file": str(archive.manifest_path.resolve().relative_to(ROOT)),
            "policy": policy.to_dict(),
            "trading_sessions": len(calendar["sessions"]),
            "option_session_close": "15:30 before 2026-08-03; 15:40 thereafter (NSE/FAOP/74467)",
            "nifty_gross_return_pct": benchmark,
            "historical_margin": "Naked: 15% notional per short; condor: 200 points + 3% notional + long premium; 10% cash reserve",
            "costs": "Illustrative 0.1% turnover + INR20 per fill; INR0.05 adverse slippage",
            "greeks": "Estimated Black-76; parity-implied forward; zero interest rate",
            "missing_observations": "Basket decisions and equity marks omitted until next complete actual bar; gaps >5 consecutive minutes or missing final held marks abort. Gap counts are disclosed per strategy.",
            "source_index_ohlc_anomalies": archive.anomalies,
            "source_hashes": archive.sources,
            "code_hashes": code_hashes,
        }
        atomic_json(folder / "verification.json", metadata)
        note = (
            "Modeled one-minute OHLC paths, not observed ticks or guaranteed bounds. "
            "Prior-minute selection, next-open fills; re-entry/adjustment execution may wait one minute. "
            "Greeks, margin and transaction costs are estimates. Open positions are marked, not force-closed. "
            "Drawdown uses minute-end marks and may miss intraminute equity lows."
            " Missing held observations delay basket monitoring; affected equity marks are omitted and gap counts are reported."
        )
        html = (
            "<!doctype html><meta charset='utf-8'><title>NIFTY options backtest</title>"
            "<style>body{font:15px system-ui;background:#111827;color:#e5e7eb;margin:32px}"
            "table{border-collapse:collapse}td,th{padding:8px;border:1px solid #374151}a{color:#93c5fd}</style>"
            f"<h1>NIFTY options · {start} to {end}</h1><p>{note}</p>"
            f"<p>NIFTY gross benchmark: {benchmark:.3f}%</p>"
            "<p><a href='summary.csv'>Summary CSV</a> · <a href='verification.json'>Assumptions and verification</a></p>"
            + table.to_html(index=False, float_format=lambda x: f"{x:,.2f}")
        )
        (folder / "index.html").write_text(html)
        from .reporting import build

        if any(
            hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != digest
            for name, digest in code_hashes.items()
        ):
            raise RuntimeError(
                "Strategy source changed during replay; rerun from the frozen source"
            )
        build(folder)
        from .verify_results import verify

        verify(folder)
        status.update(status="complete", variants=len(summaries), vectorbt_reconciled=True)
        atomic_json(folder / "status.json", status)
        print(table.to_string(index=False))
    except BaseException as exc:
        status.update(
            status="blocked",
            error=str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__,
        )
        atomic_json(folder / "status.json", status)
        raise


if __name__ == "__main__":
    main()
