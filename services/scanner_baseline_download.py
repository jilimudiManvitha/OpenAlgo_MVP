"""Optional Go download worker. One scanner job, bounded process/HTTP lifecycle."""

import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path

BINARY = (
    Path(__file__).resolve().parents[1]
    / "strategies/top_gain_volumes/native"
    / ("baseline-fetch.exe" if os.name == "nt" else "baseline-fetch")
)


def download(token, instruments, day, check_stop):
    from services.market_scanner_provider import ScannerError

    try:
        child = subprocess.Popen(
            [str(BINARY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return  # Missing/wrong-architecture native worker: use ordinary history calls.
    try:
        json.dump(
            {
                "authorization": os.environ["BROKER_API_KEY"] + ":" + token,
                "symbols": [r["broker_symbol"] for r in instruments],
                "from": (day - timedelta(days=120)).isoformat(),
                "to": (day - timedelta(days=1)).isoformat(),
            },
            child.stdin,
        )
        child.stdin.close()
        for line in child.stdout:
            check_stop()
            row = json.loads(line)
            if row["code"] in (401, 403, -8, -15, -16, -17):
                raise ScannerError("FYERS session expired during baseline download", 401)
            if row["code"] == 429:
                raise ScannerError("FYERS baseline quota reached; retry after cooldown", 429)
            yield row["symbol"], row.get("candles") if row["code"] == 200 else None
        if child.wait(timeout=5):
            raise ScannerError("Baseline download worker failed", 502)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for stream in (child.stdin, child.stdout):
            if stream:
                stream.close()
