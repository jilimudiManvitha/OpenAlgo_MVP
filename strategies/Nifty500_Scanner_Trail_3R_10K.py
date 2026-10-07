"""Nifty 500 positive gainers/shockers; HA OHLC above VWAP, trail after 3R.

Rs 10,000 per entry; completed signal and forming entry HA OHLC above VWAP.
Stop: 0.03% below signal HA low (low * 0.9997), rounded down to instrument tick.
3R arms middle-band exit without selling at 3R.
Fresh signals may re-enter after exit; 1-minute candles, 09:15-15:15 IST.
See strategies/top_gain_volumes/README.md for complete rules and execution mode.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.top_gain_volumes.runtime import main

if __name__ == "__main__":
    main("nifty500_trailing")
