"""Plot the existing trade ledger; do not rerun or change the backtest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from plotly.offline import get_plotlyjs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stratagies"))
import ha_bb_vwap_strategy_astra as strategy


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ATHERENERG | Executed trades</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#e2e8f0;font:14px system-ui,sans-serif}
header,main{max-width:1500px;margin:auto;padding:22px}h1{font-size:26px;margin:0 0 8px}p{color:#a7b4ca;line-height:1.6;margin:8px 0}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:20px 0 12px}button,select{background:#18253c;color:#e2e8f0;border:1px solid #3b4d69;border-radius:7px;padding:10px;font:inherit;cursor:pointer}select{max-width:100%}button:disabled{opacity:.4;cursor:default}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{padding:14px;background:#131e31;border:1px solid #25334b;border-radius:9px}.label{color:#94a3b8;font-size:12px;margin-bottom:7px}.value{font-size:18px;font-weight:600}
.up{color:#2dd4bf}.down{color:#fb7185}#detail{height:900px}#overview{height:340px}.panel{background:#101a2b;border-radius:10px;margin:18px 0;padding:12px}.table-wrap{overflow:auto;max-height:540px}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{padding:11px;text-align:right;border-bottom:1px solid #263248}th{position:sticky;top:0;background:#172239}th:first-child,td:first-child{text-align:left}tr[data-id]{cursor:pointer}tr[data-id]:hover,tr.selected{background:#253957}a{color:#7dd3fc}h2{font-size:18px}#status{color:#cbd5e1;margin:12px 0}
</style><script>__PLOTLY__</script></head><body>
<header><h1>ATHERENERG · Every executed trade</h1><p>₹1,00,000 starting capital · HA high breakout / BB middle exit · Volume filter disabled</p><p id="coverage"></p></header>
<main><div class="cards" id="summary"></div>
<div class="panel"><h2>Full-history overview</h2><p>Blue triangles mark buys. Exit markers are green for net winners and red for net losers. Click any trade marker to inspect its session.</p><div id="overview"></div></div>
<div class="toolbar"><button id="prev">← Previous trade</button><select id="select" aria-label="Choose a trade"></select><button id="next">Next trade →</button><button id="all">Show all candles / trades</button></div>
<div class="cards" id="tradeStats"></div><p id="status"></p><div class="panel"><div id="detail"></div></div>
<p>All times are IST and label the candle open. Signal and confirmation become known at candle close; entry uses the following real candle open plus slippage. Intrabar exit times identify the 5-minute candle, not the exact second. Trade markers use real fill prices; Heikin Ashi candles show the signal setup.</p>
<p>The yellow dashed line is the initial stop. The green dotted line is the higher of the initial stop and the previous completed candle’s BB middle; BB exit requires a strict break below the middle. Fees and slippage follow the saved backtest assumptions.</p>
<div class="panel"><h2>All trades — click a row to inspect</h2><div class="table-wrap"><table><thead><tr><th>Trade</th><th>Entry (IST)</th><th>Buy</th><th>Exit (IST)</th><th>Sell</th><th>Shares</th><th>Net P&amp;L</th><th>Exit reason</th></tr></thead><tbody id="ledger"></tbody></table></div></div>
<p><a href="REPORT.html">P&amp;L report</a> · <a href="interactive_tearsheet.html">Performance tearsheet</a> · <a href="trades.csv">Download trade ledger</a></p></main>
<script>
const D=__DATA__;
const money=n=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(n);
const card=(label,value,cls='')=>`<div class="card"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>`;
const color=n=>n>=0?'#2dd4bf':'#fb7185';
const short=s=>s.slice(0,16);
let selected=D.trades.length-1;
const base={paper_bgcolor:'#101a2b',plot_bgcolor:'#101a2b',font:{color:'#dbe5f5'},margin:{l:75,r:30,t:55,b:65},legend:{orientation:'h',y:1.08},hovermode:'closest',dragmode:'zoom'};
const config={responsive:true,displaylogo:false,scrollZoom:true,toImageButtonOptions:{format:'png',scale:2}};
document.getElementById('coverage').textContent=`${D.times[0].slice(0,10)} to ${D.times.at(-1).slice(0,10)} · ${D.trades.length} trades · ${D.times.length.toLocaleString()} five-minute bars · 334 complete sessions. Three incomplete/nonregular sessions excluded, including 9 September 2026.`;
document.getElementById('summary').innerHTML=card('Net P&L',money(D.summary.net_pnl),'down')+card('Ending capital',money(D.summary.final_equity))+card('Trades / win rate',`${D.trades.length} / ${D.summary.win_rate_pct.toFixed(2)}%`)+card('Maximum drawdown',D.summary.max_drawdown_pct.toFixed(2)+'%');
const selector=document.getElementById('select');
selector.innerHTML=D.trades.map((t,i)=>`<option value="${i}">#${t.id} · ${short(t.entry_time)} · ${money(t.net_pnl)}</option>`).join('');
document.getElementById('ledger').innerHTML=D.trades.map((t,i)=>`<tr data-id="${i}" tabindex="0"><td>#${t.id}</td><td>${short(t.entry_time)}</td><td>${t.entry.toFixed(2)}</td><td>${short(t.exit_time)}</td><td>${t.exit.toFixed(2)}</td><td>${t.quantity}</td><td style="color:${color(t.net_pnl)}">${money(t.net_pnl)}</td><td>${t.reason.replaceAll('_',' ')}</td></tr>`).join('');
const hover=t=>`Trade #${t.id}<br>Entry: ${short(t.entry_time)} @ ${money(t.entry)}<br>Exit: ${short(t.exit_time)} @ ${money(t.exit)}<br>Shares: ${t.quantity}<br>Net P&L: ${money(t.net_pnl)}<br>Exit: ${t.reason.replaceAll('_',' ')}`;
function marker(trades,kind,axis='y',xaxis='x'){
 const buy=kind==='entry';
 return {type:'scatter',mode:'markers',name:buy?'BUY (real fill)':'EXIT (real fill)',x:trades.map(t=>t[kind+'_idx']),y:trades.map(t=>t[kind]),text:trades.map(hover),customdata:trades.map(t=>t.id-1),hovertemplate:'%{text}<extra></extra>',marker:{symbol:buy?'triangle-up':'triangle-down',size:buy?13:12,color:buy?'#38bdf8':trades.map(t=>color(t.net_pnl)),line:{width:1,color:'#0b1120'}},yaxis:axis,xaxis};
}
function ticks(start,end,n=10){const step=Math.max(1,Math.ceil((end-start+1)/n));const vals=[];for(let i=start;i<=end;i+=step)vals.push(i);return {tickvals:vals,ticktext:vals.map(i=>D.times[i].slice(0,16).replace(' ','<br>'))};}
Plotly.newPlot('overview',[{type:'scatter',mode:'lines',x:D.times.map((_,i)=>i),y:D.close,line:{color:'#64748b',width:1},name:'Real close',text:D.times,hovertemplate:'%{text} IST<br>Close %{y:.2f}<extra></extra>'},marker(D.trades,'entry'),marker(D.trades,'exit')],{...base,margin:{l:75,r:30,t:45,b:65},xaxis:{...ticks(0,D.times.length-1),gridcolor:'#25334b'},yaxis:{title:'Real price / INR',gridcolor:'#25334b'}},config).then(g=>g.on('plotly_click',e=>{const i=e.points[0].customdata;if(Number.isInteger(i))showTrade(i);}));
function render(start,end,shown,all=false){
 const indices=Array.from({length:end-start+1},(_,i)=>start+i);
 const cut=k=>D[k].slice(start,end+1);
 const candles=(prefix,name,yaxis,xaxis)=>({type:'candlestick',x:indices,open:cut(prefix+'open'),high:cut(prefix+'high'),low:cut(prefix+'low'),close:cut(prefix+'close'),name,yaxis,xaxis,increasing:{line:{color:'#2dd4bf'}},decreasing:{line:{color:'#fb7185'}},text:cut('times'),hoverinfo:'text+name'});
 const line=(key,name,color,yaxis,xaxis,dash='solid')=>({type:'scatter',mode:'lines',x:indices,y:cut(key),name,line:{color,width:1.4,dash},yaxis,xaxis,text:cut('times'),hovertemplate:'%{text} IST<br>%{y:.2f}<extra>%{fullData.name}</extra>'});
 const traces=[candles('','Real OHLC','y','x'),candles('ha_','Heikin Ashi','y2','x2'),line('vwap','Session VWAP','#fbbf24','y','x'),line('bb_upper','Upper BB','#a78bfa','y2','x2'),line('bb_middle','BB middle','#cbd5e1','y2','x2'),line('bb_lower','Lower BB','#a78bfa','y2','x2'),line('vwap','VWAP (real HLC3)','#fbbf24','y2','x2'),marker(shown,'entry'),marker(shown,'exit')];
 traces.push({type:'scatter',mode:'markers',name:'Signal (HA)',x:shown.map(t=>t.signal_idx),y:shown.map(t=>D.ha_high[t.signal_idx]),marker:{symbol:'circle-open',size:15,color:'#fbbf24',line:{width:2}},text:shown.map(t=>`Trade #${t.id} signal bar<br>${D.times[t.signal_idx]} IST`),hovertemplate:'%{text}<extra></extra>',xaxis:'x2',yaxis:'y2'});
 traces.push({type:'scatter',mode:'markers',name:'Confirmation (HA)',x:shown.map(t=>t.confirmation_idx),y:shown.map(t=>D.ha_high[t.confirmation_idx]),marker:{symbol:'diamond-open',size:14,color:'#c084fc',line:{width:2}},text:shown.map(t=>`Trade #${t.id} confirmation bar<br>${D.times[t.confirmation_idx]} IST`),hovertemplate:'%{text}<extra></extra>',xaxis:'x2',yaxis:'y2'});
 const shapes=[],annotations=[];
 for(const t of shown){
  traces.push({type:'scatter',mode:'lines',x:[t.entry_idx,t.exit_idx],y:[t.entry,t.exit],line:{color:color(t.net_pnl),width:2,dash:'dot'},showlegend:false,hoverinfo:'skip'});
  if(!all){
   const xs=Array.from({length:t.exit_idx-t.entry_idx+1},(_,i)=>t.entry_idx+i);
   traces.push({type:'scatter',mode:'lines',x:xs,y:xs.map(i=>Math.max(t.stop,D.bb_middle[i-1])),name:'Prior BB middle / initial stop',line:{color:'#4ade80',width:2,dash:'dot',shape:'hv'},showlegend:t.id===shown[0].id});
   shapes.push({type:'line',xref:'x',yref:'y',x0:t.entry_idx,x1:Math.max(t.exit_idx,t.entry_idx+1),y0:t.stop,y1:t.stop,line:{color:'#fbbf24',width:2,dash:'dash'}});
   shapes.push({type:'rect',xref:'x',yref:'y domain',x0:t.entry_idx-.35,x1:t.exit_idx+.35,y0:0,y1:1,fillcolor:color(t.net_pnl),opacity:.06,line:{width:0}});
   annotations.push({x:t.entry_idx,y:t.entry,xref:'x',yref:'y',text:`BUY #${t.id}<br>${t.entry.toFixed(2)}`,showarrow:true,arrowhead:2,ax:-25,ay:55,font:{color:'#38bdf8'},bgcolor:'#101a2b'});
   annotations.push({x:t.exit_idx,y:t.exit,xref:'x',yref:'y',text:`EXIT #${t.id}<br>${t.exit.toFixed(2)} · ${money(t.net_pnl)}`,showarrow:true,arrowhead:2,ax:25,ay:-60,font:{color:color(t.net_pnl)},bgcolor:'#101a2b'});
  }
 }
 const common={...ticks(start,end),range:[start-1,end+1],gridcolor:'#25334b',zeroline:false,rangeslider:{visible:false}};
 Plotly.react('detail',traces,{...base,title:{text:all?'All executed trades · zoom to inspect':`${D.times[start].slice(0,10)} · Trade #${D.trades[selected].id} selected`,font:{size:17}},height:900,legend:{orientation:'h',y:-.10},margin:{l:75,r:35,t:70,b:135},xaxis:{...common,anchor:'y',showticklabels:false},yaxis:{domain:[.54,1],title:'Real price / INR',gridcolor:'#25334b',fixedrange:false},xaxis2:{...common,anchor:'y2',matches:'x'},yaxis2:{domain:[0,.43],title:'Heikin Ashi / INR',gridcolor:'#25334b',fixedrange:false},shapes,annotations},config);
}
function showTrade(i){
 selected=Math.max(0,Math.min(D.trades.length-1,i));selector.value=selected;const t=D.trades[selected];
 document.getElementById('prev').disabled=selected===0;document.getElementById('next').disabled=selected===D.trades.length-1;
 document.getElementById('tradeStats').innerHTML=card(`Trade #${t.id} · Net P&L`,money(t.net_pnl),t.net_pnl>=0?'up':'down')+card('Buy / shares',`${money(t.entry)} / ${t.quantity}`)+card('Sell / initial stop',`${money(t.exit)} / ${money(t.stop)}`)+card('Exit reason',t.reason.replaceAll('_',' '))+card('Fees',money(t.costs));
 const date=t.entry_time.slice(0,10);const start=D.times.findIndex(s=>s.startsWith(date));let end=start;while(end+1<D.times.length&&D.times[end+1].startsWith(date))end++;
 const shown=D.trades.filter(tr=>tr.entry_time.startsWith(date));
 document.getElementById('status').textContent=`Showing the complete ${date} session, including ${shown.length} trade(s). BUY ${short(t.entry_time)} → EXIT ${short(t.exit_time)} IST. Use the toolbar to zoom or save the chart as PNG.`;
 document.querySelectorAll('tr[data-id]').forEach(row=>row.classList.toggle('selected',Number(row.dataset.id)===selected));
 render(start,end,shown);
}
selector.onchange=()=>showTrade(Number(selector.value));document.getElementById('prev').onclick=()=>showTrade(selected-1);document.getElementById('next').onclick=()=>showTrade(selected+1);
document.getElementById('all').onclick=()=>{document.getElementById('status').textContent='All 25,050 included candles and all 73 entries/exits. Drag to zoom. Choose a trade to return to its complete session.';render(0,D.times.length-1,D.trades,true);};
document.querySelectorAll('tr[data-id]').forEach(row=>{row.onclick=()=>showTrade(Number(row.dataset.id));row.onkeydown=e=>{if(e.key==='Enter')showTrade(Number(row.dataset.id));};});
showTrade(selected);
</script></body></html>'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--report-dir",type=Path,required=True)
    args=parser.parse_args(); out=args.report_dir.resolve()
    summary=json.loads((out/"summary.json").read_text())
    assert hashlib.sha256(Path(strategy.__file__).read_bytes()).hexdigest()==summary["strategy_sha256"]
    raw=strategy.read_candles(out/"validated_ohlcv.csv")
    cfg=strategy.Config(capital=summary["capital"],volume_filter=False,breakout_source="high",exit_mode="bb_middle")
    d=strategy.indicators(raw,cfg)
    trades=pd.read_csv(out/"trades.csv")
    dates=["signal_time","confirmation_time","entry_time","exit_time"]
    for c in dates: trades[c]=pd.to_datetime(trades[c]).dt.tz_convert(strategy.TZ)
    np.testing.assert_allclose(trades.net_pnl.sum(),summary["net_pnl"])
    assert len(trades)==summary["trades"]
    payload={"times":d.index.strftime("%Y-%m-%d %H:%M").tolist(),"summary":summary,"trades":[]}
    for c in ["open","high","low","close","ha_open","ha_high","ha_low","ha_close","bb_middle","bb_upper","bb_lower","vwap"]:
        payload[c]=[round(float(v),6) if np.isfinite(v) else None for v in d[c]]
    for t in trades.itertuples():
        item={"id":t.trade_id,"quantity":t.quantity,"reason":t.reason}
        for c in ["entry","exit","stop","costs","net_pnl"]: item[c]=float(getattr(t,c))
        for c in dates:
            stamp=getattr(t,c);item[c]=stamp.strftime("%Y-%m-%d %H:%M")
            item[c.replace("_time","_idx")]=int(d.index.get_loc(stamp))
        assert item["confirmation_idx"]+1==item["entry_idx"]
        assert bool(d.signal.iloc[item["signal_idx"]])
        assert bool(d.confirmation.iloc[item["confirmation_idx"]])
        payload["trades"].append(item)
    page=PAGE.replace("__PLOTLY__",get_plotlyjs()).replace("__DATA__",json.dumps(payload,separators=(",",":"),allow_nan=False))
    (out/"trade_explorer.html").write_text(page,encoding="utf-8")
    with plt.style.context("dark_background"):
        fig,axes=plt.subplots(2,1,figsize=(18,10),gridspec_kw={"height_ratios":[3,1]},constrained_layout=True)
        x=np.arange(len(d));axes[0].plot(x,d.close,color="#94a3b8",lw=.8,label="Real close")
        entries=[t["entry_idx"] for t in payload["trades"]];exits=[t["exit_idx"] for t in payload["trades"]]
        axes[0].scatter(entries,trades.entry,marker="^",s=45,color="#38bdf8",label="Buy",zorder=3)
        for winning,color,label in [(True,"#2dd4bf","Exit: net profit"),(False,"#fb7185","Exit: net loss")]:
            mask=(trades.net_pnl>=0).to_numpy()==winning
            axes[0].scatter(np.array(exits)[mask],trades.exit[mask],marker="v",s=45,color=color,label=label,zorder=3)
        axes[0].set_ylabel("Real price / INR");axes[0].legend(loc="upper left",ncol=4)
        ticks=np.linspace(0,len(d)-1,12,dtype=int)
        axes[0].set_xticks(ticks,d.index[ticks].strftime("%d %b %Y"),rotation=25)
        axes[0].set_title("ATHERENERG | All 73 executed trades | INR 100,000 starting capital",fontsize=18,pad=18)
        axes[1].bar(trades.trade_id,trades.net_pnl,color=np.where(trades.net_pnl>=0,"#2dd4bf","#fb7185"))
        axes[1].axhline(0,color="#94a3b8",lw=.7);axes[1].set_ylabel("Net P&L / INR");axes[1].set_xlabel("Trade number (chronological)")
        axes[1].set_title(f"Net P&L: INR {summary['net_pnl']:,.2f} | 21 winners / 52 losers | Open trade_explorer.html for candle-level detail",fontsize=12)
        fig.savefig(out/"all_trades_overview.png",dpi=150);plt.close(fig)
    report=out/"REPORT.html"
    report_html=report.read_text(encoding="utf-8")
    link='<p><a href="trade_explorer.html">Explore every executed trade on candles</a></p>'
    if 'href="trade_explorer.html"' not in report_html:
        report.write_text(report_html.replace("</h1>","</h1>"+link,1),encoding="utf-8")
    archive=out.parent/(out.name+"_reports.zip")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for p in out.iterdir():
            if p.is_file():z.write(p,arcname=out.name+"/"+p.name)
        for p in [Path(__file__),Path(__file__).with_name("run_csv_report.py"),
                  Path(__file__).with_name("polars_data.py"),Path(__file__).with_name("requirements.txt"),
                  Path(__file__).with_name("README.md"),Path(strategy.__file__)]:
            z.write(p,arcname=out.name+"/"+p.name)
    print(f"Validated all {len(trades)} entry/exit markers and signal timestamps against the saved ledger.")
    print(out/"trade_explorer.html")
    print(out/"all_trades_overview.png")


if __name__=="__main__":main()
