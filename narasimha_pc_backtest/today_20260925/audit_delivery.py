"""Persist selection/accounting/source identity checks without broker calls."""

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    selection = json.loads((HERE / "selection.json").read_text())
    manifest = json.loads((HERE / "output/manifest.json").read_text())
    original = json.loads((HERE.parent / "output/manifest.json").read_text())
    assert len(selection["volume_shockers"]) == len(selection["top_gainers"]) == 50
    assert len(set(selection["symbols"])) == 80
    for row in selection["volume_shockers"]:
        assert len(row["baseline_dates"]) == 5
        assert all(day < "2026-09-25" for day in row["baseline_dates"])
        assert abs(row["volume"] / row["average_volume"] - row["rvol"]) < 1e-9
        assert row["rvol"] > 1
    for row in selection["top_gainers"]:
        assert row["change_percent"] > 0
        assert abs((row["ltp"] / row["previous_close"] - 1) * 100 - row["change_percent"]) < 1e-9
    rows = []
    for group in ["volume_shockers", "top_gainers"]:
        for rank, row in enumerate(selection[group], 1):
            rows.append(
                {
                    "group": group,
                    "rank": rank,
                    **{
                        key: row.get(key)
                        for key in [
                            "symbol",
                            "ltp",
                            "change_percent",
                            "rvol",
                            "volume",
                            "average_volume",
                            "quote_fetched_at",
                            "last_trade_at",
                        ]
                    },
                }
            )
    pd.DataFrame(rows).to_csv(HERE / "selection_table.csv", index=False)
    trades = pd.read_csv(HERE / "output/trades.csv")
    assert set(trades.date) == {"2026-09-25"}
    a = trades[trades.path == "OLHC"].sort_values("symbol").reset_index(drop=True)
    b = trades[trades.path == "OHLC"].sort_values("symbol").reset_index(drop=True)
    pd.testing.assert_frame_equal(
        a[["symbol", "entry", "exit", "quantity", "net_pnl"]],
        b[["symbol", "entry", "exit", "quantity", "net_pnl"]],
    )
    for filename in ["engine.py", "run.py"]:
        assert digest(HERE.parent / filename) == original["code_sha256"][filename]
    assert digest(HERE / "candles.duckdb") == manifest["source_sha256"]
    ledger_check = json.loads((HERE / "output/verification.json").read_text())
    browser_check = json.loads((HERE / "artifacts/browser.json").read_text())
    assert ledger_check["status"] == browser_check["status"] == "PASSED"
    report = {
        "status": "PASSED",
        "checks": [
            "selected-row gain/RVOL calculations",
            "five baseline dates precede session",
            "50+50 selections,80 unique",
            "today-only ledger",
            "path fill equality",
            "original strategy engine and runner unchanged",
            "isolated source SHA unchanged",
            "independent ledger verification",
            "browser report verification",
        ],
        "selection_limit": "Global ranks derive from the saved scanner snapshot; the complete universe was not independently archived at selection time",
        "paper_status": "Prepared; authenticated upload and session execution require separate verification",
        "files_sha256": {p.name: digest(p) for p in HERE.glob("*.py")},
    }
    (HERE / "artifacts/delivery.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": report["status"], "trades_checked": len(trades), "selected": 80}))


if __name__ == "__main__":
    main()
