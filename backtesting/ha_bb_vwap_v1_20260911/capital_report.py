"""Derive brokerage, capital/concurrency timelines and extrema from frozen fills."""

import csv
import html
import json
import pickle
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from report import document

OUT = HERE / "results"
START = "2026-09-11T09:15:00+05:30"
END = "2026-09-11T15:30:00+05:30"
PARTS = ("brokerage", "exchange", "sebi", "stt", "stamp", "gst")


def cost_parts(fill):
    turnover = fill["quantity"] * fill["price"]
    brokerage = min(20.0, turnover * 0.0003)
    exchange, sebi = turnover * 0.0000307, turnover * 0.000001
    return {
        "brokerage": brokerage,
        "exchange": exchange,
        "sebi": sebi,
        "stt": turnover * 0.00025 if fill["side"] == "sell" else 0.0,
        "stamp": turnover * 0.00003 if fill["side"] == "buy" else 0.0,
        "gst": 0.18 * (brokerage + exchange + sebi),
    }


def timeline(trades):
    events = defaultdict(list)
    for trade in trades:
        for fill in trade["fills"]:
            events[fill["time"]].append((trade, fill))
    state = {}
    net = entries = closed = exit_fills = fees = brokerage = 0
    result = []
    all_times = sorted(set(events) | {START, END})
    for stamp in all_times:
        opened_now = closed_now = exits_now = 0
        # At identical timestamps, free capital from exits before opening new positions.
        for trade, fill in sorted(events[stamp], key=lambda x: x[1]["reason"] == "entry"):
            cost = cost_parts(fill)
            assert np.isclose(sum(cost.values()), fill["fees"], atol=1e-7)
            fees += fill["fees"]
            brokerage += cost["brokerage"]
            net -= fill["fees"]
            if fill["reason"] == "entry":
                assert trade["id"] not in state
                state[trade["id"]] = {
                    "symbol": trade["symbol"],
                    "quantity": fill["quantity"],
                    "entry_price": fill["price"],
                }
                entries += 1
                opened_now += 1
            else:
                position = state[trade["id"]]
                net += (
                    (1 if trade["side"] == "buy" else -1)
                    * (fill["price"] - position["entry_price"])
                    * fill["quantity"]
                )
                position["quantity"] -= fill["quantity"]
                assert position["quantity"] >= 0
                exits_now += 1
                exit_fills += 1
                if position["quantity"] == 0:
                    del state[trade["id"]]
                    closed += 1
                    closed_now += 1
        positions = [{"trade_id": key, **value} for key, value in sorted(state.items())]
        result.append(
            {
                "time": stamp,
                "open_positions": len(state),
                "capital_in_use": sum(p["quantity"] * p["entry_price"] for p in positions),
                "entries_so_far": entries,
                "closed_trades_so_far": closed,
                "exit_fills_so_far": exit_fills,
                "entries_at_time": opened_now,
                "closed_trades_at_time": closed_now,
                "exit_fills_at_time": exits_now,
                "realized_pnl_less_paid_fees": net,
                "fees_paid": fees,
                "brokerage_paid": brokerage,
                "positions": positions,
            }
        )
    assert not state
    assert entries == closed == len(trades)
    assert np.isclose(net, sum(t["net_pnl"] for t in trades))
    assert max(x["open_positions"] for x in result) <= 11
    return result


def equity_curve(series, final_net):
    curve = pd.concat(series, axis=1).sort_index().ffill().fillna(0).sum(axis=1)
    curve.loc[START] = 0.0
    curve.loc[END] = final_net
    curve = curve.sort_index()
    high_water = curve.cummax()
    drawdown = high_water - curve
    trough_time = drawdown.idxmax()
    peak_time = curve.loc[:trough_time].idxmax()
    rows = [
        {"time": t, "net_mtm_pnl": float(curve.loc[t]), "drawdown": float(drawdown.loc[t])}
        for t in curve.index
    ]
    return rows, {
        "max_drawdown": float(drawdown.max()),
        "drawdown_peak_time": peak_time,
        "drawdown_trough_time": trough_time,
        "max_session_mtm_profit": float(curve.max()),
        "max_session_mtm_profit_time": curve.idxmax(),
        "min_session_mtm_pnl": float(curve.min()),
        "min_session_mtm_pnl_time": curve.idxmin(),
    }


VIEWER = r"""
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
"""


def main():
    destination = OUT / "capital"
    destination.mkdir(exist_ok=True)
    (OUT / "assets/capital_viewer.js").write_text(VIEWER, encoding="utf-8")
    marked = defaultdict(list)
    for file in sorted((OUT / "checkpoints").glob("*.pkl")):
        with file.open("rb") as handle:
            saved = pickle.load(handle)
        for r in saved["results"]:
            marked[(r["strategy_id"], r["scenario"])].append(
                pd.Series(dict(r["marked"]), dtype=float)
            )
    rows, timeline_rows, equity_rows, fee_rows = [], [], [], []
    old_metrics = pd.read_csv(OUT / "strategy_path_metrics.csv").set_index(
        ["strategy_id", "scenario"]
    )
    for file in sorted((OUT / "strategies").glob("*.json")):
        report = json.loads(file.read_text(encoding="utf-8"))
        sid = file.stem
        scenarios = {}
        for path in ("OLHC", "OHLC"):
            trades = [t for t in report["trades"] if t["scenario"] == path]
            fills = [f for t in trades for f in t["fills"]]
            components = dict.fromkeys(PARTS, 0.0)
            for t in trades:
                for index, f in enumerate(t["fills"], 1):
                    cost = cost_parts(f)
                    fee_rows.append(
                        dict(
                            strategy_id=sid,
                            scenario=path,
                            trade_id=t["id"],
                            fill_number=index,
                            time=f["time"],
                            symbol=t["symbol"],
                            side=f["side"],
                            quantity=f["quantity"],
                            price=f["price"],
                            **cost,
                            total_charges=sum(cost.values()),
                        )
                    )
                    for key in PARTS:
                        components[key] += cost[key]
            states = timeline(trades)
            original = old_metrics.loc[(sid, path)]
            curve, extrema = equity_curve(marked[(sid, path)], original.net_pnl)
            peak = max(states, key=lambda x: x["capital_in_use"])
            concurrent = max(states, key=lambda x: x["open_positions"])
            best = max(
                (t for t in trades if t["net_pnl"] > 0), key=lambda x: x["net_pnl"], default=None
            )
            worst = min(
                (t for t in trades if t["net_pnl"] < 0), key=lambda x: x["net_pnl"], default=None
            )
            row = dict(
                strategy_id=sid,
                name=report["name"],
                scenario=path,
                trades=len(trades),
                filled_orders=len(fills),
                net_pnl=float(original.net_pnl),
                allocated_capital=1100000,
                per_trade_limit=100000,
                total_entry_notional=sum(t["quantity"] * t["entry_price"] for t in trades),
                total_turnover=sum(f["quantity"] * f["price"] for f in fills),
                peak_capital_used=peak["capital_in_use"],
                peak_capital_time=peak["time"],
                max_open_positions=concurrent["open_positions"],
                max_open_positions_time=concurrent["time"],
                **components,
                other_charges=sum(v for k, v in components.items() if k != "brokerage"),
                total_charges=sum(components.values()),
                slippage_cost=float(original.slippage_cost),
                max_trade_profit=best["net_pnl"] if best else 0,
                max_trade_profit_id=best["id"] if best else "",
                max_trade_profit_exit_time=best["exit_time"] if best else "",
                max_trade_loss=worst["net_pnl"] if worst else 0,
                max_trade_loss_id=worst["id"] if worst else "",
                max_trade_loss_exit_time=worst["exit_time"] if worst else "",
                **extrema,
            )
            assert np.isclose(row["total_charges"], original.fees)
            assert np.isclose(row["peak_capital_used"], original.peak_notional)
            assert np.isclose(row["max_drawdown"], original.max_drawdown)
            rows.append(row)
            scenarios[path] = {"metrics": row, "timeline": states, "equity": curve}
            for r in states:
                timeline_rows.append(
                    dict(
                        strategy_id=sid,
                        scenario=path,
                        **{k: v for k, v in r.items() if k != "positions"},
                        open_trade_ids=";".join(p["trade_id"] for p in r["positions"]),
                        open_symbols=";".join(p["symbol"] for p in r["positions"]),
                    )
                )
            equity_rows.extend(dict(strategy_id=sid, scenario=path, **r) for r in curve)
        (destination / f"{sid}.js").write_text(
            "window.CAPITAL=" + json.dumps(scenarios) + ";", encoding="utf-8"
        )
        body = f"""<a href='../strategies/{sid}.html'>Strategy and every trade</a> · <a href='../capital_overview.html'>All capital/risk reports</a>
<h1>{sid}: brokerage, capital and open trades</h1><p>{html.escape(report["name"])}</p>
<div class='note'>Figures are for one strategy and one modeled path. Capital means remaining entry notional across open positions, including shorts; it is not broker margin or cumulative turnover. Partial exits free proportional entry notional. At a shared timestamp, exits precede entries. Drawdown and session P&amp;L extrema use completed-bar MTM; intrabar excursions can be larger. Brokerage and taxes are estimates from the frozen run.</div>
<p>Path: <select id='scenario'><option>OLHC</option><option>OHLC</option></select> · <a href='../capital_risk_metrics.csv'>All metrics CSV</a> · <a href='../capital_trade_timeline.csv'>Open-trade timeline CSV</a> · <a href='../brokerage_breakdown.csv'>Brokerage/taxes per fill</a></p>
<table id='summary'></table><h2>Open trades at a particular time</h2><label>Time (IST): <input id='at' type='time' step='1' min='09:15:00' max='15:30:00' value='10:00:00' style='width:180px'></label><div id='snapshot'></div>
<div id='chart'></div><p>Timeline rows describe state after all fills at the recorded time. Between rows, count and entry notional stay unchanged. The lookup uses the latest row at/before the requested time. MTM is the latest completed-bar mark, not a fresh tick valuation. A trade means one entry through its final exit; partial exits increase filled-order count, not round-trip count. Max loss is signed negative; zero means no losing trade/negative MTM observation.</p>"""
        scripts = f"<script src='../assets/plotly.min.js'></script><script src='{sid}.js'></script><script src='../assets/capital_viewer.js'></script>"
        (destination / f"{sid}.html").write_text(
            document(f"{sid} capital/risk report", body, scripts), encoding="utf-8"
        )
        strategy_page = OUT / "strategies" / f"{sid}.html"
        text = strategy_page.read_text(encoding="utf-8")
        text = re.sub(r"<!-- capital link -->.*?<!-- /capital link -->", "", text, flags=re.S)
        link = f"<!-- capital link --><p><a href='../capital/{sid}.html'>Brokerage, capital used, largest profit/loss, drawdown times and open trades at any time</a></p><!-- /capital link -->"
        strategy_page.write_text(
            text.replace("<h2>Performance", link + "<h2>Performance", 1), encoding="utf-8"
        )
        if int(sid[1:]) % 100 == 0:
            print(f"Capital/risk reports: {sid}", flush=True)
    for name, values in (
        ("capital_risk_metrics.csv", rows),
        ("capital_trade_timeline.csv", timeline_rows),
        ("portfolio_mtm_timeline.csv", equity_rows),
        ("brokerage_breakdown.csv", fee_rows),
    ):
        with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    table = "".join(
        f"<tr><td><a href='capital/{r['strategy_id']}.html#{r['scenario']}'>{r['strategy_id']}</a></td><td>{r['scenario']}</td><td>{r['trades']}</td><td>{r['brokerage']:,.2f}</td><td>{r['total_charges']:,.2f}</td><td>{r['peak_capital_used']:,.2f}</td><td>{r['max_open_positions']}</td><td>{r['max_drawdown']:,.2f}</td><td>{r['max_trade_profit']:,.2f}</td><td>{r['max_trade_loss']:,.2f}</td></tr>"
        for r in rows
    )
    body = f"""<a href='index.html'>Strategy comparison</a><h1>Brokerage, capital and risk — all 404 strategies</h1><p>808 rows keep the two OHLC path assumptions separate. Open a report to see peak times, the cost breakdown, and the stocks/shares open at a chosen time. All values are INR. Basket allocation is Rs 11 lakh per strategy; entry limit is Rs 1 lakh per stock/trade. Peak capital is concurrent entry notional, not turnover or required broker margin.</p><p><a href='capital_risk_metrics.csv'>Download every metric</a> · <a href='capital_trade_timeline.csv'>Exact modeled fill-time open positions/capital</a> · <a href='portfolio_mtm_timeline.csv'>Bar-close portfolio P&amp;L/drawdown</a> · <a href='brokerage_breakdown.csv'>Brokerage/tax breakdown for all fills</a></p><input id='search' placeholder='Filter by strategy ID or path'><table id='metrics'><thead><tr><th>Strategy</th><th>Path</th><th>Trades</th><th>Brokerage</th><th>Total charges</th><th>Peak capital</th><th>Max open trades</th><th>Max bar-close DD</th><th>Biggest winning trade</th><th>Biggest losing trade</th></tr></thead><tbody>{table}</tbody></table>"""
    script = "<script>document.querySelector('#search').oninput=e=>document.querySelectorAll('#metrics tbody tr').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(e.target.value.toLowerCase())?'':'none')</script>"
    (OUT / "capital_overview.html").write_text(
        document("Capital and risk comparison", body, script), encoding="utf-8"
    )
    index = (OUT / "index.html").read_text(encoding="utf-8")
    index = re.sub(r"<!-- capital link -->.*?<!-- /capital link -->", "", index, flags=re.S)
    index = index.replace(
        "<h2>Best observed",
        "<!-- capital link --><p><a href='capital_overview.html'>NEW: brokerage, capital, max profit/loss and open trades at any time</a></p><!-- /capital link --><h2>Best observed",
        1,
    )
    (OUT / "index.html").write_text(index, encoding="utf-8")
    validation = {
        "status": "passed",
        "strategy_path_metrics": len(rows),
        "timeline_rows": len(timeline_rows),
        "mtm_rows": len(equity_rows),
        "fills_with_fee_breakdown": len(fee_rows),
        "existing_fees_peak_notional_drawdown_reconciled": True,
    }
    (OUT / "capital_validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps(validation), flush=True)


if __name__ == "__main__":
    main()
