"""Top Gain Volumes Live — English strategy description.

Sandbox forward test only, with Rs 10,000 ENTRY NOTIONAL PER TRADE.
Universe: within Nifty500, the union of the top 50 positive NSE gainers and top 50 positive
volume shockers (cumulative volume / prior five full-session average > 1).
Re-rank timestamped live Quote ticks; membership is checked at entry time.

Signal: completed 1-minute Heikin Ashi candle, green, no lower wick, HA high
above BB(20 HA closes, 2 population standard deviations) and raw session VWAP.
Entry: during the immediately following minute, buy at the first observed
price above signal HA high, forming upper BB and VWAP, while the forming HA
candle is green with no lower wick. DO NOT WAIT FOR THE ENTRY CANDLE TO CLOSE.
Stop: signal HA low minus 0.03% (low * 0.9997), rounded down to the instrument tick.
Target: entry fill plus 3 times the entry-to-stop risk, rounded up to tick.
One open position per stock; fresh signals may re-enter after exit. Whole shares,
no portfolio-wide cap. Exit at stop/target or first fresh tick at/after 15:00 IST.
The scheduled process stops at 15:00 IST with a short exit grace. A feed outage leaves positions visibly unresolved; never
invent an exit. Stale data, missing minutes or queue overflow suppress entries.

Actual OpenAlgo Sandbox orders and confirmed fills are recorded. No live broker
orders are submitted. Sandbox does not book brokerage; charges are excluded.
Warmup uses completed broker history; newly joining stocks wait until ready.
Reports, charts and a trades CSV are available in OpenAlgo Strategy Reports.
"""

import sys
from pathlib import Path

# The scheduler launches with the application root as its working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.top_gain_volumes.runtime import main

if __name__ == "__main__":
    main()
