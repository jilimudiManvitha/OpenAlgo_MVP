"""Replay the unchanged parent strategy against the frozen scanner basket."""

import json
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run as original


def main():
    selection = json.loads((HERE / "selection.json").read_text(encoding="utf-8"))
    source = HERE / "candles.duckdb"
    out = HERE / "output"
    if source.exists() or out.exists():
        raise ValueError("Preserve existing run: source/output already exists")
    frames = []
    fetched = {}
    for symbol in selection["symbols"]:
        item = json.loads((HERE / "downloads" / f"{symbol}.json").read_text())
        frame = pd.DataFrame(
            item["candles"], columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        if frame.empty or frame.timestamp.duplicated().any():
            raise ValueError(f"Empty or duplicate source: {symbol}")
        frame["symbol"], frame["exchange"], frame["interval"] = symbol, "NSE", "1m"
        frames.append(frame)
        fetched[symbol] = item["fetched_at"]
    combined = pd.concat(frames, ignore_index=True)
    with duckdb.connect(str(source)) as db:
        db.register("candles", combined)
        db.execute("CREATE TABLE market_data AS SELECT * FROM candles")
        db.execute("CHECKPOINT")
    out.mkdir()
    for name in ["candles", "ledgers", "coverage", "rejected"]:
        (out / name).mkdir()
    cfg = {
        "strategy": "BUY_HA1m_BB20x2_VWAP_NoLowerWick_SLsignalLowMinus0.10_TP3R_OnePerDay",
        "source": str(source),
        "start": selection["date"],
        "end": selection["date"],
        "symbols": selection["symbols"],
        "capital": 100000,
        "rr": 3,
        "stop_offset": 0.10,
        "fee_bps": 5,
        "slippage_bps": 5,
        "steps": 32,
        "workers": 1,
        "asof_timestamp": int(time.time()),
        "metadata": original.metadata(selection["symbols"]),
        "selection": {
            k: selection[k]
            for k in ["selected_at", "snapshot_updated_at", "selection_bias", "limit_per_group"]
        },
    }
    manifest = {
        "status": "RUNNING",
        "config": cfg,
        "source_sha256": original.digest(source),
        "code_sha256": {
            p.name: original.digest(p)
            for p in [HERE.parent / "engine.py", HERE.parent / "run.py", Path(__file__)]
        },
        "selection_sha256": original.digest(HERE / "selection.json"),
        "fetched_at": fetched,
    }
    started = time.perf_counter()
    try:
        audits = []
        with original.connect(source):
            for symbol in cfg["symbols"]:
                audits.append(original.worker(symbol, cfg, cfg["metadata"][symbol], out))
            summary = original.summarize(out, cfg, audits)
            assert original.digest(source) == manifest["source_sha256"]
        trades = pd.read_csv(out / "trades.csv")
        coverage = pd.read_csv(out / "coverage.csv")
        groups = []
        for group in ["volume_shockers", "top_gainers", "deduplicated_union"]:
            symbols = (
                set(cfg["symbols"])
                if group == "deduplicated_union"
                else {r["symbol"] for r in selection[group]}
            )
            for path in ["OLHC", "OHLC"]:
                f = trades[trades.symbol.isin(symbols) & trades.path.eq(path)]
                groups.append(
                    {
                        "group": group,
                        "path": path,
                        "selected": len(symbols),
                        "eligible": int(
                            (coverage.symbol.isin(symbols) & coverage.status.eq("ELIGIBLE")).sum()
                        ),
                        "trades": len(f),
                        "wins": int(f.net_pnl.gt(0).sum()),
                        "gross_pnl": float(f.gross_pnl.sum()),
                        "fees": float(f.fees.sum()),
                        "net_pnl": float(f.net_pnl.sum()),
                    }
                )
        pd.DataFrame(groups).to_csv(out / "group_summary.csv", index=False)
        html_path = out / "index.html"
        html = html_path.read_text(encoding="utf-8").replace("Nifty 50", "25 Sep scanner basket")
        notice = f'<div class="notice">Selection: {selection["selected_at"]}. Top 50 volume shockers and top 50 gainers; overlap counted once in the union. This is a retrospective basket test: the afternoon selection was not known for morning entries. Incomplete sessions are excluded. Group results are in group_summary.csv. No live deployment decision follows from this single session.</div>'
        html_path.write_text(
            html.replace(
                '<div class="notice" id="coverage">', notice + '<div class="notice" id="coverage">'
            ),
            encoding="utf-8",
        )
        manifest.update(
            status="COMPLETE_AVAILABLE_DATA",
            audits=audits,
            summary=summary,
            groups=groups,
            seconds=time.perf_counter() - started,
        )
        print(
            json.dumps(
                {
                    "summary": summary,
                    "groups": groups,
                    "coverage": coverage.status.value_counts().to_dict(),
                },
                indent=2,
            )
        )
    except BaseException as exc:
        manifest.update(status="FAILED_OR_INTERRUPTED", error=str(exc))
        raise
    finally:
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    from verify_today import main as verify

    verify()
    from finish_report import main as finish

    finish()


if __name__ == "__main__":
    main()
