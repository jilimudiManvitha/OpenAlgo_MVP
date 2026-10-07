"""Nifty500 Scanner · SHORT · Fixed 3R · 10K · 5m HA. Sandbox-only; SELL entry / BUY cover.

All signal and forming-entry HA OHLC below VWAP; lower-BB breakdown.
Rs 10,000 per trade; stop 0.03% above signal HA high; 09:15–15:15 IST.
See strategies/short_equity/README.md after the evening integration.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.short_equity.runtime import main

if __name__ == "__main__":
    main("nifty500_short_fixed_5m")
