"""Independent vectorized source/entry/accounting verification of saved ledgers."""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from run import HERE, digest


def main():
    out = HERE / "output"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "COMPLETE_AVAILABLE_DATA"
    cfg = manifest["config"]
    ledger = pd.read_csv(out / "trades.csv")
    assert not ledger.duplicated(["path", "symbol", "date"]).any()
    assert (ledger.notional <= 100000 + 1e-7).all()
    assert (ledger.quantity == np.floor(ledger.quantity)).all()
    assert (ledger.entry_ts >= ledger.signal_ts + 60).all()
    assert (ledger.entry_ts <= ledger.signal_ts + 120).all()
    assert (ledger.exit_ts >= ledger.entry_ts).all()
    np.testing.assert_allclose(
        ledger.gross_pnl, (ledger.exit - ledger.entry) * ledger.quantity, atol=1e-7
    )
    np.testing.assert_allclose(
        ledger.fees,
        (ledger.exit + ledger.entry) * ledger.quantity * cfg["fee_bps"] / 10000,
        atol=1e-7,
    )
    np.testing.assert_allclose(ledger.net_pnl, ledger.gross_pnl - ledger.fees, atol=1e-7)
    np.testing.assert_allclose(
        ledger.raw_reference_pnl - ledger.slippage_cost, ledger.gross_pnl, atol=1e-6
    )
    counts = {}
    with duckdb.connect(config={"threads": 2, "memory_limit": "1GB"}) as db:
        for symbol in cfg["symbols"]:
            data = db.execute(
                "SELECT * FROM read_parquet(?) ORDER BY timestamp",
                [str(out / "candles" / f"{symbol}.parquet")],
            ).fetchdf()
            f = ledger[ledger.symbol == symbol]
            ix = np.searchsorted(data.timestamp.to_numpy(), f.signal_ts.to_numpy())
            s = data.iloc[ix].reset_index(drop=True)
            e = data.iloc[ix + 1].reset_index(drop=True)
            f = f.reset_index(drop=True)
            assert np.all(s.timestamp.to_numpy() == f.signal_ts.to_numpy())
            assert np.all(e.timestamp.to_numpy() == f.signal_ts.to_numpy() + 60)
            assert e.eligible_session.all()
            assert np.all(s.ha_low >= s.ha_open - 1e-9)
            assert np.all(s.ha_close > s.ha_open)
            assert np.all(s.ha_high > s.bb_upper)
            assert np.all(s.ha_high > s.vwap)
            # Independent forming snapshot reconstructed from the selected raw path.
            elapsed = np.maximum(0.0, f.entry_ts.to_numpy() - e.timestamp.to_numpy())
            progress = np.clip(elapsed / 20, 0, 3)
            vertices = np.column_stack(
                [
                    e.open,
                    np.where(f.path == "OLHC", e.low, e.high),
                    np.where(f.path == "OLHC", e.high, e.low),
                    e.close,
                ]
            )
            leg = np.minimum(2, np.floor(progress).astype(int))
            frac = progress - leg
            rows = np.arange(len(f))
            p = f.entry_reference.to_numpy()
            expected = vertices[rows, leg] + (vertices[rows, leg + 1] - vertices[rows, leg]) * frac
            np.testing.assert_allclose(p, expected, rtol=0, atol=0.0001)
            highs, lows = np.maximum(e.open.to_numpy(), p), np.minimum(e.open.to_numpy(), p)
            for j in [1, 2]:
                highs = np.where(leg >= j, np.maximum(highs, vertices[:, j]), highs)
                lows = np.where(leg >= j, np.minimum(lows, vertices[:, j]), lows)
            hc = (e.open.to_numpy() + highs + lows + p) / 4
            assert np.all(lows >= e.ha_open.to_numpy() - 1e-7)
            assert np.all(hc >= e.ha_open.to_numpy() - 1e-7)
            assert np.all(p >= s.ha_high.to_numpy() - 1e-7)
            windows = data.ha_close.to_numpy()[(ix + 1)[:, None] + np.arange(-19, 0)]
            windows = np.column_stack([windows, hc])
            upper = windows.mean(axis=1) + 2 * windows.std(axis=1, ddof=0)
            assert np.all(p >= upper - 1e-7)
            dates = ((data.timestamp + 19800) // 86400).astype(int)
            volumes = data.volume.groupby(dates).cumsum().to_numpy()
            pv = (
                (((data.high + data.low + data.close) / 3) * data.volume)
                .groupby(dates)
                .cumsum()
                .to_numpy()
            )
            cv = e.volume.to_numpy() * elapsed / 60
            vw = (pv[ix] + (highs + lows + p) / 3 * cv) / (volumes[ix] + cv)
            assert np.all(p >= vw - 1e-6)
            tick = cfg["metadata"][symbol]["tick"]
            slip = cfg["slippage_bps"] / 10000
            np.testing.assert_allclose(
                f.entry, np.ceil((p * (1 + slip) - 1e-10) / tick) * tick, atol=1e-7
            )
            np.testing.assert_allclose(
                f.stop, np.floor((s.ha_low - 0.10 + 1e-10) / tick) * tick, atol=1e-7
            )
            np.testing.assert_allclose(
                f.target,
                np.ceil((f.entry + 3 * (f.entry - f.stop) - 1e-10) / tick) * tick,
                atol=1e-7,
            )
            np.testing.assert_allclose(
                f.exit,
                np.where(
                    f.reason == "TARGET",
                    f.exit_reference,
                    np.floor((f.exit_reference * (1 - slip) + 1e-10) / tick) * tick,
                ),
                atol=1e-7,
            )
            exits = np.minimum(
                np.searchsorted(data.timestamp.to_numpy(), f.exit_ts, side="right") - 1,
                len(data) - 1,
            )
            # Exact next-minute open belongs to the next bar; all references still in range.
            x = data.iloc[exits].reset_index(drop=True)
            regular_exit = f.reason != "TARGET"
            assert np.all(
                f.loc[regular_exit, "exit_reference"] >= x.loc[regular_exit, "low"] - 1e-6
            )
            assert np.all(
                f.loc[regular_exit, "exit_reference"] <= x.loc[regular_exit, "high"] + 1e-6
            )
            assert np.all(
                f.loc[f.reason == "TARGET", "exit_reference"]
                == f.loc[f.reason == "TARGET", "target"]
            )
            cutoff = 905 if cfg["metadata"][symbol]["is_fo"] else 920
            sq = f[f.reason == "SQUARE_OFF"]
            assert np.all((sq.exit_ts + 19800) % 86400 == cutoff * 60)
            assert np.all((f.exit_ts + 19800) % 86400 <= cutoff * 60 + 1e-6)
            counts[symbol] = len(f)
    daily = pd.read_csv(out / "daily.csv")
    for summary in manifest["summary"]:
        path = summary["path"]
        f, d = ledger[ledger.path == path], daily[daily.path == path]
        assert len(f) == summary["trades"]
        np.testing.assert_allclose(
            [f.net_pnl.sum(), d.net_pnl.sum()], summary["net_pnl"], atol=1e-6
        )
    with duckdb.connect(cfg["source"], read_only=True):
        assert digest(Path(cfg["source"])) == manifest["source_sha256"]
    result = {
        "status": "PASSED",
        "trades_checked": len(ledger),
        "symbols": counts,
        "checks": [
            "one trade per symbol/day/path",
            "capital cap",
            "completed signal conditions",
            "immediate next minute",
            "forming HA wick / BB / VWAP",
            "modeled price/time",
            "tick-rounded fills and 3R target",
            "exit price range and cutoff",
            "fees, slippage, P&L and daily totals",
            "source SHA-256 unchanged",
        ],
        "limits": "Not an independent reconstruction of the earliest exit on every price path; synthetic tests cover exit ordering.",
    }
    (out / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"status": result["status"], "trades_checked": len(ledger), "symbols": len(counts)}
        )
    )


if __name__ == "__main__":
    main()
