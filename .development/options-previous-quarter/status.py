"""Print the quarter download progress; --watch refreshes the terminal every 5 seconds."""

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "backtesting/nifty_options/2026-04-08_2026-07-07/download_status.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--seconds", type=float, default=0, help="Stop watching after this many seconds; 0 means until Ctrl-C")
    args = parser.parse_args()
    started = time.monotonic()
    print("April 8–July 7, 2026 | History download", flush=True)
    try:
        while True:
            status = json.loads(STATUS.read_text())
            done, remaining = status["completed"], status["remaining"]
            total = done + remaining
            ratio = done / total if total else 0
            filled = int(ratio * 40)
            bar = "█" * filled + "░" * (40 - filled)
            line = f"[{bar}] {ratio:5.1%}  {done:,}/{total:,}  {status['status'].upper()}  Remaining: {remaining:,}  Invalid: {len(status.get('deferred_ranges', []))}"
            print("\r" + line + "    ", end="", flush=True)
            if not args.watch or status["status"] not in {"preparing", "downloading"} or (args.seconds and time.monotonic() - started >= args.seconds):
                print("\nUpdated: " + status["updated_at"])
                if status.get("reason"):
                    print(status["reason"])
                break
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nStatus display closed; downloader unchanged.")


if __name__ == "__main__":
    main()
