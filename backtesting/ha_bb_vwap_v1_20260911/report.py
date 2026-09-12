"""Offline per-strategy reports and a full-session interactive chart for every trade."""

import html
import json
from pathlib import Path

from plotly.offline import get_plotlyjs
from replay import DAY, safe_json, write_csv

STYLE = """body{background:#101722;color:#e2e8f0;font:15px system-ui;margin:26px}a{color:#66baff}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid #334155;text-align:right}th:first-child,td:first-child{text-align:left}th{position:sticky;top:0;background:#182235}h1{font-size:24px;overflow-wrap:anywhere}.note{background:#273347;padding:14px;line-height:1.6}.green{color:#35d99c}.red{color:#fb7185}input{background:#273347;color:white;padding:10px;width:65%;margin:14px 0}#chart{height:760px}pre{white-space:pre-wrap}button{padding:8px;margin:5px}"""
DISCLAIMER = "OHLC-path approximation, not tick replay. Two paths tested; uniform assumed intraminute volume. 0.05% adverse slippage plus adverse tick rounding and estimated Zerodha intraday fees. End-of-day gainers/losers selection creates hindsight bias. One day cannot establish a durable edge."


def money(v):
    return f"{v:,.2f}"


def document(title, body, scripts=""):
    return f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{STYLE}</style></head><body>{body}{scripts}</body></html>'


VIEWER = r"""
const t=window.TRADE,b=window.BARS;
const labels=b.map(x=>x.time);
function bucket(iso){const d=new Date(iso); const ist=new Date(d.getTime()+330*60000);return String(ist.getUTCHours()).padStart(2,'0')+':'+String(Math.floor(ist.getUTCMinutes()/t.minutes)*t.minutes).padStart(2,'0');}
const green='#22c55e',red='#ef4444';
let traces=[{type:'candlestick',name:'Heikin Ashi',x:labels,open:b.map(x=>x.ha[0]),high:b.map(x=>x.ha[1]),low:b.map(x=>x.ha[2]),close:b.map(x=>x.ha[3]),increasing:{line:{color:green},fillcolor:green},decreasing:{line:{color:red},fillcolor:red}}];
traces.push({type:'candlestick',name:'Real candles (toggle)',visible:'legendonly',x:labels,open:b.map(x=>x.raw[0]),high:b.map(x=>x.raw[1]),low:b.map(x=>x.raw[2]),close:b.map(x=>x.raw[3]),increasing:{line:{color:green},fillcolor:green},decreasing:{line:{color:red},fillcolor:red}});
for(const [key,name,color] of [['bb_upper','BB upper','#a78bfa'],['bb_mid','BB middle','#7c83b5'],['bb_lower','BB lower','#a78bfa'],['vwap','VWAP','#f59e0b']]) traces.push({type:'scatter',mode:'lines',name,x:labels,y:b.map(x=>x[key]),line:{color,width:1.4}});
for(const [key,name,color] of [['sma9','SMA9','#4ade80'],['ema9','EMA9','#38bdf8'],['ema21','EMA21','#ec4899'],['supertrend','Supertrend','#94a3b8']])traces.push({type:'scatter',mode:'lines',name,x:labels,y:b.map(x=>x[key]),visible:t.name.includes(key)?true:'legendonly',line:{color,width:1}});
const signalTime=bucket(new Date(new Date(t.entry_time).getTime()-t.minutes*60000).toISOString());
const signal=b.find(x=>x.time===signalTime);
if(signal)traces.push({type:'scatter',mode:'markers',name:'Completed signal',x:[signalTime],y:[signal.ha[t.side==='buy'?1:2]],marker:{symbol:'diamond-open',color:'#38bdf8',size:12,line:{width:2}}});
traces.push({type:'scatter',mode:'markers',name:'Entry fill',x:[bucket(t.entry_time)],y:[t.entry_price],marker:{symbol:t.side==='buy'?'triangle-up':'triangle-down',color:'#facc15',size:15,line:{color:'black',width:1}},text:[t.entry_time+' | '+t.quantity+' shares @ '+t.entry_price.toFixed(4)],hovertemplate:'%{text}<extra>Entry</extra>'});
traces.push({type:'scatter',mode:'markers',name:'Exit fills',x:t.fills.slice(1).map(x=>bucket(x.time)),y:t.fills.slice(1).map(x=>x.price),marker:{symbol:'x',color:'#f8fafc',size:12},text:t.fills.slice(1).map(x=>x.time+' | '+x.reason+' | '+x.quantity+' @ '+x.price.toFixed(4)),hovertemplate:'%{text}<extra>Exit</extra>'});
for(const [name,y,color] of [['Entry',t.entry_price,'#facc15'],['Initial SL',t.initial_stop,'#ef4444'],['Fixed target',t.target,'#22c55e']])traces.push({type:'scatter',mode:'lines',name,x:[bucket(t.entry_time),bucket(t.exit_time)],y:[y,y],line:{color,dash:'dash',width:1.5}});
if(t.stop_path.length)traces.push({type:'scatter',mode:'lines+markers',name:'Trailing SL',x:t.stop_path.map(x=>bucket(x[0])),y:t.stop_path.map(x=>x[1]),line:{color:'#fb923c',shape:'hv'},marker:{size:4}});
const categories=[];for(let m=555;m<=930;m+=t.minutes)categories.push(String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0'));
const tickvals=categories.filter((x,i)=>i===0||x.endsWith(':00')||x.endsWith(':30')||x==='15:30');
const oscillator=t.name.includes('rsi_')?'rsi':t.name.includes('macd_')?'macd':null;
if(oscillator){for(const key of oscillator==='rsi'?['rsi']:['macd','macd_signal'])traces.push({type:'scatter',mode:'lines',name:key.toUpperCase(),x:labels,y:b.map(x=>x[key]),yaxis:'y2',line:{width:1.5}});}
Plotly.newPlot('chart',traces,{paper_bgcolor:'#101722',plot_bgcolor:'#101722',font:{color:'#e2e8f0'},margin:{l:70,r:35,t:100,b:75},xaxis:{type:'category',categoryorder:'array',categoryarray:categories,range:[-.5,categories.length-.5],tickmode:'array',tickvals,rangeslider:{visible:false},title:{text:'11 September 2026 • IST • Full session 09:15–15:30'}},yaxis:{title:{text:'Price (Rs)'},gridcolor:'#263449',autorange:true,domain:oscillator?[.28,1]:[0,1]},yaxis2:{domain:[0,.2],title:{text:oscillator?.toUpperCase()},gridcolor:'#263449'},legend:{orientation:'h',y:1.15},shapes:[{type:'rect',xref:'x',yref:'paper',x0:bucket(t.entry_time),x1:bucket(t.exit_time),y0:0,y1:1,fillcolor:'#64748b',opacity:.12,line:{width:0}}]}, {responsive:true,displaylogo:false,toImageButtonOptions:{format:'png',filename:t.id,width:1800,height:950,scale:2}});
"""


def initialize(output):
    for folder in ("assets", "trades", "strategies"):
        (output / folder).mkdir(parents=True, exist_ok=True)
    (output / "assets/plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    (output / "assets/viewer.js").write_text(VIEWER, encoding="utf-8")


def save_bars(output, key, charts):
    rows = []
    for s in charts:
        v = s.indicators
        rows.append(
            {
                "time": s.candle.start.strftime("%H:%M"),
                "ha": [s.ha_open, s.ha_high, s.ha_low, s.ha_close],
                "raw": [s.candle.open, s.candle.high, s.candle.low, s.candle.close],
                **{
                    k: getattr(v, k)
                    for k in (
                        "bb_upper",
                        "bb_mid",
                        "bb_lower",
                        "vwap",
                        "sma9",
                        "ema9",
                        "ema21",
                        "supertrend",
                        "rsi",
                        "macd",
                        "macd_signal",
                    )
                },
            }
        )
    (output / "assets" / f"{key}.js").write_text(
        "window.BARS=" + json.dumps(safe_json(rows)) + ";", encoding="utf-8"
    )


def save_trade(output, trade, bars_key):
    title = f"{trade['id']} | {trade['symbol']} {trade['side']} {trade['minutes']}m | {trade['scenario']}"
    rows = "".join(
        f"<tr><td>{f['time'][11:19]}</td><td>{f['side']}</td><td>{f['reason']}</td><td>{f['quantity']}</td><td>{f['price']:.4f}</td><td>{f['fees']:.2f}</td></tr>"
        for f in trade["fills"]
    )
    body = f"""<a href="../strategies/{trade["strategy_id"]}.html">Strategy report</a> · <a href="../index.html">All strategies</a>
<h1>{html.escape(title)}</h1><p>{html.escape(trade["name"])}</p><p>Net P&amp;L: <b class="{"green" if trade["net_pnl"] > 0 else "red"}">Rs {money(trade["net_pnl"])}</b> · Gross after slippage: Rs {money(trade["gross_pnl"])} · Fees: Rs {money(trade["fees"])}</p>
<div class="note">{DISCLAIMER}<br>Green = HA close ≥ HA open; red = HA close &lt; HA open. Real prices are available in the legend. Click legend labels to toggle indicators; toolbar camera exports PNG. Missing candles remain gaps. The last regular candle ends at 15:30; no artificial 15:30 candle is added.</div>
<div id="chart"></div><table><tr><th>IST time</th><th>Side</th><th>Reason</th><th>Shares</th><th>Fill</th><th>Fees</th></tr>{rows}</table>"""
    scripts = f'<script src="../assets/plotly.min.js"></script><script src="../assets/{bars_key}.js"></script><script>window.TRADE={json.dumps(safe_json(trade))};</script><script src="../assets/viewer.js"></script>'
    (output / "trades" / f"{trade['id']}.html").write_text(
        document(title, body, scripts), encoding="utf-8"
    )


def strategy_page(output, cfg, sid, metrics, trades, stock_rows):
    mrows = "".join(
        f"<tr><td>{m['scenario']}</td><td>{m['trades']}</td><td>{money(m['net_pnl'])}</td><td>{money(m['gross_pnl'])}</td><td>{money(m['fees'])}</td><td>{m['win_rate']:.1f}%</td><td>{money(m['max_drawdown'])}</td><td>{money(m['peak_notional'])}</td></tr>"
        for m in metrics
    )
    trows = "".join(
        f"<tr><td><a href='../trades/{t['id']}.html'>{t['id']} chart</a></td><td>{t['symbol']}</td><td>{t['scenario']}</td><td>{t['entry_time'][11:19]}</td><td>{t['exit_time'][11:19]}</td><td>{t['quantity']}</td><td>{money(t['net_pnl'])}</td><td>{t['exit_reason']}</td></tr>"
        for t in trades
    )
    stocks = "".join(
        f"<tr><td>{r['symbol']}</td><td>{r['scenario']}</td><td>{r['trades']}</td><td>{money(r['net_pnl'])}</td><td>{money(r['benchmark_net'])}</td></tr>"
        for r in stock_rows
    )
    body = f"""<a href='../index.html'>All strategies</a><h1>{sid}: {html.escape(cfg.name)}</h1><div class='note'>{DISCLAIMER}<br>Each stock has independent Rs 100,000 per-trade allocation; total P&amp;L is the sum across the supplied 11-stock basket. Return denominator is Rs 1,100,000, not Rs 100,000. Peak notional is shown separately. Sharpe, Sortino and annualized returns are not estimated from one trading day.</div>
<h2>Performance</h2><table><tr><th>Path</th><th>Trades</th><th>Net Rs</th><th>Gross Rs</th><th>Fees Rs</th><th>Win rate</th><th>Bar-close MTM drawdown Rs</th><th>Peak notional Rs</th></tr>{mrows}</table>
<p>Settings: SL buffer {cfg.sl_buffer}; RR {cfg.reward_risk}; trail {cfg.trail_fraction:.0%}; partial {cfg.partial}; indicator stop {cfg.stop_rule}; indicator target {cfg.target_rule}.</p>
<h2>Per-stock report and session benchmark</h2><p>Benchmark is a same-direction open-to-cutoff trade in each supplied stock with identical sizing/cost assumptions. It is also selected with hindsight. NIFTY data was not provided; no NIFTY comparison is fabricated.</p><table><tr><th>Stock</th><th>Path</th><th>Trades</th><th>Strategy net Rs</th><th>Session benchmark net Rs</th></tr>{stocks}</table>
<h2>Every trade</h2><table><tr><th>Full-session chart</th><th>Stock</th><th>Path</th><th>Entry IST</th><th>Exit IST</th><th>Shares</th><th>Net Rs</th><th>Exit reason</th></tr>{trows or "<tr><td>No trades generated.</td></tr>"}</table>"""
    (output / "strategies" / f"{sid}.html").write_text(document(cfg.name, body), encoding="utf-8")
    (output / "strategies" / f"{sid}.json").write_text(
        json.dumps(
            safe_json(
                {"name": cfg.name, "metrics": metrics, "stocks": stock_rows, "trades": trades}
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


def index_page(output, ranking, audit):
    rows = "".join(
        f"<tr><td><a href='strategies/{r['strategy_id']}.html'>{r['strategy_id']}</a></td><td>{r['side']}</td><td>{r['minutes']}</td><td>{money(r['worst_path_net'])}</td><td>{money(r['mean_path_net'])}</td><td>{r['trades_OLHC']}/{r['trades_OHLC']}</td><td>{html.escape(r['name'])}</td></tr>"
        for r in ranking
    )
    leaders = []
    for side in ("buy", "sell"):
        for minutes in (1, 5):
            candidates = [
                r
                for r in ranking
                if r["side"] == side
                and r["minutes"] == minutes
                and r["trades_OLHC"] + r["trades_OHLC"] > 0
            ]
            if candidates:
                r = candidates[0]
                leaders.append(
                    f"<li>{side} {minutes}m: <a href='strategies/{r['strategy_id']}.html'>{r['strategy_id']}</a>, worse-path net Rs {money(r['worst_path_net'])}, mean-path net Rs {money(r['mean_path_net'])}.</li>"
                )
    body = f"""<h1>HA / Bollinger / VWAP V1 — 11 September 2026</h1><div class='note'>{DISCLAIMER}<br>Ranking: highest minimum net P&amp;L across the two assumed paths, then mean net P&amp;L. This is a sensitivity score, not a mathematical worst-case bound. Choose a strategy for its report; choose any trade for its individual full-session chart.</div>
<p><a href='SUMMARY.md'>Written findings</a> · <a href='strategy_summary.csv'>404-strategy comparison CSV</a> · <a href='all_trades.csv'>All trades CSV</a> · <a href='data_audit.json'>Source/data audit</a> · <a href='methodology.md'>Methodology</a></p>
<h2>Best observed by direction/timeframe</h2><ul>{"".join(leaders)}</ul><p>Reports: 404 strategies × 11 stocks × 2 path assumptions = 8,888 strategy-stock runs. Missing warm-up and low-volume data reduce confidence; use the detailed audit. These results do not establish that the winner will work on another day.</p>
<input id='search' placeholder='Filter by strategy, side, timeframe or exit rule'><table id='ranking'><thead><tr><th>Report</th><th>Side</th><th>Minutes</th><th>Worse-path net Rs</th><th>Mean-path net Rs</th><th>Trades L/H</th><th>Strategy name</th></tr></thead><tbody>{rows}</tbody></table>"""
    scripts = "<script>document.querySelector('#search').oninput=e=>{let q=e.target.value.toLowerCase();document.querySelectorAll('#ranking tbody tr').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q)?'':'none')};</script>"
    (output / "index.html").write_text(
        document("V1 backtest comparison", body, scripts), encoding="utf-8"
    )
    return leaders
