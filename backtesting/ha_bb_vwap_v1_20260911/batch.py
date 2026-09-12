"""Run independent stock replays in three local processes, then build reports."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from replay import source_files


def run_stock(symbol):
    env = dict(os.environ, POLARS_MAX_THREADS="2", NUMBA_NUM_THREADS="1")
    command = [sys.executable, str(HERE / "run.py"), "--only-symbol", symbol]
    with subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as process:
        output = []
        for line in process.stdout:
            output.append(line)
            print(f"[{symbol}] {line.rstrip()}", flush=True)
        code = process.wait()
    if code:
        raise RuntimeError(f"{symbol} failed: {''.join(output)[-4000:]}")
    return symbol


if __name__ == "__main__":
    symbols = [row[1] for row in source_files()]
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(run_stock, symbols))
    subprocess.run([sys.executable, str(HERE / "run.py"), "--report-only"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(HERE / "findings.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(HERE / "verify.py")], cwd=ROOT, check=True)
