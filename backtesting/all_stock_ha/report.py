"""Auditable ledger, marked-to-market metrics, calendar periods and offline UI."""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data import TZ


def metrics(curve, daily, trades, capital, previous=0.):
    curve=np.asarray(curve,dtype=float)
    if not len(curve):
        return {'trades':0,'status':'no_eligible_history'}
    equity=capital+curve
    peak=np.maximum.accumulate(np.r_[capital+previous,equity])[1:]
    dd=peak-equity
    exhausted=bool(np.any(equity<=0) or capital+previous<=0)
    daily=np.asarray(daily,dtype=float)
    denominators=capital+np.r_[previous,daily[:-1]]
    returns=np.diff(np.r_[previous,daily])/denominators if (denominators>0).all() else np.array([])
    sharpe=float(np.mean(returns)/np.std(returns,ddof=1)*np.sqrt(252)) if len(returns)>1 and np.std(returns,ddof=1)>0 and not exhausted else None
    pnl=trades.net_pnl.to_numpy() if len(trades) else np.array([])
    wins=pnl[pnl>0]; losses=pnl[pnl<0]
    return {'status':'capital_depleted_reference_only' if exhausted else 'evaluated',
            'trades':len(trades),'long_trades':int((trades.side=='LONG').sum()),
            'short_trades':int((trades.side=='SHORT').sum()),
            'gross_pnl':float(trades.gross_pnl.sum()),
            'costs':float(trades.entry_cost.sum()+trades.exit_cost.sum()),
            'net_pnl':float(curve[-1]-previous),
            'return_on_reference_pct':float((curve[-1]-previous)/capital*100),
            'reference_capital':capital,'max_drawdown_inr':float(dd.max()),
            'max_drawdown_pct':None if exhausted else float(np.max(dd/peak)*100),
            'win_rate_pct':float((pnl>0).mean()*100) if len(pnl) else None,
            'sharpe_daily_252_rf0':sharpe,
            'average_win':float(wins.mean()) if len(wins) else None,
            'average_loss':float(losses.mean()) if len(losses) else None,
            'profit_factor':float(wins.sum()/-losses.sum()) if len(losses) else None,
            'expectancy':float(pnl.mean()) if len(pnl) else None,
            'ambiguous_trades':int(trades.ambiguous.sum()),
            'average_holding_minutes':float((trades.exit_timestamp-trades.entry_timestamp).mean()/60) if len(trades) else None}


def daily_table(stamps,curve,occupied,fees,trades,capital):
    day=(np.asarray(stamps,dtype=np.int64)+19800)//86400
    days,starts,counts=np.unique(day,return_index=True,return_counts=True)
    ends=starts+counts-1
    pnl=curve[ends]
    daily=pd.DataFrame({'date':pd.to_datetime(days*86400,unit='s'),
                        'cumulative_pnl':pnl,'net_pnl':np.diff(np.r_[0.,pnl]),
                        'equity':capital+pnl,
                        'peak_notional':np.maximum.reduceat(occupied,starts),
                        'minimum_equity':np.minimum.reduceat(capital+curve,starts),
                        'fees':np.diff(np.r_[0.,fees[ends]])})
    # At intrabar resolution occupied retains the entry notional through exit.
    daily['funding_bound']=np.maximum.reduceat(np.maximum(0.,occupied-curve),starts)
    daily['trades']=0
    daily['entry_turnover']=0.
    if len(trades):
        entries=pd.to_datetime(trades.entry_timestamp,unit='s',utc=True).dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
        totals=trades.assign(date=entries).groupby('date').agg(trades=('quantity','size'),entry_turnover=('entry_notional','sum'))
        daily=daily.drop(columns=['trades','entry_turnover']).merge(totals,on='date',how='left').fillna({'trades':0,'entry_turnover':0})
    return daily


def period_tables(stamps,curve,trades,capital):
    session_days,session_starts,session_counts=np.unique((stamps+19800)//86400,return_index=True,return_counts=True)
    dates=pd.to_datetime(session_days*86400,unit='s')
    day=dates.normalize()
    year=dates.year.to_numpy()
    labels={'month':dates.strftime('%Y-%m'),
            'quarter':np.array([f'{y}-Q{q}' for y,q in zip(year,dates.quarter)]),
            'half_year':np.array([f'{y}-H{1 if m<=6 else 2}' for y,m in zip(year,dates.month)]),
            'year':year.astype(str),
            'five_year':np.array([f'{y//5*5}-{y//5*5+4}' for y in year]),
            'ten_year':np.array([f'{y//10*10}-{y//10*10+9}' for y in year])}
    exit_stamps=trades.exit_timestamp.to_numpy() if len(trades) else np.array([])
    records=[]
    for kind,keys in labels.items():
        values,starts,counts=np.unique(keys,return_index=True,return_counts=True)
        for label,session_start,count in zip(values,starts,counts):
            session_end=session_start+count
            start=session_starts[session_start]
            end=session_starts[session_end] if session_end<len(session_starts) else len(curve)
            selected=trades[(exit_stamps>=stamps[start]) & (exit_stamps<=stamps[end-1])]
            daily_ends=session_starts[session_start:session_end]+session_counts[session_start:session_end]-1
            m=metrics(curve[start:end],curve[daily_ends],selected,capital,curve[start-1] if start else 0.)
            years=5 if kind=='five_year' else 10 if kind=='ten_year' else 1
            if kind in ['five_year','ten_year']:
                start_year=int(str(label).split('-')[0])
                start_bound=pd.Timestamp(start_year,1,1)
                end_bound=pd.Timestamp(start_year+years,1,1)
            elif kind=='year':
                start_bound=pd.Timestamp(int(label),1,1);end_bound=pd.Timestamp(int(label)+1,1,1)
            elif kind=='half_year':
                start_bound=pd.Timestamp(int(str(label)[:4]),1 if str(label).endswith('1') else 7,1)
                end_bound=start_bound+pd.DateOffset(months=6)
            else:
                p=pd.Period(str(label).replace('-Q','Q'),freq='Q' if kind=='quarter' else 'M')
                start_bound=p.start_time;end_bound=p.end_time+pd.Timedelta(nanoseconds=1)
            # Boundary coverage only; session gaps are separately exposed in coverage.
            partial=day[0]>start_bound+pd.Timedelta(days=7) or day[-1]<end_bound-pd.Timedelta(days=7)
            records.append({'period_type':kind,'period':str(label),'start':str(day[session_start].date()),
                            'end':str(day[session_end-1].date()),'partial_window':bool(partial),
                            'coverage_note':'See excluded sessions; calendar boundaries alone do not prove completeness',**m})
    for years in [5,10]:
        threshold=day[-1]-pd.DateOffset(years=years)
        session_start=int(day.searchsorted(threshold))
        start=session_starts[session_start]
        selected=trades[exit_stamps>=stamps[start]]
        daily_ends=session_starts[session_start:]+session_counts[session_start:]-1
        m=metrics(curve[start:],curve[daily_ends],selected,capital,curve[start-1] if start else 0.)
        records.append({'period_type':f'trailing_{years}_year','period':f'last_{years}_years',
                        'start':str(day[session_start].date()),'end':str(day[-1].date()),
                        'partial_window':bool(day[0]>threshold),
                        'coverage_note':'partial history' if day[0]>threshold else 'See excluded sessions',**m})
    return pd.DataFrame(records)


def write_symbol(out,symbol,timeframe,raw,curve,occupied,fees,trades,capital):
    out.mkdir(parents=True,exist_ok=True)
    stamps=raw.timestamp.to_numpy()
    trades=trades.copy()
    trades.insert(0,'symbol',symbol)
    trades.insert(1,'timeframe',f'{timeframe}m')
    trades['trade_id']=np.arange(1,len(trades)+1)
    for name in ['signal','entry','exit']:
        trades[name+'_time_ist']=pd.to_datetime(trades[name+'_timestamp'],unit='s',utc=True).dt.tz_convert(TZ).astype(str)
    trades.to_csv(out/'trades.csv',index=False)
    daily=daily_table(stamps,curve,occupied,fees,trades,capital)
    daily.to_csv(out/'daily.csv',index=False)
    periods=period_tables(stamps,curve,trades,capital)
    periods.insert(0,'symbol',symbol)
    periods.insert(1,'timeframe',f'{timeframe}m')
    periods.to_csv(out/'periods.csv',index=False)
    m=metrics(curve,daily.cumulative_pnl,trades,capital)
    m.update(symbol=symbol,timeframe=f'{timeframe}m',
             peak_notional=float(occupied.max()),funding_bound=float(np.maximum(0.,occupied-curve).max()),
             eligible_sessions=len(daily),first_session=str(daily.date.iloc[0].date()),
             last_session=str(daily.date.iloc[-1].date()))
    # Buy/hold is a reference only: unadjusted prices and no dividends, before costs.
    q=int(capital//raw.open.iloc[0])
    benchmark=q*(raw.close.to_numpy()-raw.open.iloc[0])
    peak=np.maximum.accumulate(np.r_[capital,capital+benchmark])[1:]
    m['buy_hold_price_only_pnl']=float(benchmark[-1])
    m['buy_hold_price_only_max_dd_pct']=float(((peak-capital-benchmark)/peak*100).max())
    m['benchmark_note']='Same-stock unadjusted price-only buy/hold before costs; dividends/splits not verified. NIFTY benchmark unavailable unless supplied.'
    (out/'summary.json').write_text(json.dumps(m,indent=2,allow_nan=False),encoding='utf-8')
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,subplot_titles=['Daily cumulative net P&L','Daily reference-capital equity'])
    fig.add_trace(go.Scatter(x=daily.date,y=daily.cumulative_pnl,name='Net P&L'),row=1,col=1)
    fig.add_trace(go.Scatter(x=daily.date,y=daily.equity,name='Reference equity'),row=2,col=1)
    fig.update_layout(template='plotly_dark',height=650,title=f'{symbol} | {timeframe}m | INR 100,000 per trade')
    charts=fig.to_html(full_html=False,include_plotlyjs='../../plotly.min.js')
    body=f'<h1>{html.escape(symbol)} — {timeframe}m</h1><p>Entry/exit times identify one-minute execution bars, not exact ticks. Costs are illustrative. Charts below sample daily; drawdown metrics use minute close marks.</p>'
    body+='<p><a href="trades.csv">Trade ledger</a> · <a href="daily.csv">Daily capital/P&amp;L</a> · <a href="periods.csv">All period reports</a></p>'
    body+=pd.DataFrame([m]).T.to_html(header=False,escape=True)+charts+periods.to_html(index=False,escape=True)
    write_html(out/'report.html',body)
    return m,daily,periods


STYLE='body{background:#101620;color:#dde5ee;font:15px system-ui;margin:24px}a{color:#60caff}table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #334155;padding:7px;text-align:right}th{background:#1e293b;position:sticky;top:0}input{padding:10px;background:#1e293b;color:white;border:1px solid #64748b} .scroll{overflow:auto} h1{font-size:25px}'


def write_html(path,body):
    Path(path).write_text('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>'+STYLE+'</style></head><body>'+body+'</body></html>',encoding='utf-8')


def index_report(out,summary,coverage,manifest):
    shown=summary.copy()
    if not shown.empty:
        shown['report']=[f'<a href="{html.escape(str(s))}/{t}/report.html">Open</a>' for s,t in zip(shown.symbol,shown.timeframe)]
    body='<h1>All-stock HA / Bollinger / VWAP backtest</h1>'
    body+='<p>INR 100,000 fixed notional per trade. Independent stocks may hold positions concurrently. Results are candle-model estimates with illustrative costs; this is not a live strategy.</p>'
    body+='<p><a href="summary.csv">Stock results CSV</a> · <a href="coverage.csv">Coverage CSV</a> · <a href="all_periods.csv">Monthly through ten-year CSV</a> · <a href="research.csv">Research trials</a> · <a href="research_selection.csv">Walk-forward selection</a> · <a href="manifest.json">Assumptions/run manifest</a></p>'
    for tf in [1,5]:
        if (out/f'portfolio_{tf}m_daily.csv').exists():
            body+=f'<p>{tf}m portfolio: <a href="portfolio_{tf}m_daily.csv">Daily capital and P&amp;L</a> · <a href="portfolio_{tf}m_summary.json">Aggregate metrics</a></p>'
    body+='<p>Search stock: <input id="search" placeholder="Symbol"></p><div class="scroll">'
    columns=[x for x in ['symbol','timeframe','status','trades','net_pnl','max_drawdown_inr','max_drawdown_pct','win_rate_pct','sharpe_daily_252_rf0','funding_bound','eligible_sessions','report'] if x in shown]
    safe=shown[columns].copy()
    for col in safe.select_dtypes(include='object').columns:
        if col!='report':safe[col]=safe[col].map(lambda x:html.escape(str(x)))
    body+=safe.to_html(index=False,escape=False,table_id='results')+'</div>'
    body+='<h2>Coverage and exclusions</h2><p>Stocks with insufficient complete sessions or no raw history are listed here, not assigned fabricated zero returns.</p><div class="scroll">'+coverage.to_html(index=False,escape=True)+'</div>'
    body+='<script>document.querySelector("#search").oninput=function(){const q=this.value.toLowerCase();document.querySelectorAll("#results tbody tr").forEach(r=>r.hidden=!r.innerText.toLowerCase().includes(q));};</script>'
    write_html(out/'index.html',body)
