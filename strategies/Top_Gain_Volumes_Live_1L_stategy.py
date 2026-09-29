"""Top Gain Volumes Live — English strategy description.

Paper forward test only, with Rs 100,000 ENTRY NOTIONAL PER TRADE (fees extra).
Universe: the union of the top 50 positive NSE gainers and top 50 positive
volume shockers (cumulative volume / prior five full-session average > 1).
Re-rank timestamped live Quote ticks; membership is checked at entry time.

Signal: completed 1-minute Heikin Ashi candle, green, no lower wick, HA high
above BB(20 HA closes, 2 population standard deviations) and raw session VWAP.
Entry: during the immediately following minute, buy at the first observed
price above signal HA high, forming upper BB and VWAP, while the forming HA
candle is green with no lower wick. DO NOT WAIT FOR THE ENTRY CANDLE TO CLOSE.
Stop: signal HA low minus Rs 0.10, rounded down to the instrument tick.
Target: entry fill plus 3 times the entry-to-stop risk, rounded up to tick.
One trade per stock per day. Whole shares, no leverage, no portfolio-wide cap.
Exit at stop/target or first fresh tick at/after 15:05 IST for ALL stocks.
The scheduled process stops at 15:10 IST. A feed outage leaves positions visibly unresolved; never
invent an exit. Stale data, missing minutes or queue overflow suppress entries.

Fills are simulated from observed ticks with 5 bps adverse market slippage;
target fills never fall below target. Charges are an illustrative 5 bps per
fill, NOT actual brokerage/taxes. No live or sandbox orders are submitted.
Warmup uses completed broker history; newly joining stocks wait until ready.
Reports, charts and a trades CSV are available in OpenAlgo Strategy Reports.
"""

import sys
from pathlib import Path

# The scheduler launches with the application root as its working directory.
sys.path.insert(0, str(Path.cwd()))
from strategies.top_gain_volumes.runtime import main

if __name__ == "__main__":
    main()
