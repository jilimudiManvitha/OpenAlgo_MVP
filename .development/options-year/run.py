"""Resume annual data collection, then replay and publish only verified full-year results."""

import argparse
import hashlib
import json
import subprocess
import sys

from setup import OUT, ROOT, setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if not args.report_only:
        subprocess.run(
            [sys.executable, str(ROOT / ".development/options-year/collect.py")],
            cwd=ROOT,
            check=True,
        )
    status = json.loads((OUT / "download_status.json").read_text())
    if status["status"] != "download_complete" or status["remaining"]:
        print(json.dumps({"report": "pending", "download": status}, indent=2))
        return 2
    setup()
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
    assert metadata["start"] == "2025-10-09" and metadata["end"] == "2026-10-08"
    # Browser checks run against the new annual artifacts, never the old report.
    subprocess.run(
        ["node", ".development/options-year/verify_report.cjs", str(results)], cwd=ROOT, check=True
    )
    content = (results / "combined_dashboard.html").read_bytes()
    destination = ROOT / "backtesting/options_1yearBacktest.html"
    temporary = destination.with_suffix(".html.tmp")
    temporary.write_bytes(content)
    temporary.replace(destination)
    print(
        json.dumps(
            {"report": str(destination), "sha256": hashlib.sha256(content).hexdigest()}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
