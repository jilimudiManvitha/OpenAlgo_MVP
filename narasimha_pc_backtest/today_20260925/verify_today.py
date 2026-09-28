"""Include pre-session indicator warmup in the independent ledger verifier."""

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run
import verify_results


def main():
    out = HERE / "output"
    cfg = json.loads((out / "manifest.json").read_text())["config"]
    boundary = run.stamp(cfg["start"])
    with run.connect(cfg["source"]) as source, duckdb.connect() as export:
        for symbol in cfg["symbols"]:
            path = out / "candles" / f"{symbol}.parquet"
            current = export.execute(
                "SELECT * FROM read_parquet(?) WHERE timestamp>=? ORDER BY timestamp",
                [str(path), boundary],
            ).fetchdf()
            frame = source.execute(
                "SELECT timestamp,open,high,low,close,volume FROM market_data WHERE symbol=? ORDER BY timestamp",
                [symbol],
            ).fetchdf()
            raw = frame.to_numpy(dtype=float)
            minute = (raw[:, 0] + 19800) % 86400 // 60
            valid = (
                (minute >= 555)
                & (minute < 930)
                & (raw[:, 0] + 60 <= cfg["asof_timestamp"])
                & np.isfinite(raw).all(axis=1)
                & (raw[:, 1:5] > 0).all(axis=1)
                & (raw[:, 5] >= 0)
                & (raw[:, 2] >= np.max(raw[:, [1, 3, 4]], axis=1))
                & (raw[:, 3] <= np.min(raw[:, [1, 2, 4]], axis=1))
            )
            raw = np.ascontiguousarray(raw[valid])
            calculated = pd.DataFrame(
                np.column_stack([raw, run.indicators(raw)]),
                columns=list(frame.columns) + run.HA_COLS,
            )
            # Check the warmup reconstruction agrees with every exported indicator.
            np.testing.assert_allclose(
                calculated.loc[calculated.timestamp >= boundary, run.HA_COLS],
                current[run.HA_COLS],
                equal_nan=True,
            )
            warmup = calculated[calculated.timestamp < boundary].copy()
            warmup["eligible_session"] = False
            combined = pd.concat([warmup, current], ignore_index=True)
            combined["timestamp"] = combined.timestamp.astype("int64")
            export.register("verified_candles", combined)
            export.execute(
                "COPY verified_candles TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)]
            )
    verify_results.HERE = HERE
    verify_results.main()


if __name__ == "__main__":
    main()
