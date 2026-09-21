"""Repository-only verification. Not required on the destination computer."""

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import crypto_backtest as cb
from backtesting.ethfut_404.engine import replay
from backtesting.ha_bb_vwap_v1_20260911.replay import Maker
from strategies.ha_bb_vwap_v1.models import Candle


def main():
    proof = {"fixture": "existing ETH snapshots, first 12000 events per timeframe", "versions": []}
    for sid, d, minutes, rr in cb.STRATEGIES:
        events = np.load(ROOT / f"backtesting/ethfut_404/results/events_{minutes}m.npy", mmap_mode="r")[:12000].copy()
        expected, expected_marks = replay(events, d, minutes, .1, rr, 0., 0, 0, 0)
        state = cb.strategy_state()
        all_fills, all_marks = [], []
        for left in range(0, len(events), 137):
            right = min(len(events), left + 137)
            fills, marks = cb.trade_events(events[left:right], state, d, minutes, rr, 100000., .01, .0005, .0005, right == len(events))
            all_fills.append(fills)
            all_marks.append(marks)
        actual = np.concatenate(all_fills)
        np.testing.assert_allclose(actual, expected[:, 1:], rtol=1e-12, atol=1e-7)
        np.testing.assert_allclose(np.concatenate(all_marks), expected_marks, rtol=1e-12, atol=1e-7)
        proof["versions"].append({"id": sid, "fills_matched": len(actual)})
    # Compare forming and completed snapshots against the original Maker.
    stamp = int(datetime(2026, 1, 1, 23, 0, tzinfo=UTC).timestamp()*1e6)
    ticks = np.array([[stamp+i*20_000_000, 100+5*np.sin(i/31)+i/1000, i%7+1] for i in range(1200)])
    for minutes in (1, 5):
        events, _ = cb.make_events(ticks, minutes, cb.candle_state())
        maker, active, expected_rows = Maker([]), None, []
        for t, price, size in ticks:
            bucket = t // (minutes*60_000_000) * minutes*60_000_000
            start, now = datetime.fromtimestamp(bucket/1e6, UTC), datetime.fromtimestamp(t/1e6, UTC)
            if active is not None and active.start != start:
                final = Candle(active.start, active.start+timedelta(minutes=minutes), active.open, active.high, active.low, active.close, active.volume, True)
                snap = maker.preview(final)
                expected_rows.append([snap.ha_open,snap.ha_high,snap.ha_low,snap.ha_close,*list(vars(snap.indicators).values())[:4]])
                maker.commit(final)
                active = None
            active = Candle(start, now, active.open if active else price, max(active.high,price) if active else price, min(active.low,price) if active else price, price, (active.volume if active else 0)+size, False)
            snap = maker.preview(active)
            expected_rows.append([snap.ha_open,snap.ha_high,snap.ha_low,snap.ha_close,*list(vars(snap.indicators).values())[:4]])
        np.testing.assert_allclose(events[:,4:12], expected_rows, rtol=1e-9, atol=1e-8)
    proof["snapshot_parity"] = "1200 synthetic ticks, 1m/5m, including midnight; HA, BB and VWAP match original Maker within float tolerance"
    # Bounded synthetic throughput only, not a historical result or destination-PC benchmark.
    n = 100000
    ticks = np.column_stack((stamp+np.arange(n)*1_000_000, 100+np.sin(np.arange(n)/100), np.ones(n)))
    before = time.perf_counter()
    for minutes in (1, 5):
        events, _ = cb.make_events(ticks, minutes, cb.candle_state())
        for sid,d,m,rr in cb.STRATEGIES:
            if m == minutes:
                cb.trade_events(events, cb.strategy_state(), d, minutes, rr, 100000., .01, .0005, .0005, True)
    proof["synthetic_100k_ticks_core_seconds"] = time.perf_counter()-before
    print(json.dumps(proof,indent=2))
    cb.json_write(Path(__file__).with_name("reference_validation.json"), proof)


if __name__ == "__main__":
    main()
