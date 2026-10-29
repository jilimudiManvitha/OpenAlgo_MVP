"""Reconcile exported option backtests against ledgers, final marks and source hashes."""

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

from .history import atomic_json, cache_file, read_candles
from .profiles import PROFILES, ROOT


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(v for k, v in attrs if k == "href")


def verify(folder):
    folder = Path(folder)
    metadata = json.loads((folder / "verification.json").read_text())
    summaries = json.loads((folder / "summary.json").read_text())
    keys = {(s["strategy"], s["path"]) for s in summaries}
    assert keys == {(k, p) for k in PROFILES for p in metadata["paths"]}
    assert len(keys) == len(summaries)
    manifest_path = (
        ROOT / metadata["manifest_file"]
        if metadata.get("manifest_file")
        else folder.parent / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    contracts = {c["symbol"]: c for c in manifest["contracts"]}
    calendar = json.loads((folder / "calendar.json").read_text())
    rows_checked = 0
    for summary in summaries:
        path = folder / summary["path"] / summary["strategy"]
        state = json.loads((path / "state.json").read_text())
        trades = pd.read_csv(path / "trades.csv") if summary["closed_legs"] else pd.DataFrame()
        curve = pd.read_csv(path / "equity.csv")
        assert np.isfinite(curve["equity"]).all()
        assert pd.to_datetime(curve["timestamp"]).is_monotonic_increasing
        assert not curve["timestamp"].duplicated().any()
        assert len(set(curve["timestamp"].str[:10])) == len(calendar["sessions"])
        closed_net = float(trades["net_pnl"].sum()) if not trades.empty else 0.0
        open_fees = sum(leg["entry_fee"] for leg in state["legs"])
        assert abs(closed_net - open_fees - state["total_realized"]) < 0.01
        fees = (
            float(trades["entry_fee"].sum() + trades["exit_fee"].sum()) if not trades.empty else 0.0
        )
        assert abs(fees + open_fees - state["fees"]) < 0.01
        unrealized = 0.0
        for leg in state["legs"]:
            c = contracts[leg["symbol"]]
            candles = read_candles(cache_file(c["symbol"], c["start"], c["end"]))["candles"]
            final_bar = int(pd.Timestamp(curve["timestamp"].iloc[-1]).timestamp()) - 60
            last = [r for r in candles if r["timestamp"] == final_bar][-1]
            unrealized += (last["close"] - leg["entry"]) * leg["quantity"] * leg["side"]
        assert abs(state["total_realized"] + unrealized - summary["net_pnl"]) < 0.01
        assert abs(curve["equity"].iloc[-1] - summary["capital"] - summary["net_pnl"]) < 0.01
        values = pd.Series([summary["capital"], *curve["equity"].tolist()])
        assert abs((values - values.cummax()).min() - summary["max_drawdown_inr"]) < 0.01
        if not trades.empty:
            assert trades["symbol"].str.startswith("NSE:NIFTY").all()
            assert (trades["quantity"] % trades["lot_size"] == 0).all()
            assert (
                pd.to_datetime(trades["exit_ts"], format="ISO8601")
                >= pd.to_datetime(trades["entry_ts"], format="ISO8601")
            ).all()
            for _, entry in trades.groupby(["cycle", "entry_ts"]):
                assert entry["quantity"].nunique() == 1
            recalculated = (
                (trades["exit"] - trades["entry"]) * trades["side"] * trades["quantity"]
                - trades["entry_fee"]
                - trades["exit_fee"]
            )
            assert np.allclose(recalculated, trades["net_pnl"], atol=0.001)
        rows_checked += len(trades)
    for filename, digest in metadata["source_hashes"].items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest, filename
    for filename, digest in metadata["code_hashes"].items():
        assert hashlib.sha256((folder / "source" / filename).read_bytes()).hexdigest() == digest, (
            filename
        )
    parser = Links()
    parser.feed((folder / "index.html").read_text())
    local = [url for url in parser.links if not url.startswith(("http", "#", "data:"))]
    assert all((folder / url).is_file() for url in local)
    result = {
        "passed": True,
        "variants": len(summaries),
        "closed_leg_rows_checked": rows_checked,
        "source_files_hashed": len(metadata["source_hashes"]),
        "local_links_checked": len(local),
        "trading_sessions": len(calendar["sessions"]),
        "checks": "Exported cash flow, fees, final source marks, drawdown, chronological whole-lot fills, source integrity and local links. Simulation assumptions remain estimates.",
    }
    atomic_json(folder / "ledger_verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    print(json.dumps(verify(parser.parse_args().folder), indent=2))
