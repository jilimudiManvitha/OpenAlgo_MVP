"""NIFTY premium intraday, current weekly expiry; persistent Sandbox only."""

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "app.py").is_file())
sys.path.insert(0, str(ROOT))
from strategies.nifty_options.runtime import main

if __name__ == "__main__":
    main("premium_intraday_current_week")
