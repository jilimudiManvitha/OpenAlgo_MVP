"""April 8–July 7 replay using existing catalogue/cache; annual download stays stopped."""

import argparse
import fcntl
import hashlib
import json
import socket
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".development/options-year"))
from setup import setup
import collect as collector

START, END = date(2026, 4, 8), date(2026, 7, 7)
OUT = ROOT / "backtesting/nifty_options/2026-04-08_2026-07-07"
LOG = ROOT / "log/test/options-previous-quarter"
DESTINATION = ROOT / "backtesting/options_3months_2026-07-07.html"


def require_app_stopped():
    for port in (5000, 8765):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError("Full-quota collection requires OpenAlgo stopped")


def quarter_history(token, operation, payload):
    from services.expired_data_service import get_expired_data

    for attempt in range(4):
        require_app_stopped()
        ok, result, status = get_expired_data(operation, payload, auth_token=token, broker="fyers")
        if ok:
            return result["data"]
        if status == 502 and result.get("message") == "FYERS returned an invalid expired-data response.":
            raise collector.DeferredHistoryError()
        if status not in {429, 500, 502, 503, 504} or attempt == 3:
            break
        delay = max((5, 15, 30)[attempt], float(result.get("retry_after", 0)))
        if delay > 300:
            raise RuntimeError("FYERS expired-history budget unavailable for more than five minutes")
        time.sleep(delay + 0.1)
    raise RuntimeError(f"Expired history history failed: HTTP {status}, code {result.get('code')}")


def prepare():
    from strategies.nifty_options import history as h
    from strategies.nifty_options.engine import IST
    from strategies.nifty_options.replay import Archive

    source = ROOT / "backtesting/nifty_options/2025-10-09_2026-10-08/manifest.json"
    annual = json.loads(source.read_text())
    if not (OUT / "manifest.json").exists():
        contracts = []
        for original in annual["contracts"]:
            c = dict(original)
            c["start"], c["end"] = max(c["start"], str(START)), min(c["end"], str(END))
            if c["start"] <= c["end"]:
                contracts.append(c)
        spot = h.cache_file(collector.INDEX, str(START), str(END))
        rows, provenance = {}, []
        for filename in annual["spot_files"]:
            path = ROOT / filename
            data = h.read_candles(path)
            selected = [
                r
                for r in data["candles"]
                if START <= datetime.fromtimestamp(r["timestamp"], IST).date() <= END
            ]
            if selected:
                h.validate_rows(selected, check_ohlc=False)
                collector.merge(rows, selected, str(START), str(END))
                provenance.append(
                    dict(file=filename, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                )
        candles = [r for _, r in sorted(rows.items())]
        if not spot.exists():
            h.write_candles(
                spot,
                dict(
                    broker_symbol=collector.INDEX,
                    candles=candles,
                    start_date=str(START),
                    end_date=str(END),
                    interval="1m",
                    data_status="ok",
                    index_close_only=True,
                    provenance=provenance,
                    source_ohlc_anomalies=[
                        r
                        for r in candles
                        if not r["low"]
                        <= min(r["open"], r["close"])
                        <= max(r["open"], r["close"])
                        <= r["high"]
                    ],
                ),
            )
        manifest = dict(
            start=str(START),
            end=str(END),
            contracts=contracts,
            expiries=annual["expiries"],
            spot_files=[str(spot.relative_to(ROOT))],
            interval="1m",
            source="FYERS actual listed contracts",
            historical_greeks=False,
            catalogue_source=dict(
                file=str(source.relative_to(ROOT)),
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            ),
        )
        h.atomic_json(OUT / "manifest.json", manifest)
    calendar = Archive(OUT / "manifest.json").verify_calendar(START, END)
    h.atomic_json(OUT / "calendar_preflight.json", calendar)
    print(
        json.dumps(
            {"period": [str(START), str(END)], "verified_index_sessions": len(calendar["sessions"])}
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--max-requests", type=int, default=500000)
    parser.add_argument("--full-quota", action="store_true",
                        help="Use the published plan quota without a foreground reserve; app must remain stopped")
    args = parser.parse_args()
    if args.max_requests < 0:
        parser.error("Request cap must be nonnegative")
    LOG.mkdir(parents=True, exist_ok=True)
    setup(out=OUT, private_dir=LOG / "private")
    if args.full_quota:
        require_app_stopped()
        from broker.fyers.api import data_budget

        # Process-local settings only. Keep the existing shared usage counter.
        data_budget.PLANS = {"standard": (0.22, 50, 5000), "prime": (0.13, 500, 500000)}
        args.before_request = require_app_stopped
        args.history_fetcher = quarter_history
        args.request_delay = 1.25 if data_budget.plan() == "standard" else 0.13
    collector.START, collector.END, collector.OUT = START, END, OUT
    with (LOG / "collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepare()
        if not args.report_only:
            args.reserve = 0 if args.full_quota else 1000
            collector.collect(args)
        if args.prepare_only:
            return 0
        status = json.loads((OUT / "download_status.json").read_text())
        if status["status"] != "download_complete" or status["remaining"]:
            print(json.dumps({"report": "pending", "download": status}, indent=2))
            return 2
        subprocess.run(
            [
                sys.executable,
                "-m",
                "strategies.nifty_options.replay",
                "--manifest",
                str(OUT / "manifest.json"),
                "--broker",
                "fyers",
            ],
            cwd=ROOT,
            check=True,
        )
        results = OUT / "results"
        complete = json.loads((results / "status.json").read_text())
        metadata = json.loads((results / "verification.json").read_text())
        assert complete["status"] == "complete" and complete["variants"] == 24
        assert metadata["start"] == str(START) and metadata["end"] == str(END)
        subprocess.run(
            ["node", ".development/options-year/verify_report.cjs", str(results)],
            cwd=ROOT,
            check=True,
        )
        content = (results / "combined_dashboard.html").read_bytes()
        temporary = DESTINATION.with_suffix(".html.tmp")
        temporary.write_bytes(content)
        temporary.replace(DESTINATION)
        print(
            json.dumps({"report": str(DESTINATION), "sha256": hashlib.sha256(content).hexdigest()})
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
