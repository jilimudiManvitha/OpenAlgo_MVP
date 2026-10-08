"""One offline daily journal HTML, using the application's brokerage/metric functions."""

import collections
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import run

ROOT, OUT, DAY = run.ROOT, run.OUT, run.DAY
run.setup()
from services.report_brokerage import COMPONENTS, estimate_report, tariff
from services.report_journal import day_metrics
from strategies.nifty_options import history
from strategies.nifty_options.profiles import PROFILES
from strategies.nifty_options.replay import verify_vectorbt


def load(path):
    return json.loads((OUT / path).read_text())


def epoch(ts):
    return datetime.fromisoformat(ts).timestamp() if isinstance(ts, str) else ts


def summarize(trades):
    m = day_metrics(trades, DAY)
    m["unrealized"] = sum(t.get("unrealized", 0) for t in trades if t.get("exit_ts") is None)
    m["total_net"] = m["net_pnl"] + m["unrealized"] - m["open_entry_charges"]
    m["all_charges"] = m["charges"] + m["open_entry_charges"]
    m["all_brokerage"] = sum(t["charge_breakdown"]["brokerage"] for t in trades)
    m["total_entry_value"] = sum(t["entry"] * t["quantity"] for t in trades)
    return {k: round(v, 6) if isinstance(v, float) else v for k, v in m.items()}


def enriched(result, trades, exchange, product):
    report = estimate_report(
        {"broker": "fyers", "exchange": exchange, "product": product, "trades": trades}
    )
    assert report["charge_info"]["unavailable"] == 0
    result["trades"] = report["trades"]
    for i, t in enumerate(result["trades"]):
        t.update(
            id=f"{result['strategy']}:{result['path']}:{i}",
            strategy=result["strategy"],
            strategy_name=result["name"],
            family=result["family"],
        )
        assert t["quantity"] > 0 and int(t["quantity"]) == t["quantity"]
        assert math.isfinite(t["fees"]) and t["fees"] >= 0
        if t.get("exit_ts") is not None:
            sign = -1 if t["side"] in (-1, "SELL") else 1
            assert abs(t["gross_pnl"] - (t["exit"] - t["entry"]) * t["quantity"] * sign) < 1e-5
            assert abs(t["net_pnl"] - round(t["gross_pnl"] - t["fees"], 2)) < 1e-6
    result["metrics"] = summarize(result["trades"])
    return result


def model():
    selection = load("inputs/selection.json")
    manifest = load("inputs/manifest.json")
    manifest["source"] = (
        "FYERS read-only 1-minute history, completed October 7 session; current symbol master"
    )
    run.base.save("inputs/manifest.json", manifest)
    with closing(sqlite3.connect((OUT / "openalgo.db").as_uri() + "?mode=ro", uri=True)) as conn:
        mapping = dict(conn.execute("SELECT brsymbol,symbol FROM symtoken WHERE exchange='NFO'"))
    contracts = {c["symbol"]: c for c in manifest["contracts"]}
    candles = {
        symbol: history.read_candles(history.cache_file(symbol, DAY, DAY)) for symbol in contracts
    }
    coverage = {
        "contracts": len(contracts),
        "with_data": sum(bool(c["candles"]) for c in candles.values()),
        "empty_contracts": [symbol for symbol, data in candles.items() if not data["candles"]],
        "stock_files": len(selection["stocks"]),
        "long_universe": len(selection["longs"]),
        "short_universe": len(selection["shorts"]),
        "watchlist": len(selection["watchlist"]),
        "snapshot_time": selection["snapshot_time"],
        "expiries": manifest["expiries"],
    }
    output = []
    for r in load("stocks.json"):
        trades = [
            {**t, "side": t.get("side", "BUY"), "exchange": "NSE", "product": "MIS"}
            for t in r["trades"]
        ]
        r["status"] = (
            "Complete" if all(c["eligible"] for c in r["coverage"]) else "Partial coverage"
        )
        if not r["universe_size"]:
            r["status"] = "No symbols in watchlist"
        r["capital_allocation"] = None
        result = enriched(r, trades, "NSE", "MIS")
        verify_vectorbt(
            [
                {
                    **t,
                    "side": -1 if t["side"] in (-1, "SELL") else 1,
                    "entry_fee": t["entry_estimated_fees"],
                    "exit_fee": round(t["fees"] - t["entry_estimated_fees"], 2),
                }
                for t in result["trades"]
            ],
            max(2_000_000, result["metrics"]["peak_capital"]),
        )
        output.append(result)
    for path in ("OLHC", "OHLC"):
        data = load("options/" + path + "/details.json")
        for key, profile in PROFILES.items():
            trades = []
            state = data["states"][key]
            for source in [*data["trades"][key], *state["legs"]]:
                t = dict(source)
                broker_symbol = t["symbol"]
                t.update(
                    symbol=mapping[broker_symbol],
                    broker_symbol=broker_symbol,
                    entry_ts=epoch(t["entry_ts"]),
                    path=path,
                    exchange="NFO",
                    product="NRML",
                    fees=0,
                    gross_pnl=t.get("gross_pnl", 0),
                    net_pnl=0,
                )
                if t.get("exit_ts"):
                    t["exit_ts"] = epoch(t["exit_ts"])
                    assert (
                        abs(
                            (source["entry_fee"] + source["exit_fee"])
                            - sum(
                                estimate_report(
                                    {
                                        "broker": "fyers",
                                        "exchange": "NFO",
                                        "product": "NRML",
                                        "trades": [t],
                                    }
                                )["trades"][0]["charge_breakdown"].values()
                            )
                        )
                        < 0.011
                    )
                else:
                    last = candles[broker_symbol]["candles"][-1]
                    assert (
                        datetime.fromtimestamp(last["timestamp"], run.base.IST).strftime("%H:%M")
                        == "15:39"
                    ), "Missing final held mark"
                    t.update(
                        exit_ts=None,
                        exit=None,
                        mark=last["close"],
                        mark_ts=last["timestamp"],
                        reason="OPEN",
                        unrealized=(last["close"] - t["entry"]) * t["side"] * t["quantity"],
                    )
                trades.append(t)
            skipped = data["skipped"][key]
            result = {
                "strategy": key,
                "name": key.replace("_", " ").title(),
                "family": "NIFTY options",
                "path": path,
                "skipped": skipped,
                "coverage": [],
                "capital_allocation": profile.capital,
                "curve": data["curves"][key],
                "status": "Complete" if trades else "No eligible entry",
                "positional": profile.positional,
            }
            result = enriched(result, trades, "NFO", "NRML")
            expected = data["curves"][key][-1]["equity"] - profile.capital
            assert abs(expected - result["metrics"]["total_net"]) <= 0.011 * max(1, len(trades)), (
                key,
                path,
                expected,
                result["metrics"]["total_net"],
            )
            # Entry-time model reserve, computed from selected long premiums and prior index close.
            batches = collections.defaultdict(list)
            for t in result["trades"]:
                batches[t["entry_ts"]].append(t)
            reserves = []
            for batch in batches.values():
                assert len(batch) == 4, (key, "Every new basket requires four legs")
                assert len({t["quantity"] for t in batch}) == 1
                assert len({t["expiry"] for t in batch}) == 1
                for kind, offset in (("CE", 200), ("PE", -200)):
                    wing = next(t for t in batch if t["kind"] == kind and t["side"] == 1)
                    short = next(t for t in batch if t["kind"] == kind and t["side"] == -1)
                    assert wing["strike"] == short["strike"] + offset
            spots = history.read_candles(ROOT / manifest["spot_files"][0])["candles"]
            spot_map = {r["timestamp"]: r["close"] for r in spots}
            for ts, batch in batches.items():
                longs = [t for t in batch if t["side"] == 1]
                if len(batch) == 4 and len(longs) == 2:
                    # Engine margin uses previous close premiums, not slipped execution prices.
                    prior_ts = int(ts // 60) * 60 - 60
                    premium = sum(
                        next(
                            r["close"]
                            for r in candles[t["broker_symbol"]]["candles"]
                            if r["timestamp"] == prior_ts
                        )
                        for t in longs
                    )
                    reserves.append(
                        batch[0]["quantity"] * (200 + 0.03 * spot_map[prior_ts] + premium) / 0.9
                    )
            result["modeled_peak_reserve"] = max(reserves, default=0)
            output.append(result)
    assert len(output) == 56 and len({r["strategy"] for r in output}) == 28
    scenarios = {}
    for path in ("OLHC", "OHLC"):
        rows = [r for r in output if r["path"] == path]
        trades = [t for r in rows for t in r["trades"]]
        total = summarize(trades)
        for metric in (
            "net_pnl",
            "gross_pnl",
            "charges",
            "wins",
            "losses",
            "trades",
            "open_trades",
            "total_net",
        ):
            assert abs(total[metric] - sum(r["metrics"][metric] for r in rows)) < 0.001
        scenarios[path] = total
    spot = history.read_candles(ROOT / manifest["spot_files"][0])
    benchmark = {
        "name": "NIFTY 50",
        "start_price": spot["candles"][0]["close"],
        "end_price": spot["candles"][-1]["close"],
        "start_time": "09:15",
        "end_time": "15:29",
        "return_pct": 100 * (spot["candles"][-1]["close"] / spot["candles"][0]["close"] - 1),
    }
    result = {
        "day": DAY,
        "built": datetime.now(run.base.IST).isoformat(),
        "broker": "fyers",
        "tariff": tariff("fyers"),
        "components": COMPONENTS,
        "coverage": coverage,
        "benchmark": benchmark,
        "results": output,
        "scenarios": scenarios,
    }
    run.base.save("report-data.json", result)
    print(
        json.dumps(
            {
                "scenario_totals": scenarios,
                "coverage": {k: v for k, v in coverage.items() if k != "empty_contracts"},
            },
            indent=2,
        )
    )
    return result


def build():
    data = model()
    template = Path(__file__).with_name("template.html").read_text()
    payload = (
        json.dumps(data, separators=(",", ":"), allow_nan=False)
        .replace("<", "\\u003c")
        .replace("&", "\\u0026")
    )
    result = template.replace("__DATA__", payload)
    path = ROOT / "backtesting/all_strategies_2026-10-07.html"
    path.write_text(result)
    print(
        "HTML",
        path,
        "bytes",
        path.stat().st_size,
        "sha256",
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


if __name__ == "__main__":
    build()
