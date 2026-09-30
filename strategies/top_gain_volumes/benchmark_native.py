"""Reproducible local math benchmark; optional read-only FYERS baseline comparison."""

import argparse
import json
import sqlite3
import time
import timeit
from contextlib import closing
from datetime import datetime

import numpy as np

from strategies.top_gain_volumes.fast_math import BACKEND, bands
from strategies.top_gain_volumes.profiles import ROOT
from strategies.top_gain_volumes.runtime import IST


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    values = tuple(float(x) for x in range(100, 120))
    iterations = 50000
    def old():
        return float(np.mean(values)), float(np.mean(values) + 2 * np.std(values))
    result = {
        "timestamp": datetime.now(IST).isoformat(),
        "math_backend": BACKEND,
        "math_iterations": iterations,
        "bands_us": min(timeit.repeat(lambda: bands(values), number=iterations, repeat=3))
        * 1e6
        / iterations,
        "old_numpy_us": min(timeit.repeat(old, number=iterations, repeat=3)) * 1e6 / iterations,
        "note": "Math-only microbenchmark, not observed feed-to-order latency. Network timings include startup/pacing and may vary.",
    }
    if args.network:
        from services.market_scanner_provider import (
            FyersScannerProvider,
            get_fyers_token,
            load_universe,
        )
        from services.scanner_baseline_download import download
        from utils.httpx_client import cleanup_httpx_client

        with closing(sqlite3.connect("file:db/market_scanner_live.db?mode=ro", uri=True)) as c:
            owners = c.execute(
                "SELECT user FROM scanner_live_accounts WHERE broker='fyers'"
            ).fetchall()
        if len(owners) != 1:
            raise RuntimeError("Select one FYERS account before benchmarking")
        token = get_fyers_token(owners[0][0])
        items = [
            x for x in load_universe() if x["symbol"] in {"RELIANCE", "SBIN", "TCS", "INFY", "ITC"}
        ]
        day = datetime.now(IST).date()
        try:
            started = time.perf_counter()
            with closing(download(token, items, day, lambda: None)) as stream:
                native = dict(stream)
            result["go_download_seconds"] = time.perf_counter() - started
            provider = FyersScannerProvider(token)
            started = time.perf_counter()
            ordinary = {i["broker_symbol"]: provider.history(i, day) for i in items}
            result["python_download_seconds"] = time.perf_counter() - started
            result["download_symbols"] = len(items)
            result["download_parity"] = native == ordinary and all(ordinary.values())
            if not result["download_parity"]:
                raise RuntimeError("Native baseline output did not match ordinary FYERS history")
        finally:
            cleanup_httpx_client()
    output = ROOT / "db/scanner_backtest_cache/native-benchmark.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
