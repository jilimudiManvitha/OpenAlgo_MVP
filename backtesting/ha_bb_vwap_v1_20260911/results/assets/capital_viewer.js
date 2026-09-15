
const data=window.CAPITAL,selector=document.querySelector('#scenario'),timeInput=document.querySelector('#at');
const cash=x=>'Rs '+Number(x).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const when=x=>x?x.slice(11,26).replace(/\+.*$/,''):'';
function selected(){return data[selector.value];}
function row(label,value){return '<tr><td>'+label+'</td><td>'+value+'</td></tr>';}
function show(){
 const d=selected(),s=d.metrics;
 document.querySelector('#summary').innerHTML=
 row('Total round-trip trades / filled orders',s.trades+' / '+s.filled_orders)+
 row('Net profit',cash(s.net_pnl))+row('Brokerage only',cash(s.brokerage))+
 row('Exchange + SEBI + STT + stamp + GST',cash(s.other_charges))+
 row('Total brokerage and other charges',cash(s.total_charges))+row('Slippage and tick-rounding cost',cash(s.slippage_cost))+
 row('Basket allocation / per-trade limit',cash(s.allocated_capital)+' / Rs 1,00,000')+
 row('Peak simultaneous capital at entry prices',cash(s.peak_capital_used)+' at '+when(s.peak_capital_time))+
 row('Cumulative entry notional (capital reused)',cash(s.total_entry_notional))+
 row('Maximum simultaneous open trades',s.max_open_positions+' at '+when(s.max_open_positions_time))+
 row('Maximum bar-close MTM drawdown',cash(s.max_drawdown)+'; peak '+when(s.drawdown_peak_time)+' → trough '+when(s.drawdown_trough_time))+
 row('Largest winning trade',cash(s.max_trade_profit)+(s.max_trade_profit_id?' · <a href="../trades/'+s.max_trade_profit_id+'.html">'+s.max_trade_profit_id+'</a>':''))+
 row('Largest losing trade',cash(s.max_trade_loss)+(s.max_trade_loss_id?' · <a href="../trades/'+s.max_trade_loss_id+'.html">'+s.max_trade_loss_id+'</a>':''))+
 row('Highest session bar-close MTM profit',cash(s.max_session_mtm_profit)+' at '+when(s.max_session_mtm_profit_time))+
 row('Lowest session bar-close MTM P&L',cash(s.min_session_mtm_pnl)+' at '+when(s.min_session_mtm_pnl_time));
 const local=x=>x.slice(0,26).replace(/\+.*$/,'');
 const trace=(name,rows,key,color,axis)=>({name,type:'scatter',mode:'lines',x:rows.map(r=>local(r.time)),y:rows.map(r=>r[key]),line:{color,shape:'hv'},yaxis:axis});
 Plotly.react('chart',[
 trace('Capital in use',d.timeline,'capital_in_use','#38bdf8','y'),
 trace('Open trades',d.timeline,'open_positions','#f59e0b','y2'),
 trace('Bar-close net MTM',d.equity,'net_mtm_pnl','#22c55e','y3'),
 trace('Bar-close drawdown',d.equity,'drawdown','#ef4444','y3')],
 {paper_bgcolor:'#101722',plot_bgcolor:'#101722',font:{color:'#e2e8f0'},margin:{l:90,r:70,t:60,b:60},
 xaxis:{type:'date',range:['2026-09-11T09:15:00','2026-09-11T15:30:00'],tickformat:'%H:%M',anchor:'free',position:0,title:{text:'11 September 2026 · IST'}},
 yaxis:{domain:[.4,1],title:{text:'Capital (Rs)'},gridcolor:'#334155'},
 yaxis2:{overlaying:'y',anchor:'x',side:'right',range:[0,12],dtick:2,title:{text:'Open trades'}},
 yaxis3:{domain:[0,.27],title:{text:'P&L / DD (Rs)'},gridcolor:'#334155'},legend:{orientation:'h',y:1.12},hovermode:'x unified'},
 {responsive:true,displaylogo:false});
 lookup();
}
function lookup(){
 const d=selected(),time=timeInput.value.length===5?timeInput.value+':00':timeInput.value;
 const stamp=Date.parse('2026-09-11T'+time+'+05:30');
 if(!Number.isFinite(stamp)||time<'09:15:00'||time>'15:30:00'){document.querySelector('#snapshot').textContent='Choose a time from 09:15:00 to 15:30:00 IST.';return;}
 const before=rows=>rows.filter(x=>Date.parse(x.time)<=stamp).at(-1);
 const r=before(d.timeline),e=before(d.equity);
 document.querySelector('#snapshot').innerHTML='<h3>At '+time+' IST</h3><p><b>'+r.open_positions+' open trades</b> · '+cash(r.capital_in_use)+' capital in use · '+r.entries_so_far+' entries and '+r.closed_trades_so_far+' completed trades so far.</p><p>Realized P&L less fees paid: '+cash(r.realized_pnl_less_paid_fees)+'. Latest bar-close MTM: '+cash(e.net_mtm_pnl)+' (mark at '+when(e.time)+' IST).</p>'+
 '<table><tr><th>Trade</th><th>Stock</th><th>Remaining shares</th><th>Entry price</th><th>Entry notional still in use</th></tr>'+r.positions.map(p=>'<tr><td><a href="../trades/'+p.trade_id+'.html">'+p.trade_id+'</a></td><td>'+p.symbol+'</td><td>'+p.quantity+'</td><td>'+cash(p.entry_price)+'</td><td>'+cash(p.entry_price*p.quantity)+'</td></tr>').join('')+'</table>';
}
selector.onchange=show;timeInput.oninput=lookup;
if(location.hash==='#OHLC')selector.value='OHLC';show();
