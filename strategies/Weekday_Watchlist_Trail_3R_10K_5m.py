"""Weekday Watchlist · Trail after 3R · 10K · 5m HA.

5-minute Heikin-Ashi / BB(20,2) / session VWAP; Sandbox only.
Same rules as its 1m counterpart: Rs 10,000 per entry, stop 0.03% below
signal HA low, whole shares, 09:15-15:15 IST on NSE weekdays.
See strategies/top_gain_volumes/README.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.top_gain_volumes.runtime import main

if __name__ == "__main__":
    main('weekday_trailing_5m')
