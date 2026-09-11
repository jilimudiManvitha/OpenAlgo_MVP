"""Run: backtesting/.venv/Scripts/python.exe backtesting/all_stock_ha/run.py --help"""
from __future__ import annotations

import argparse
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd
from plotly.offline import get_plotlyjs

from data import ROOT,TZ,connect,init_catalog,ingest_csvs,complete_sessions,digest
from engine import Config,features,simulate,experiments
from report import write_symbol,daily_table,metrics,period_tables,index_report

HOME=Path(__file__).resolve().parent
DEFAULT_OUT=HOME/'results'


def atomic_json(path,value):
    tmp=Path(str(path)+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False,default=str),encoding='utf-8')
    tmp.replace(path)


def save_timeline(path,stamps,curve,occupied,fees):
    arrays={}
    for name,values in [('pnl',curve),('occupied',occupied),('fees',fees)]:
        delta=np.diff(np.r_[0.,values])
        nonzero=np.flatnonzero(delta)
        arrays[name+'_t']=stamps[nonzero]
        arrays[name+'_d']=delta[nonzero]
    np.savez_compressed(path,**arrays)


def research_stock(folder,raw,prepared,tf,base):
    stamps=raw.timestamp.to_numpy()
    days=(stamps+19800)//86400
    unique,starts,counts=np.unique(days,return_index=True,return_counts=True)
    arrays={'days':unique}
    rows=[]
    for name,candidate in experiments().items():
        cfg=replace(candidate,allocation=base.allocation,tick=base.tick,
                    rollover='rolling' if name=='rolling_continuation' else base.rollover)
        t,curve,occupied,fees=simulate(raw,prepared,tf,cfg)
        daily=daily_table(stamps,curve,occupied,fees,t,cfg.allocation)
        arrays[name+'_pnl']=daily.net_pnl.to_numpy()[20:]
        arrays[name+'_trades']=daily.trades.to_numpy()[20:]
        rows.append({'variant':name,**metrics(curve,daily.cumulative_pnl,t,cfg.allocation)})
    arrays['days']=unique[20:]
    pd.DataFrame(rows).to_csv(folder/'research_summary.csv',index=False)
    np.savez_compressed(folder/'research_daily.npz',**arrays)


def aggregate_research(out,symbols,capital):
    details=[]
    selections=[]
    for tf in [1,5]:
        by_variant={}
        count=0
        for symbol in symbols:
            folder=out/symbol/f'{tf}m'
            if not (folder/'research_daily.npz').exists():continue
            count+=1
            with np.load(folder/'research_daily.npz') as saved:
                dates=saved['days']
                for name in experiments():
                    frame=pd.DataFrame({'pnl':saved[name+'_pnl'],'trades':saved[name+'_trades']},index=dates)
                    by_variant[name]=by_variant[name].add(frame,fill_value=0) if name in by_variant else frame
        if not count:continue
        common=sorted(set().union(*(x.index for x in by_variant.values())))
        # Chronological development folds, then a final untouched 20% holdout.
        cuts=[int(len(common)*f) for f in [0.4,0.55,0.7,0.8,1.]]
        scored=[]
        for name,frame in by_variant.items():
            frame=frame.reindex(common,fill_value=0)
            for fold,(train_end,test_end) in enumerate(zip(cuts[:-1],cuts[1:]),1):
                for segment,lo,hi in [('train',0,train_end),('validation' if fold<4 else 'holdout',train_end,test_end)]:
                    part=frame.iloc[lo:hi]
                    pnl=part.pnl.to_numpy()
                    # Equal opportunity reference funding; same fixed denominator for every candidate.
                    returns=pnl/(capital*count)
                    sharpe=float(returns.mean()/returns.std(ddof=1)*np.sqrt(252)) if len(returns)>1 and returns.std(ddof=1)>0 else None
                    row={'timeframe':f'{tf}m','variant':name,'fold':fold,'segment':segment,
                         'start':str(pd.Timestamp(common[lo]*86400,unit='s').date()),
                         'end':str(pd.Timestamp(common[hi-1]*86400,unit='s').date()),
                         'net_pnl':float(pnl.sum()),'trades':int(part.trades.sum()),
                         'daily_fixed_capital_sharpe':sharpe,'reference_capital':capital*count}
                    scored.append(row)
        scores=pd.DataFrame(scored)
        details.extend(scored)
        excluded=['rolling_continuation','target_first_sensitivity','double_cost_stress']
        for fold in range(1,5):
            training=scores[(scores.fold==fold)&(scores.segment=='train')&(~scores.variant.isin(excluded))&(scores.trades>=30)]
            training=training.dropna(subset=['daily_fixed_capital_sharpe']).sort_values(['daily_fixed_capital_sharpe','variant'],ascending=[False,True])
            if training.empty:
                selections.append({'timeframe':f'{tf}m','fold':fold,'status':'insufficient_training_trades'})
                continue
            chosen=training.iloc[0].variant
            target=scores[(scores.fold==fold)&(scores.variant==chosen)&(scores.segment!='train')].iloc[0]
            selections.append({'timeframe':f'{tf}m','fold':fold,'selected_on':'training_only',
                               'variant':chosen,'evaluation_segment':target.segment,
                               'evaluation_net_pnl':target.net_pnl,'evaluation_trades':target.trades,
                               'evaluation_sharpe':target.daily_fixed_capital_sharpe,
                               'status':'evaluated_not_live_recommendation'})
    pd.DataFrame(details).to_csv(out/'research.csv',index=False)
    pd.DataFrame(selections).to_csv(out/'research_selection.csv',index=False)


def aggregate(out,symbols,coverage,manifest):
    summaries=[];periods=[]
    for symbol in symbols:
        for tf in [1,5]:
            folder=out/symbol/f'{tf}m'
            if not (folder/'done.json').exists():continue
            summaries.append(json.loads((folder/'summary.json').read_text()))
            periods.append(pd.read_csv(folder/'periods.csv'))
    summary=pd.DataFrame(summaries)
    if len(summary):summary=summary.sort_values(['timeframe','net_pnl'],ascending=[True,False])
    summary.to_csv(out/'summary.csv',index=False)
    pd.concat(periods,ignore_index=True).to_csv(out/'all_periods.csv',index=False) if periods else None
    coverage.to_csv(out/'coverage.csv',index=False)
    for tf in [1,5]:
        folders=[out/s/f'{tf}m' for s in symbols if (out/s/f'{tf}m'/'done.json').exists()]
        if not folders:continue
        low=int(manifest['first_timestamp']//60)
        high=int(manifest['last_timestamp']//60)+1
        deltas={k:np.zeros(high-low+2) for k in ['pnl','occupied','fees']}
        trade_parts=[]
        day_parts=[]
        for folder in folders:
            with np.load(folder/'timeline.npz') as saved:
                for name in deltas:
                    idx=saved[name+'_t']//60-low
                    np.add.at(deltas[name],idx,saved[name+'_d'])
            trade_parts.append(pd.read_csv(folder/'trades.csv'))
            day_parts.append(pd.read_csv(folder/'daily.csv',usecols=['date']))
        stamps=np.arange(low,high+2,dtype=np.int64)*60
        observed=pd.concat(day_parts).date.unique()
        observed_days=pd.DatetimeIndex(observed).as_unit('s').asi8//86400
        day=(stamps+19800)//86400
        slots=(stamps//60+330)%1440
        mask=np.isin(day,observed_days)&(slots>=555)&(slots<930)
        values={k:np.cumsum(v)[mask] for k,v in deltas.items()}
        capital=manifest['config']['allocation']*len(folders)
        trades=pd.concat(trade_parts,ignore_index=True)
        daily=daily_table(stamps[mask],values['pnl'],values['occupied'],values['fees'],trades,capital)
        daily['peak_concurrent_positions_bound']=np.ceil(daily.peak_notional/manifest['config']['allocation'])
        # Exact count bound uses each trade's bar intervals, not fractional allocations.
        pos=np.zeros(len(stamps))
        if len(trades):
            np.add.at(pos,trades.entry_timestamp.to_numpy(dtype=np.int64)//60-low,1)
            np.add.at(pos,trades.exit_timestamp.to_numpy(dtype=np.int64)//60-low+1,-1)
        pos=np.cumsum(pos)[mask]
        _,starts=np.unique(day[mask],return_index=True)
        daily['peak_concurrent_positions_bound']=np.maximum.reduceat(pos,starts).astype(int)
        daily.to_csv(out/f'portfolio_{tf}m_daily.csv',index=False)
        m=metrics(values['pnl'],daily.cumulative_pnl,trades,capital)
        m.update(stocks=len(folders),peak_notional_bound=float(values['occupied'].max()),
                 funding_bound=float(np.maximum(0.,values['occupied']-values['pnl']).max()),
                 capital_note='Full-notional collateral, no leverage. Intrabar overlap is a conservative one-minute bound; reference equity uses 100000 per evaluated stock. Financing and broker margin not modeled.')
        atomic_json(out/f'portfolio_{tf}m_summary.json',m)
        period_tables(stamps[mask],values['pnl'],trades,capital).to_csv(out/f'portfolio_{tf}m_periods.csv',index=False)
    aggregate_research(out,symbols,manifest['config']['allocation'])
    index_report(out,summary,coverage,manifest)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['catalog','run','report'])
    parser.add_argument('--historify',type=Path,default=ROOT/'db/historify.duckdb')
    parser.add_argument('--catalog',type=Path,default=HOME/'research.duckdb')
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--symbols',nargs='+')
    parser.add_argument('--research',action='store_true')
    parser.add_argument('--rollover',choices=['rolling','fresh'],default='fresh')
    parser.add_argument('--tick',type=float,default=0.01)
    parser.add_argument('--csv-root',type=Path,action='append')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    with connect(args.catalog) as catalog:
        init_catalog(catalog)
        if args.command=='catalog':
            roots=args.csv_root or [ROOT/'stock_symbols_CSVs',ROOT/'backtesting',ROOT/'data',ROOT.parent/'CSVs',ROOT.parent/'historify_ATHERENERG_20260908_112029']
            frame=ingest_csvs(catalog,roots)
            frame.to_csv(args.out/'csv_catalog.csv',index=False)
            print(frame.groupby(['kind','status']).agg(files=('path','size'),rows=('rows','sum')).to_string(),flush=True)
            return
    if args.command=='report':
        manifest=json.loads((args.out/'manifest.json').read_text())
        coverage=pd.read_csv(args.out/'coverage.csv')
        summary=aggregate(args.out,manifest['symbols'],coverage,manifest)
        print(f'Report rebuilt: {len(summary)} stock/timeframe results',flush=True)
        return
    cfg=Config(rollover=args.rollover,tick=args.tick)
    cfg.validate()
    with connect(args.historify,readonly=True) as source:
        source.execute('BEGIN TRANSACTION')
        catalog=source.execute("SELECT symbol,exchange,interval,first_timestamp,last_timestamp,record_count FROM data_catalog WHERE exchange='NSE' AND interval='1m' ORDER BY symbol").fetchdf()
        if args.symbols:
            catalog=catalog[catalog.symbol.isin(args.symbols)]
            missing=set(args.symbols)-set(catalog.symbol)
            if missing:raise ValueError(f'No source history for requested symbols: {sorted(missing)}')
        if catalog.empty:raise ValueError('No NSE one-minute data available')
        catalog.to_csv(args.out/'source_coverage.csv',index=False)
        original=ROOT/'backtesting/stratagies/ha_bb_vwap_strategy_astra.py'
        fingerprint={p.name:digest(p) for p in HOME.glob('*.py') if not p.name.startswith('test_')}
        manifest={'config':asdict(cfg),'symbols':catalog.symbol.tolist(),
                  'first_timestamp':int(catalog.first_timestamp.min()),'last_timestamp':int(catalog.last_timestamp.max()),
                  'source_path':str(args.historify.resolve()),'source_bytes':args.historify.stat().st_size,
                  'source_catalog_sha256':hashlib.sha256(catalog.to_csv(index=False).encode()).hexdigest(),
                  'original_strategy_sha256':digest(original),'implementation':fingerprint,
                  'research':args.research,'snapshot':'read-only DuckDB transaction; catalog fingerprint and source stat recorded',
                  'assumptions':['Real 1m execution bars; completed 1m HLC3 VWAP at entry; intrabar ordering approximate',
                                 'HA BB(20,2), population deviation; volume >=2x prior 20 complete-session mean',
                                 'One stock position at a time; unlimited subsequent trades; no global position cap',
                                 ('Fresh inside-to-outside band crossings' if cfg.rollover=='fresh' else 'Rolling eligible outside-band signal replacement') + '; completed confirmation filters replaced by real price trigger',
                                 '09:20 through before 15:20 entry; 15:20 square-off; 0.01 original tick default is configurable, not verified per-stock historical tick',
                                 '5 bps fees per side and 5 bps slippage illustrative; no broker-specific fee/tax claim',
                                 'Only complete regular sessions; gaps excluded; HA recurses over retained history; 20 retained prior sessions for volume warmup',
                                 'Unadjusted source prices; corporate actions and point-in-time universe not verified; survivorship risk',
                                 'Reference equity can deplete; all-opportunity P&L requires replenishment/funding; no constrained portfolio replay',
                                 'No verified NIFTY benchmark provided; price-only same-stock buy/hold shown',
                                 '5/10-year output reports actual available coverage, never extrapolated']}
        run_id=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        manifest['run_id']=run_id
        existing=args.out/'manifest.json'
        if existing.exists() and json.loads(existing.read_text())['run_id']!=run_id:
            raise ValueError('Run inputs/code changed: choose a new --out directory to preserve reproducibility')
        atomic_json(existing,manifest)
        (args.out/'plotly.min.js').write_text(get_plotlyjs(),encoding='utf-8')
        (args.out/'original_strategy.py').write_bytes(original.read_bytes())
        with connect(args.catalog) as research_db:
            research_db.execute('INSERT OR REPLACE INTO backtest_runs VALUES (?,?,?)',[run_id,json.dumps(manifest),'running'])
        coverage=[]
        for index,row in enumerate(catalog.itertuples(),1):
            started=time.perf_counter()
            folder=args.out/row.symbol
            folder.mkdir(exist_ok=True)
            if (folder/'coverage.json').exists() and all((folder/f'{tf}m'/'done.json').exists() for tf in [1,5]):
                coverage.append(json.loads((folder/'coverage.json').read_text()))
                print(f'[{index}/{len(catalog)}] {row.symbol}: resumed',flush=True)
                continue
            raw=source.execute("SELECT timestamp,open,high,low,close,volume FROM market_data WHERE symbol=? AND exchange='NSE' AND interval='1m' ORDER BY timestamp",[row.symbol]).fetchdf()
            valid,sessions=complete_sessions(raw)
            sessions.to_csv(folder/'sessions.csv',index=False)
            cov={'symbol':row.symbol,'source_rows':len(raw),'valid_rows':len(valid),
                 'source_sessions':len(sessions),'valid_sessions':int(sessions.valid_session.sum()),
                 'excluded_sessions':int((~sessions.valid_session).sum()),
                 'eligible_sessions':max(0,int(sessions.valid_session.sum())-20),
                 'status':'evaluated' if len(valid)>20*375 else 'insufficient_complete_sessions'}
            atomic_json(folder/'coverage.json',cov)
            coverage.append(cov)
            pd.DataFrame(coverage).to_csv(args.out/'coverage.csv',index=False)
            if len(valid)<=20*375:
                print(f'[{index}/{len(catalog)}] {row.symbol}: {cov["status"]}',flush=True)
                continue
            for tf in [1,5]:
                dest=folder/f'{tf}m'
                if (dest/'done.json').exists():continue
                prepared=features(valid,tf)
                trades,curve,occupied,fees=simulate(valid,prepared,tf,cfg)
                # Warmup data initializes indicators but is not scored as trading history.
                warmup=20*375
                scored=valid.iloc[warmup:].reset_index(drop=True)
                m,daily,periods=write_symbol(dest,row.symbol,tf,scored,curve[warmup:],occupied[warmup:],fees[warmup:],trades,cfg.allocation)
                save_timeline(dest/'timeline.npz',scored.timestamp.to_numpy(),curve[warmup:],occupied[warmup:],fees[warmup:])
                if args.research:
                    research_stock(dest,valid,prepared,tf,cfg)
                atomic_json(dest/'done.json',{'run_id':run_id,'trades':len(trades)})
            print(f'[{index}/{len(catalog)}] {row.symbol}: {cov["valid_sessions"]} complete sessions, {time.perf_counter()-started:.1f}s',flush=True)
        source.execute('COMMIT')
    coverage=pd.DataFrame(coverage)
    summary=aggregate(args.out,catalog.symbol.tolist(),coverage,manifest)
    with connect(args.catalog) as research_db:
        research_db.execute('UPDATE backtest_runs SET status=? WHERE run_id=?',['complete_available_data',run_id])
    print(f'Completed {len(summary)} stock/timeframe results: {args.out / "index.html"}',flush=True)


if __name__=='__main__':
    main()
