"""Maintainer packaging + isolated synthetic verification, no historical run."""

import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ["crypto_backtest.py", "test_crypto_backtest.py", "requirements.txt", "README.md",
         "INSTALL.cmd", "RUN.cmd", "reference_validation.json"]


def main():
    target = HERE / "crypto_four_portable.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(HERE / name, "crypto_four_portable/" + name)
    validation = HERE / "validation_tmp"
    validation.mkdir(exist_ok=True)
    env = {**os.environ, "NUMBA_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    with tempfile.TemporaryDirectory(dir=validation) as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(target) as archive:
            assert archive.testzip() is None
            archive.extractall(root)
        code = root / "crypto_four_portable"
        checks = []
        def run(args):
            completed = subprocess.run([sys.executable, *args], cwd=code, env=env, capture_output=True, text=True)
            checks.append({"args": args, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
            print(completed.stdout, completed.stderr, flush=True)
            if completed.returncode:
                raise RuntimeError("Isolated package check failed")
        run(["-m", "unittest", "-v", "test_crypto_backtest"])
        data = root / "synthetic_data"
        for symbol, folder in (("BTCUSD", "btcfut"), ("ETHUSD", "ethfut"), ("SOLUSD", "solusd"), ("XAUTUSD", "xautusdfut")):
            destination = data / folder
            destination.mkdir(parents=True)
            with (destination / "synthetic.csv").open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["product_symbol", "price", "size", "timestamp", "buyer_role"])
                for i in range(1000):
                    t = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=20*i)
                    w.writerow([symbol, 100+10*math.sin(i/20)+i/100, 1, t.isoformat(), "maker"])
        args = ["crypto_backtest.py", "--data", str(data), "--output", str(root/"synthetic_output"), "--workers", "2", "--memory", "256MB"]
        run(args)
        summary = json.loads((root/"synthetic_output/summary.json").read_text())
        assert len(summary) == 4 and sum(len(r["strategies"]) for r in summary) == 16
        assert all(r["coverage"]["processed"] == 1000 for r in summary)
        assert sum(s["trades"] for r in summary for s in r["strategies"]) > 0
        run(args)
        args[args.index("--output")+1] = str(root/"benchmark_output")
        run(args + ["--benchmark-ticks", "500"])
        assert "BENCHMARK SAMPLE" in (root/"benchmark_output/index.html").read_text()
        proof = {"isolated_zip_tests": "passed", "synthetic_coins": 4, "strategy_coin_results": 16,
                 "resume_and_benchmark_cli": "passed", "zip_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                 "checks": checks}
        (HERE/"package_validation.json").write_text(json.dumps(proof, indent=2))
    print(f"Transfer archive: {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
