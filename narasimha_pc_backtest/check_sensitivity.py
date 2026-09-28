"""Check whether 4x denser intrabar entry sampling materially changes this run."""

import json

import duckdb
import numpy as np
import pandas as pd
from engine import replay
from run import HA_COLS, HERE


def main():
    out = HERE / "output"
    manifest = json.loads((out / "manifest.json").read_text())
    cfg = manifest["config"]
    comparisons = []
    with duckdb.connect(config={"threads": 2, "memory_limit": "1GB"}) as db:
        for symbol in cfg["symbols"]:
            data = db.execute(
                "SELECT * FROM read_parquet(?) ORDER BY timestamp",
                [str(out / "candles" / f"{symbol}.parquet")],
            ).fetchdf()
            raw = np.ascontiguousarray(
                data[["timestamp", "open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
            )
            ha = np.ascontiguousarray(data[HA_COLS].to_numpy())
            allowed = data.eligible_session.to_numpy()
            original = pd.read_csv(out / "ledgers" / f"{symbol}.csv")
            meta = cfg["metadata"][symbol]
            for path_id, path in enumerate(["OLHC", "OHLC"]):
                refined = replay(
                    raw,
                    ha,
                    allowed,
                    905 if meta["is_fo"] else 920,
                    path_id,
                    meta["tick"],
                    cfg["slippage_bps"] / 10000,
                    cfg["fee_bps"] / 10000,
                    float(cfg["capital"]),
                    float(cfg["rr"]),
                    cfg["stop_offset"],
                    128,
                )
                f = original[original.path == path]
                same_signals = len(f) == len(refined) and np.array_equal(
                    f.signal_ts.to_numpy(), refined[:, 0]
                )
                same_fills = same_signals and np.allclose(
                    f[["entry", "exit", "quantity", "stop", "target", "net_pnl"]].to_numpy(),
                    refined[:, [3, 4, 5, 6, 7, 10]],
                    rtol=0,
                    atol=1e-6,
                )
                comparisons.append(
                    {
                        "symbol": symbol,
                        "path": path,
                        "original_trades": len(f),
                        "refined_trades": len(refined),
                        "same_signals": bool(same_signals),
                        "same_fills": bool(same_fills),
                        "net_pnl_difference": float(refined[:, 10].sum() - f.net_pnl.sum()),
                    }
                )
    result = {
        "entry_samples_per_leg": [32, 128],
        "comparisons": comparisons,
        "changed_symbol_paths": sum(not c["same_fills"] for c in comparisons),
        "note": "Sampling sensitivity check, not proof of exact tick reconstruction.",
    }
    (out / "sampling-sensitivity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "comparisons"}))


if __name__ == "__main__":
    main()
