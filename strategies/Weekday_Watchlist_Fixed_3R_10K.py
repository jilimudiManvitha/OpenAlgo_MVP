"""Today's Mon/Tue/Wed/Thu/Fri /trading watchlist; original HA breakout, fixed 3R.

Rs 10,000 per entry, whole shares, fresh signals can re-enter after an exit.
Stop: 0.03% below signal HA low (low * 0.9997), rounded down to instrument tick.
One open position per symbol per strategy. 1-minute candles, 09:15-15:00 IST.
See strategies/top_gain_volumes/README.md for complete rules and execution mode.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.top_gain_volumes.runtime import main

if __name__ == "__main__":
    main("weekday_fixed")
