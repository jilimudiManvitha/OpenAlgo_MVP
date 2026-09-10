"""Compare preparation speed and independently reconcile with the saved backtest."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import statistics
import sys
import tempfile
from time import perf_counter

import numpy as np
import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stratagies"))
import ha_bb_vwap_strategy_astra as strategy
from polars_data import aggregate_pnl, export_heikin_ashi, prepare_historify


def legacy(csv, directory):
    source = pd.read_csv(csv)
    source.columns = source.columns.str.strip().str.lower()
    source["timestamp"] = pd.to_datetime(source.date + " " + source.time).dt.tz_localize(strategy.TZ)
    source["symbol"] = "ATHERENERG"
    if source.timestamp.duplicated().any(): raise ValueError("Duplicates")
    expected = list(range(555,930,5)); accepted = []
    now = pd.Timestamp.now(tz=strategy.TZ)
    for _, group in source.groupby(source.timestamp.dt.date):
        stamps = group.timestamp.sort_values()
        slots = (stamps.dt.hour * 60 + stamps.dt.minute).tolist()
        if slots == expected and stamps.dt.second.eq(0).all() and (stamps + strategy.FIVE <= now).all():
            accepted.append(group)
    path = directory / "validated_ohlcv.csv"
    pd.concat(accepted).sort_values("timestamp").to_csv(path, index=False)
    return strategy.read_candles(path)


def main():
    p=argparse.ArgumentParser();p.add_argument("--csv",type=Path,required=True);p.add_argument("--report-dir",type=Path,required=True)
    args=p.parse_args();out=args.report_dir
    timing={"pandas_seconds":[],"polars_seconds":[]}
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
        folder=Path(temp)
        # Alternate order to reduce systematic filesystem cache/order bias.
        for repeat in range(3):
            for name in (["pandas","polars"] if repeat%2==0 else ["polars","pandas"]):
                start=perf_counter()
                if name=="pandas": previous=legacy(args.csv,folder)
                else:
                    prepared=prepare_historify(args.csv);prepared.write(folder);current=prepared.to_strategy()
                timing[name+"_seconds"].append(perf_counter()-start)
    pd.testing.assert_frame_equal(previous,current,check_exact=False,rtol=1e-13,atol=1e-12)
    saved=json.loads((out/"summary.json").read_text())
    assert prepared.exclusions==saved["excluded_sessions"]
    cfg=strategy.Config(capital=100000.,volume_filter=False,breakout_source="high",exit_mode="bb_middle")
    old_indicators=strategy.indicators(previous,cfg)
    new_indicators=strategy.indicators(current,cfg)
    pd.testing.assert_frame_equal(old_indicators,new_indicators,check_exact=False,rtol=1e-12,atol=1e-10)
    with contextlib.redirect_stdout(io.StringIO()): result=strategy.simulate({"ATHERENERG":new_indicators},cfg)
    ledger=pd.read_csv(out/"trades.csv").drop(columns="trade_id")
    for c in ["signal_time","confirmation_time","entry_time","exit_time"]:
        ledger[c]=pd.to_datetime(ledger[c]).dt.tz_convert(strategy.TZ)
    pd.testing.assert_frame_equal(result,ledger,check_exact=False,rtol=1e-12,atol=1e-8)
    equity=pd.read_csv(out/"daily_pnl.csv")
    idx=pd.DatetimeIndex(pd.to_datetime(equity.date)).tz_convert(strategy.TZ)
    daily,monthly,by_exit=aggregate_pnl(result,pd.Series(equity.closing_equity.to_numpy(),index=idx),cfg.capital)
    for filename,new in [("daily_pnl.csv",daily),("monthly_pnl.csv",monthly),("exit_breakdown.csv",by_exit)]:
        old=pd.read_csv(out/filename,index_col=0)
        np.testing.assert_allclose(new.to_numpy(dtype=float),old.to_numpy(dtype=float),rtol=1e-12,atol=1e-8)
    export_heikin_ashi(new_indicators,out)
    med_old=statistics.median(timing["pandas_seconds"]);med_new=statistics.median(timing["polars_seconds"])
    report={"polars_version":pl.__version__,"source_rows":prepared.source_bars,"included_rows":len(current),
            "validation":"PASS: complete-session selection, OHLCV, all HA/indicators, 73 trade records, daily/monthly/exit P&L",
            "net_pnl":float(result.net_pnl.sum()),"timing":timing,"median_pandas_seconds":med_old,
            "median_polars_seconds":med_new,"preparation_speedup":med_old/med_new,
            "scope":"CSV load, timestamp parsing, validation, session filtering, normalized export and pandas conversion only; includes removing the old CSV reread. Not end-to-end backtest speed. Three alternating-order runs; no memory measurement."}
    (out/"polars_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
