"""Isolated October 13 intraday-only research; historical GETs, no order calls."""

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backtest/options_intraday_2026-10-13"
DAY = "2026-10-13"
sys.path.insert(0, str(ROOT))


def save(name, data):
    from strategies.nifty_options.history import atomic_json

    atomic_json(OUT / name, data)


def setup():
    spec = importlib.util.spec_from_file_location(
        "research_setup", ROOT / ".development/options-year/setup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private = ROOT / "log/test/options-intraday-20261013/private"
    module.setup(OUT, private)
    for key in ("SANDBOX_DATABASE_URL", "LOGS_DATABASE_URL", "LATENCY_DATABASE_URL"):
        os.environ[key] = "sqlite:///" + str(private / (key.lower() + ".db"))
    os.environ["PYTHON_STRATEGY_DATA_DIR"] = str(private / "schedules")
    from strategies.nifty_options import history

    history.CACHE = OUT / "inputs"
    return history


def budget():
    from broker.fyers.api import data_budget

    now = time.time()
    state = data_budget.read(data_budget.state_path(), now)
    limit = data_budget.PLANS[data_budget.plan()][2]
    if state["count"] >= limit - 1000:
        raise RuntimeError("Daily FYERS reserve reached; collection stopped")
    if state["cooldown"] > now:
        raise RuntimeError("Shared FYERS cooldown active; collection stopped")
    # Leave short-term capacity for the running application.
    waiting = 0
    while len(state["calls"]) >= 35:
        if waiting % 30 == 0:
            print(
                json.dumps(
                    {
                        "stage": "waiting_for_spare_capacity",
                        "recent_calls": len(state["calls"]),
                        "waited_seconds": waiting,
                    }
                ),
                flush=True,
            )
        time.sleep(5)
        waiting += 5
        now = time.time()
        state = data_budget.read(data_budget.state_path(), now)
        if state["cooldown"] > now or state["count"] >= limit - 1000:
            raise RuntimeError("Shared FYERS cooldown or daily reserve reached; collection stopped")
        if waiting >= 600:
            raise RuntimeError("No spare FYERS capacity for ten minutes; collection stopped")
    return {"daily_used": state["count"], "reserve": 1000, "recent_calls": len(state["calls"])}


def fetch_one(h, token, symbol):
    from broker.fyers.api.data import get_api_response
    from strategies.nifty_options.engine import IST

    first = int(datetime.fromisoformat(DAY).replace(tzinfo=IST).timestamp())
    raw_name = "inputs/raw/" + hashlib.sha256(symbol.encode()).hexdigest() + ".json"
    if (OUT / raw_name).exists():
        response = json.loads((OUT / raw_name).read_text())
    else:
        budget()
        response = get_api_response(
            "/data/history?"
            + urlencode(
                {
                    "symbol": symbol,
                    "resolution": "1",
                    "date_format": "0",
                    "range_from": first,
                    "range_to": first + 86399,
                    "cont_flag": "1",
                }
            ),
            token,
            retry_429=False,
        )
    if response.get("s") not in ("ok", "no_data"):
        raise RuntimeError(
            f"FYERS history unavailable: code {response.get('code')}, symbol {symbol}"
        )
    save(raw_name, response)
    unique = {}
    volume_revisions = 0
    for row in response.get("candles", []):
        if not first <= row[0] <= first + 86399:
            continue
        if row[0] in unique and unique[row[0]] != row:
            if symbol == "NSE:NIFTY50-INDEX" and unique[row[0]][:5] == row[:5]:
                volume_revisions += 1  # Index volume is unused; all OHLC prices agree.
            else:
                raise RuntimeError("Conflicting source candle: " + symbol)
        unique[row[0]] = row
    rows = [
        dict(zip(("timestamp", "open", "high", "low", "close", "volume", "oi"), r, strict=False))
        for _, r in sorted(unique.items())
    ]
    h.validate_rows(rows, check_ohlc=symbol != "NSE:NIFTY50-INDEX")
    result = {
        "broker_symbol": symbol,
        "candles": rows,
        "interval": "1m",
        "start_date": DAY,
        "end_date": DAY,
        "data_status": "ok" if rows else "no_data",
        "index_close_only": symbol == "NSE:NIFTY50-INDEX",
        "index_volume_revisions": volume_revisions,
        "duplicate_rows_removed": len(response.get("candles", [])) - len(rows),
        "source_file": raw_name,
    }
    h.write_candles(h.cache_file(symbol, DAY, DAY), result)
    return result


def prepare(h):
    from database.symbol import SymToken, db_session
    from strategies.nifty_options.data_probe import active_login

    _, token = active_login()
    try:
        rows = list(
            db_session.query(SymToken).filter(
                SymToken.exchange == "NFO",
                SymToken.name == "NIFTY",
                SymToken.instrumenttype.in_(("CE", "PE")),
            )
        )
        contracts = [
            {
                "symbol": r.brsymbol,
                "expiry": datetime.strptime(r.expiry, "%d-%b-%y").date().isoformat(),
                "strike": r.strike,
                "kind": r.instrumenttype,
                "lot_size": r.lotsize,
                "start": DAY,
                "end": DAY,
                "expired": False,
            }
            for r in rows
        ]
    finally:
        db_session.remove()
    expiries = sorted({c["expiry"] for c in contracts if c["expiry"] >= DAY})[:2]
    if len(expiries) != 2:
        raise RuntimeError("Two current option expiries required")
    contracts = sorted([c for c in contracts if c["expiry"] in expiries], key=lambda c: c["symbol"])
    assert len({c["symbol"] for c in contracts}) == len(contracts)
    assert all(c["lot_size"] == 65 for c in contracts)
    spot = h.cache_file("NSE:NIFTY50-INDEX", DAY, DAY)
    if not spot.exists():
        fetch_one(h, token, "NSE:NIFTY50-INDEX")
    manifest = {
        "start": DAY,
        "end": DAY,
        "expiries": expiries,
        "contracts": contracts,
        "spot_files": [str(spot.relative_to(ROOT))],
        "source": "FYERS historical one-minute candles and current symbol master snapshot",
        "historical_greeks": False,
    }
    save("manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "prepared",
                "expiries": expiries,
                "option_contracts": len(contracts),
                "index_candles": len(h.read_candles(spot)["candles"]),
                "budget": budget(),
            }
        ),
        flush=True,
    )
    return token, contracts


def collect(h):
    token, contracts = prepare(h)
    for i, c in enumerate(contracts):
        target = h.cache_file(c["symbol"], DAY, DAY)
        if not target.exists():
            time.sleep(2.1)
            fetch_one(h, token, c["symbol"])
        status = {"status": "collecting", "completed": i + 1, "total": len(contracts)}
        save("status.json", status)
        if (i + 1) % 10 == 0:
            print(json.dumps(status), flush=True)
    save("status.json", {"status": "downloaded", "total": len(contracts)})


def replay():
    import pandas as pd

    from strategies.nifty_options import replay as r
    from strategies.nifty_options import verify_results
    from strategies.nifty_options.engine import IST
    from strategies.nifty_options.profiles import Policy

    selected = {k: v for k, v in r.PROFILES.items() if v.holding == "intraday"}
    assert len(selected) == 6
    # Restriction is local to this research process; source files are unchanged.
    r.PROFILES = selected
    verify_results.PROFILES = selected
    folder = OUT / "results"
    (folder / "source").mkdir(parents=True, exist_ok=True)
    hashes = {}
    for source in [
        *(ROOT / "strategies/nifty_options").glob("*.py"),
        ROOT / "strategies/nifty_options/policy.json",
        ROOT / "services/report_brokerage.py",
        Path(__file__),
    ]:
        content = source.read_bytes()
        (folder / "source" / source.name).write_bytes(content)
        hashes[source.name] = hashlib.sha256(content).hexdigest()
    archive = r.Archive(OUT / "manifest.json")
    day = date.fromisoformat(DAY)
    from strategies.nifty_options import history

    coverage = []
    for contract in archive.manifest["contracts"]:
        data = history.read_candles(history.cache_file(contract["symbol"], DAY, DAY))
        history.validate_rows(data["candles"])
        assert all(
            datetime.fromtimestamp(row["timestamp"], IST).date() == day for row in data["candles"]
        )
        coverage.append(
            {
                "symbol": contract["symbol"],
                "expiry": contract["expiry"],
                "candles": len(data["candles"]),
                "duplicate_rows_removed": data.get("duplicate_rows_removed", 0),
            }
        )
    pd.DataFrame(coverage).to_csv(folder / "coverage.csv", index=False)
    calendar = archive.verify_calendar(day, day)
    save("results/calendar.json", calendar)
    summaries = []
    for path in ("OLHC", "OHLC"):
        summaries.extend(
            r.export_run(folder, path, *r.replay(archive, day, day, path, broker="fyers"))
        )
    for s in summaries:
        assert s["open_legs"] == 0
        trades = (
            pd.read_csv(folder / s["path"] / s["strategy"] / "trades.csv")
            if s["closed_legs"]
            else pd.DataFrame()
        )
        pnl = trades.groupby("cycle").net_pnl.sum() if len(trades) else pd.Series(dtype=float)
        s.update(
            completed_cycles=len(pnl),
            wins=int((pnl > 0).sum()),
            losses=int((pnl < 0).sum()),
            breakeven=int((pnl == 0).sum()),
            win_rate_pct=float((pnl > 0).mean() * 100) if len(pnl) else None,
        )
        curve = pd.read_csv(folder / s["path"] / s["strategy"] / "equity.csv")
        values = pd.Series([s["capital"], *curve.equity.tolist()])
        s["max_drawdown_pct"] = float((values / values.cummax() - 1).min() * 100)
        if len(trades):
            assert (
                trades.entry_ts.str.startswith(DAY).all()
                and trades.exit_ts.str.startswith(DAY).all()
            )
            assert abs(trades.net_pnl.sum() - s["net_pnl"]) < 0.01
        save(f"results/{s['path']}/{s['strategy']}/summary.json", s)
    spot = [
        (t, p)
        for t, p in sorted(archive.spot.items())
        if datetime.fromtimestamp(t, IST).date() == day
    ]
    pd.DataFrame(
        [{"timestamp": datetime.fromtimestamp(t, IST).isoformat(), "close": p} for t, p in spot]
    ).to_csv(folder / "benchmark.csv", index=False)
    save("results/summary.json", summaries)
    pd.DataFrame(summaries).to_csv(folder / "summary.csv", index=False)
    metadata = {
        "status": "complete",
        "start": DAY,
        "end": DAY,
        "strategies": 6,
        "paths": ["OLHC", "OHLC"],
        "trading_sessions": 1,
        "manifest_file": str((OUT / "manifest.json").relative_to(ROOT)),
        "source_hashes": archive.sources,
        "code_hashes": hashes,
        "policy": Policy.load(ROOT / "strategies/nifty_options/policy.json").to_dict(),
        "broker": "fyers",
        "nifty_gross_return_pct": (spot[-1][1] / spot[0][1] - 1) * 100,
    }
    metadata["coverage"] = {
        "contracts": len(coverage),
        "with_candles": sum(c["candles"] > 0 for c in coverage),
        "no_data": sum(c["candles"] == 0 for c in coverage),
        "full_385_minutes": sum(c["candles"] == 385 for c in coverage),
        "option_candles": sum(c["candles"] for c in coverage),
    }
    for raw in (OUT / "inputs/raw").glob("*.json"):
        metadata["source_hashes"][str(raw.relative_to(ROOT))] = hashlib.sha256(
            raw.read_bytes()
        ).hexdigest()
    bprices = pd.Series([p for _, p in spot])
    metadata["nifty_max_drawdown_pct"] = float((bprices / bprices.cummax() - 1).min() * 100)
    pd.DataFrame(
        [
            {
                "strategy": s["strategy"],
                "path": s["path"],
                "strategy_return_pct": s["return_pct"],
                "nifty_gross_return_pct": metadata["nifty_gross_return_pct"],
                "strategy_max_drawdown_pct": s["max_drawdown_pct"],
                "nifty_max_drawdown_pct": metadata["nifty_max_drawdown_pct"],
                "sharpe": None,
                "sortino": None,
                "note": "One session; annualized ratios withheld",
            }
            for s in summaries
        ]
    ).to_csv(folder / "benchmark_comparison.csv", index=False)
    save("results/verification.json", metadata)
    report(folder, summaries, metadata)
    result = verify_results.verify(folder)
    save("status.json", {"status": "complete", "verification": result})
    print(
        pd.DataFrame(summaries)[
            ["strategy", "path", "net_pnl", "fees", "completed_cycles", "wins", "losses"]
        ].to_string(index=False),
        flush=True,
    )


def report(folder, summaries, metadata):
    from html import escape

    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    sections = []
    for idx, path in enumerate(("OLHC", "OHLC")):
        rows = [s for s in summaries if s["path"] == path]
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            subplot_titles=("Net P&L at minute close", "Drawdown at minute close"),
        )
        details = []
        skipped_notes = []
        for s in rows:
            prefix = f"{path}/{s['strategy']}"
            curve = pd.read_csv(folder / prefix / "equity.csv")
            for n, values in (
                (1, curve.equity - s["capital"]),
                (2, curve.equity - curve.equity.cummax().clip(lower=s["capital"])),
            ):
                fig.add_trace(
                    go.Scatter(
                        x=curve.timestamp,
                        y=values,
                        name=s["strategy"],
                        legendgroup=s["strategy"],
                        showlegend=n == 1,
                    ),
                    row=n,
                    col=1,
                )
            details.append(
                f"<li>{s['strategy']}: <a href='{prefix}/trades.csv'>trade legs</a> · <a href='{prefix}/equity.csv'>minute equity</a> · <a href='{prefix}/skipped_entries.json'>data gaps and skipped entries</a></li>"
            )
            if not s["completed_cycles"]:
                skips = json.loads((folder / prefix / "skipped_entries.json").read_text())
                reasons = sorted({item["reason"] for item in skips})
                skipped_notes.append(
                    f"<li>{escape(s['strategy'].replace('_', ' ').title())}: {escape('; '.join(reasons) or 'No entry')}.</li>"
                )
        fig.update_layout(
            template="plotly_dark",
            height=700,
            hovermode="x unified",
            margin={"l": 65, "r": 20, "t": 40, "b": 40},
        )
        table = pd.DataFrame(rows)[
            [
                "strategy",
                "net_pnl",
                "fees",
                "return_pct",
                "completed_cycles",
                "wins",
                "losses",
                "breakeven",
                "win_rate_pct",
                "closed_legs",
                "max_drawdown_inr",
                "missing_held_bar_minutes",
                "greek_unavailable_minutes",
            ]
        ]
        sections.append(
            f"<h2>{path} modeled path</h2><p>Combined net P&L: ₹{sum(s['net_pnl'] for s in rows):,.2f} on ₹1,20,00,000 allocated across six independent strategies.</p>"
            + table.rename(columns=lambda c: c.replace("_", " ").title()).to_html(
                index=False, na_rep="N/A", float_format=lambda v: f"{v:,.2f}"
            )
            + (
                "<p>Skipped entries under the existing rules:</p><ul>"
                + "".join(skipped_notes)
                + "</ul>"
                if skipped_notes
                else ""
            )
            + fig.to_html(full_html=False, include_plotlyjs=idx == 0)
            + "<ul>"
            + "".join(details)
            + "</ul>"
        )
    html = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Options intraday — 13 October 2026</title><style>body{background:#0d1424;color:#e3eaf6;font:15px/1.6 system-ui;margin:24px}main{max-width:1500px;margin:auto}h1{font-size:30px}h2{margin-top:40px}a{color:#91b9ff}table{border-collapse:collapse;display:block;overflow:auto;font-size:13px}th,td{padding:9px;border:1px solid #34435a;text-align:right}th{background:#1c2b42}p{max-width:1100px}.note{background:#19273d;padding:16px;border-radius:10px}</style></head><body><main><h1>Six options intraday strategies</h1><p>13 October 2026 · NIFTY · current and next weekly expiry · ₹20 lakh per strategy</p><p class='note'>Historical simulation, not actual account results. Entries at 09:30; intraday exit at 15:20. All strategies use same-expiry 200-point wings. Selection uses the prior completed minute and fills use the next open. OLHC and OHLC are alternative modeled candle paths, not actual ticks or guaranteed bounds; do not add their results together. FYERS standard retail fees and ₹0.05 adverse slippage before tick rounding are included. Margin and Black-76 Greeks are estimates. Missing held bars can delay monitoring and understate drawdown; counts appear in the tables. A trade means a completed strategy cycle including adjustments; option legs are counted separately. One day cannot establish reliable Sharpe, Sortino or long-run performance.</p>"""
    html += f"<p>NIFTY gross first-to-last minute-close return: {metadata['nifty_gross_return_pct']:.3f}%. This unlevered index benchmark is not risk-equivalent to option selling.</p><p><a href='summary.csv'>Summary CSV</a> · <a href='benchmark_comparison.csv'>Benchmark comparison</a> · <a href='verification.json'>Run metadata and source hashes</a> · <a href='https://fyers.in/pricing'>FYERS pricing</a></p>"
    coverage = metadata["coverage"]
    html += f"<p>Coverage: {coverage['contracts']} listed contracts requested; {coverage['with_candles']} returned candles and {coverage['no_data']} returned no data. {coverage['full_385_minutes']} have all 385 option-session minutes. Missing prices were not filled in. <a href='coverage.csv'>Contract-by-contract coverage CSV</a>.</p>"
    html += "".join(sections) + "</main></body></html>"
    (folder / "index.html").write_text(html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("probe", "liquid-probe", "fetch", "replay", "all"))
    args = parser.parse_args()
    h = setup()
    try:
        if args.stage == "probe":
            prepare(h)
        if args.stage == "liquid-probe":
            token, contracts = prepare(h)
            spot = h.read_candles(h.cache_file("NSE:NIFTY50-INDEX", DAY, DAY))["candles"][14][
                "close"
            ]
            for expiry in sorted({c["expiry"] for c in contracts}):
                c = min(
                    (c for c in contracts if c["expiry"] == expiry and c["kind"] == "CE"),
                    key=lambda c: abs(c["strike"] - spot),
                )
                data = fetch_one(h, token, c["symbol"])
                print(
                    json.dumps(
                        {
                            "stage": "liquid_probe",
                            "symbol": c["symbol"],
                            "candles": len(data["candles"]),
                        }
                    ),
                    flush=True,
                )
                time.sleep(2.1)
        if args.stage in ("fetch", "all"):
            collect(h)
        if args.stage in ("replay", "all"):
            replay()
    except Exception as exc:
        save(
            "status.json",
            {
                "status": "blocked",
                "error": str(exc)
                if isinstance(exc, (RuntimeError, AssertionError))
                else type(exc).__name__,
            },
        )
        raise
    finally:
        from utils.httpx_client import cleanup_httpx_client

        cleanup_httpx_client()
