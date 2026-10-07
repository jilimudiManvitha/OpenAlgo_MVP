"""Build one self-contained HTML: all strategy results, operational review and limits."""

import csv
import gzip
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from plotly.offline import get_plotlyjs

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
IST = ZoneInfo("Asia/Kolkata")


def load(name):
    return json.loads((OUT / name).read_text())


def stamp(value):
    return (
        datetime.fromtimestamp(value, IST).isoformat() if isinstance(value, (int, float)) else value
    )


def build():
    audit = load("audit.json")
    paper = {r["strategy_id"]: r for r in load("inputs/paper_reports.json")}
    selection = load("inputs/selection.json")
    manifest = load("inputs/manifest.json")
    coverage = {
        "option_contracts_requested": len(manifest["contracts"]),
        "option_contracts_with_candles": 0,
        "option_contracts_without_candles": 0,
    }
    for filename in (OUT / "inputs/options/candles").glob("*.json.gz"):
        with gzip.open(filename, "rt") as f:
            archive = json.load(f)
        if archive["broker_symbol"] == "NSE:NIFTY50-INDEX":
            continue
        coverage[
            "option_contracts_with_candles"
            if archive["candles"]
            else "option_contracts_without_candles"
        ] += 1
    assert (
        coverage["option_contracts_requested"]
        == coverage["option_contracts_with_candles"] + coverage["option_contracts_without_candles"]
    )
    with gzip.open(ROOT / manifest["spot_files"][0], "rt") as f:
        spot = json.load(f)["candles"]
    prices = [
        r
        for r in spot
        if "09:15" <= datetime.fromtimestamp(r["timestamp"], IST).strftime("%H:%M") <= "15:39"
    ]
    stock_prices = [
        r
        for r in prices
        if datetime.fromtimestamp(r["timestamp"], IST).strftime("%H:%M") <= "15:00"
    ]

    def benchmark(rows):
        high = rows[0]["close"]
        dd = 0
        for r in rows:
            high = max(high, r["close"])
            dd = min(dd, (r["close"] / high - 1) * 100)
        return {
            "return_pct": (rows[-1]["close"] / rows[0]["close"] - 1) * 100,
            "drawdown_pct": dd,
            "first": rows[0]["close"],
            "last": rows[-1]["close"],
            "start": stamp(rows[0]["timestamp"]),
            "end": stamp(rows[-1]["timestamp"]),
        }

    benchmarks = {"Stocks": benchmark(stock_prices), "Options": benchmark(prices)}
    scenarios = []
    for result in load("stocks.json"):
        m = result["metrics"]
        running = high = 0
        curve = []
        for trade in sorted(result["trades"], key=lambda t: t["exit_ts"]):
            running += trade["net_pnl"]
            high = max(high, running)
            curve.append(
                {"timestamp": stamp(trade["exit_ts"]), "pnl": running, "drawdown": running - high}
            )
        scenarios.append(
            {
                "key": result["strategy"],
                "name": result["name"],
                "family": "Stocks",
                "path": result["path"],
                "net": m["net_pnl"],
                "realized": m["net_pnl"],
                "fees": m["charges"],
                "return_pct": m["return_on_peak_capital"],
                "capital": m["peak_capital"],
                "capital_label": "Peak concurrent notional",
                "drawdown": m["realized_drawdown"],
                "drawdown_label": "Realized-trade drawdown",
                "trades": m["trades"],
                "trade_label": "Closed trades",
                "open": m["open_trades"],
                "win_rate": m["win_rate"] if m["trades"] else None,
                "profit_factor": m["profit_factor"],
                "coverage": f"{sum(c['eligible'] for c in result['coverage'])}/{len(result['coverage'])} symbols",
                "exclusions": [c for c in result["coverage"] if not c["eligible"]],
                "curve": curve,
                "ledger": [
                    {**t, "entry_ts": stamp(t["entry_ts"]), "exit_ts": stamp(t["exit_ts"])}
                    for t in result["trades"]
                ],
                "method": "09:15–15:00 IST; ₹10,000 per entry; final ranked scanner basket / Tuesday watchlist applied retrospectively. 5 bps adverse slippage per side plus illustrative 5 bps turnover charges. No combined capital cap. OLHC/OHLC with 8 samples per segment; modeled uniform volume.",
            }
        )
    details = {p: load("options/" + p + "/details.json") for p in ("OLHC", "OHLC")}
    for summary in load("options/summary.json"):
        key, path = summary["strategy"], summary["path"]
        d = details[path]
        legs = d["trades"][key]
        state = d["states"][key]
        curve = d["curves"][key]
        grouped = defaultdict(list)
        for leg in legs:
            leg["net_pnl"] = leg["gross_pnl"] - leg["entry_fee"] - leg["exit_fee"]
            grouped[leg["cycle"]].append(leg)
        cycles = [
            {
                "cycle": cycle,
                "net_pnl": sum(leg["net_pnl"] for leg in ll),
                "closed_legs": len(ll),
                "complete": not (state["legs"] and cycle == state["cycle"]),
            }
            for cycle, ll in grouped.items()
        ]
        gains = [c["net_pnl"] for c in cycles if c["complete"]]
        losses = -sum(min(n, 0) for n in gains)
        high = summary["capital"]
        cc = []
        for row in curve:
            high = max(high, row["equity"])
            cc.append(
                {
                    "timestamp": row["timestamp"],
                    "pnl": row["equity"] - summary["capital"],
                    "drawdown": row["equity"] - high,
                }
            )
        scenarios.append(
            {
                "key": key,
                "name": key.replace("_", " ").title(),
                "family": "Options",
                "path": path,
                "net": summary["net_pnl"],
                "realized": summary["realized_pnl"],
                "fees": summary["fees"],
                "return_pct": summary["return_pct"],
                "capital": summary["capital"],
                "capital_label": "Allocated capital",
                "drawdown": abs(summary["max_drawdown_inr"]),
                "drawdown_label": "Minute-end MTM drawdown",
                "trades": len(gains),
                "trade_label": "Completed cycles",
                "closed_legs": summary["closed_legs"],
                "open": summary["open_legs"],
                "win_rate": 100 * sum(n > 0 for n in gains) / len(gains) if gains else None,
                "profit_factor": sum(max(n, 0) for n in gains) / losses if losses else None,
                "coverage": f"{summary['closed_legs']} closed / {summary['open_legs']} open legs",
                "exclusions": d["skipped"][key],
                "curve": cc,
                "ledger": legs,
                "cycles": cycles,
                "open_legs": state["legs"],
                "method": "Fresh single-session simulation from cash, not the actual blocked run and not an overnight carry reconstruction. Decisions use prior completed minute; fills use following open. Greeks inferred from observed option prices; historical margin and costs estimated. ₹20 lakh allocated per strategy; 0.1% turnover + ₹20 per fill, ₹0.05 adverse slippage. Next-week positional legs can remain open at 15:39; net includes their closing marks.",
            }
        )
    assert len(scenarios) == 40 and len({r["key"] for r in scenarios}) == 20
    for s in scenarios:
        p = paper[s["key"]]
        s["paper"] = {
            k: p.get(k)
            for k in (
                "status",
                "updated_at",
                "metrics",
                "streaming_symbols",
                "ready_symbols",
                "note",
            )
        }
        s["paper"]["stale"] = p["status"] == "running"
        s["paper"]["recorded_trades"] = len(p["trades"])
        s["paper"]["ledger"] = [
            {
                **t,
                "entry_ts": stamp(t["entry_ts"]),
                "exit_ts": stamp(t["exit_ts"]) if t.get("exit_ts") else None,
            }
            for t in p["trades"]
        ]
        s["benchmark"] = benchmarks[s["family"]]
    payload = {
        "day": "2026-10-06",
        "scenarios": scenarios,
        "archive_coverage": coverage,
        "audit": {k: v for k, v in audit.items() if k != "orders"},
        "selection": {k: v for k, v in selection.items() if k != "stocks"},
        "benchmarks": benchmarks,
        "order_counts": dict(
            __import__("collections").Counter(o["strategy"] for o in audit["orders"])
        ),
    }
    (OUT / "report_data.json").write_text(json.dumps(payload, allow_nan=False, indent=2))
    with (OUT / "summary.csv").open("w", newline="") as f:
        cols = [
            "key",
            "family",
            "path",
            "net",
            "realized",
            "fees",
            "return_pct",
            "capital",
            "drawdown",
            "trades",
            "trade_label",
            "closed_legs",
            "open",
            "win_rate",
            "profit_factor",
            "coverage",
        ]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(scenarios)
    data = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    page = TEMPLATE.replace("__PLOTLY__", get_plotlyjs()).replace("__DATA__", data)
    (OUT / "index.html").write_text(page)
    print(
        json.dumps(
            {
                "html": str(OUT / "index.html"),
                "strategies": 20,
                "scenarios": 40,
                "bytes": len(page.encode()),
                "stock_positive_both": [
                    s["key"]
                    for s in scenarios
                    if s["path"] == "OLHC"
                    and s["net"] > 0
                    and next(t for t in scenarios if t["key"] == s["key"] and t["path"] == "OHLC")[
                        "net"
                    ]
                    > 0
                ],
            },
            indent=2,
        )
    )


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>All 20 Scheduled Strategies — 6 October 2026</title>
<style>:root{color-scheme:dark;--bg:#0b1220;--card:#121e31;--muted:#9bacc4;--border:#28394f;--blue:#69b8ff;--green:#63dfae;--red:#ff899a;--amber:#ffd181}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#e9f0fa;font:15px/1.55 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:30px 24px 70px}h1{font-size:clamp(25px,4vw,42px);line-height:1.15;margin:10px 0}h2{font-size:23px}h3{font-size:17px}p{color:var(--muted)}.eyebrow{font-size:12px;letter-spacing:.15em;color:var(--blue)}.sub{max-width:1000px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.card,section.panel{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px}.big{display:block;font-size:28px;font-weight:700}.label{color:var(--muted);font-size:12px}.alert{background:#312335;border:1px solid #815464;border-radius:12px;padding:16px 20px;margin:16px 0}.alert strong{color:var(--red)}.note{background:#252436;border-left:3px solid var(--amber);padding:14px 18px}.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin:18px 0}.toolbar label{min-width:0;max-width:100%;display:flex;flex-direction:column;gap:4px;color:var(--muted);font-size:12px}button,select,input{min-width:0;max-width:100%;font:inherit;background:#17263d;color:#e9f0fa;border:1px solid #3c536e;border-radius:7px;padding:9px 12px}button{cursor:pointer}button.active{border-color:var(--blue);background:#234769}a{color:var(--blue)}.scroll{overflow:auto;border:1px solid var(--border);border-radius:10px;max-width:100%}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px 12px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap}th{color:var(--muted);background:#17263a;position:sticky;top:0}th:first-child,td:first-child{text-align:left}td:first-child{white-space:normal;min-width:230px}tr.pick:hover{background:#1c304b;cursor:pointer}.pos{color:var(--green)}.neg{color:var(--red)}.muted{color:var(--muted)}.badge{font-size:11px;display:inline-block;border:1px solid #3b506b;border-radius:20px;padding:2px 8px;margin-left:6px}.charts{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:14px}.chart{min-height:300px;width:100%;min-width:0}.panel{margin-top:22px}details{margin:16px 0}summary{cursor:pointer;color:#dfeaff}.findings{display:grid;grid-template-columns:1fr 1fr;gap:14px}.findings article{padding:16px;border:1px solid var(--border);border-radius:10px}.findings p{margin:8px 0}.logline{font:12px/1.5 ui-monospace,monospace;overflow-wrap:anywhere;color:var(--muted)}#detail{scroll-margin-top:15px}.foot{font-size:12px;margin-top:25px;color:var(--muted)}@media(max-width:800px){main{padding:20px 12px}.cards{grid-template-columns:repeat(2,1fr)}.charts,.findings{grid-template-columns:minmax(0,1fr)}.card,section.panel{padding:15px}.toolbar select{max-width:100%}.big{font-size:22px}}@media print{button,.toolbar{display:none}body{background:white;color:black}.panel,.card{break-inside:avoid}}</style>
<script>__PLOTLY__</script></head><body><main><div class="eyebrow">OPENALGO · SESSION REVIEW + HISTORICAL REPLAY</div><h1>20 scheduled strategies.<br>One session, fully separated results.</h1><p class="sub">Tuesday, 6 October 2026 · IST · Eight stock strategies and twelve NIFTY option strategies. Actual saved paper activity is shown separately from modeled historical results. This file works offline.</p>
<div class="cards"><div class="card"><span class="label">SCHEDULES STARTED</span><span class="big">20 / 20</span><span class="label">All scheduled at 09:15</span></div><div class="card"><span class="label">OPTION STRATEGIES BLOCKED</span><span class="big neg">12 / 12</span><span class="label">Feed setup never completed; zero entries</span></div><div class="card"><span class="label">STALE STOCK REPORTS</span><span class="big neg">6</span><span class="label">62 trades still marked open in saved reports</span></div><div class="card"><span class="label">SANDBOX POSITIONS NOW</span><span class="big">0</span><span class="label">57 AUTO_SQUARE_OFF orders recorded</span></div></div>
<div class="alert"><strong>Today's scheduled run had errors.</strong> Subscription capacity, handshake failures and connection outages blocked all option entries. Seven stock strategies recorded trades. The Nifty500 5-minute trailing strategy recorded none. Six stock reports are stale, so their saved P&L must not be treated as final session P&L.</div>
<section class="panel"><h2>Strategy-by-strategy backtest</h2><p>These scenarios estimate how the saved rules behaved on today's historical candles with uninterrupted data. They do not recover trades that the live runners missed. Switch the modeled intraminute path; the two paths are alternatives and must never be added.</p><div class="toolbar"><label>Intraminute path<select id="path"><option>OLHC</option><option>OHLC</option></select></label><label>Family<select id="family"><option>All</option><option>Stocks</option><option>Options</option></select></label><label>Find a strategy<input id="search" placeholder="e.g. premium or 5m"></label><button id="csv">Download visible summary CSV</button></div><p id="scope" class="label"></p><div class="scroll"><table><thead><tr><th>Strategy</th><th>Net / MTM ₹</th><th>Return %</th><th>Drawdown ₹</th><th>Closed trades / cycles</th><th>Win %</th><th>Profit factor</th><th>Open legs</th><th>Saved paper run</th></tr></thead><tbody id="overview"></tbody></table></div><p class="label">Stock returns use peak concurrent notional; option returns use ₹20 lakh allocated capital. Stock drawdown is realized-trade drawdown; option drawdown uses minute-end equity. These are independent simulations, not a combined portfolio.</p></section>
<section class="panel" id="detail"><div class="toolbar"><label>Strategy details<select id="strategy"></select></label></div><h2 id="strategyName"></h2><p id="method"></p><div id="stats" class="cards"></div><div class="charts"><div id="equity" class="chart"></div><div id="dd" class="chart"></div></div><div id="benchmark" class="note"></div><h3>Today's recorded paper activity</h3><p id="actual"></p><details><summary>Backtest trade / leg ledger</summary><button id="ledgerCsv">Download this ledger CSV</button><div class="scroll" style="max-height:480px"><table><thead id="ledgerHead"></thead><tbody id="ledger"></tbody></table></div></details><details><summary>Open simulated option legs and skipped decisions / exclusions</summary><pre id="gaps" class="logline"></pre></details><details><summary>Saved paper ledger (may be stale)</summary><div class="scroll" style="max-height:400px"><table><thead id="paperHead"></thead><tbody id="paperLedger"></tbody></table></div></details></section>
<section class="panel"><h2>Operational findings from today's logs</h2><div class="findings"><article><h3>1. Option subscription capacity exhausted</h3><p>Each option runner required 961 subscriptions. Logs repeatedly show the shared pool full at 3 connections × 1,000 symbols. All twelve retained missing subscriptions and their 09:30–09:31 entry window elapsed.</p><p>Repair implemented locally: cap FYERS scanner streaming at 1,000 symbols (full-universe REST polling continues), subscribe each flat option profile to its required expiry, preserve active-cycle chains, and stagger runner connections. 139 focused tests pass, including the real pool allocator offline. The scanner cap needs a user-controlled OpenAlgo restart. Live session recovery remains unverified; retrying alone cannot create capacity.</p></article><article><h3>2. Transport disruptions</h3><p>Handshake timeouts, FYERS HSM connection failures, connection resets, DNS resolution errors and ping/pong timeouts occurred. Some stock runners recovered and traded; the 5-minute Nifty500 trailing runner recorded no trades.</p><p>Review both upstream network stability and reconnect/subscription recovery. A no-trade result here is not proof that no strategy signal occurred.</p></article><article><h3>3. Stock reports were not finalized</h3><p>Six reports retain “running” and pre-15:00 update timestamps, with 62 trades marked open. Logs contain later closing fills; Sandbox has zero remaining positions and 57 auto-square-off orders.</p><p>The scheduler has a three-second graceful termination window before killing surviving processes. Slow square-off / worker shutdown is a plausible contributor, not a proven cause from retained logs alone. Final fills need explicit report reconciliation.</p></article><article><h3>4. Additional recorded errors</h3><p>A Sandbox MCX square-off attempt reported “Missing required field: quantity.” There are also subscription-release mismatch errors. These require targeted follow-up; the empty current position table does not explain the original MCX request.</p><p>The main JSON error log retains only 1,000 entries, covering 15:15:17–17:27:14. Morning evidence comes from the twenty dated strategy logs. Counts below are retained log entries, not unique incidents.</p></article></div><details open><summary>Errors by scheduled strategy</summary><div class="scroll"><table><thead><tr><th>Strategy</th><th>Handshake</th><th>Capacity rejection lines</th><th>History reset</th><th>Ack timeout</th><th>HSM failure</th></tr></thead><tbody id="logSummary"></tbody></table></div></details><details><summary>Retained application error groups</summary><div id="appErrors"></div></details><details><summary>Evidence: source file, line number and example</summary><div id="evidence"></div></details></section>
<section class="panel"><h2>Portfolio review: what remains?</h2><p>The agreed implementation is complete locally: all requested asset classes, liabilities, dated CSV pricing, nine reports, FIFO alongside weighted-average holdings, categorized watchlists and existing-Sandbox paper GTT integration. Verification from today's development work passed 59 portfolio backend tests, 113 existing GTT tests, 20 frontend tests, plus desktop/mobile browser checks.</p><div class="note"><strong>October 7 update: combined local build is ready for user startup.</strong> At the user’s request, the normal frontend was rebuilt while OpenAlgo was stopped and verified on isolated port 5011. The user starts OpenAlgo and logs into the broker before the scheduled session. Market-hour operational acceptance remains. No production portfolio records or example orders were created.</div><p>Current boundaries remain deliberate: manual/CSV NAV for non-stock assets; explicit “Refresh triggers & import confirmed fills” for paper-ledger reconciliation; tracking-only watch thresholds; no automatic SIP schedule; no tax filing computation or automatic broker-holdings import. These are future enhancements if wanted, not silently implemented features. Live GTT fills and reset preservation still need user-environment acceptance after deployment.</p></section>
<section class="panel"><h2>Data, method and reproducibility</h2><p id="archiveCoverage"></p><ul><li>FYERS one-minute history for 6 October, prior stock-candle warmup, dated end-of-session scanner snapshot and Tuesday watchlist. The scanner selection is retrospective and has selection bias; historical membership was not reconstructed. All 92 unique stock histories were available (77 scanner symbols and 23 watchlist symbols, with overlap).</li><li>Option scenarios use the current and next listed expiries, 6 and 13 October. Each simulation begins flat today; it does not reconstruct a carried positional portfolio from earlier sessions. Open next-week positions are marked, not forcibly sold. The three current-week positional profiles found no contract in their requested premium band at entry and therefore made no trade. These zero results reflect unavailable qualifying entries. The option benchmark ends at the last observed NIFTY index minute, 15:29; option marks continue to 15:39.</li><li>OLHC = open → low → high → close. OHLC = open → high → low → close. Neither path is observed tick data or a guaranteed best/worst bound. Short-lived breaches, spreads, queues, latency and slippage can differ in practice.</li><li>Stock costs: illustrative 5 bps turnover fees per fill and 5 bps adverse price movement per side. Option costs: illustrative 0.1% turnover plus ₹20 per fill and ₹0.05 adverse slippage. These are estimates, not a broker tax statement.</li><li>One session cannot support a reliable annualized Sharpe, Sortino or CAGR. They are unavailable, not zero. Benchmark is gross NIFTY 50 over the relevant intraday window; leverage and capital bases differ.</li><li>All report data and charts are embedded in this HTML. Supporting JSON, CSV, source data hashes and replay scripts remain beside it. No historical backtest was written into the application Reports database.</li></ul></section><p class="foot">Generated from local source snapshots and historical data. No orders were submitted. Production processes, databases and schedules were left untouched. The frontend was separately rebuilt on October 7 at the user’s request. Figures are modeled outcomes, not a prediction.</p>
</main><script id="reportData" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.getElementById('reportData').textContent), $=id=>document.getElementById(id), fmt=(n,d=2)=>n==null?'—':Number(n).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d}), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), tone=n=>n>0?'pos':n<0?'neg':'muted';
const unique=D.scenarios.filter(s=>s.path==='OLHC');$('strategy').innerHTML=unique.map(s=>`<option value="${esc(s.key)}">${esc(s.name)}</option>`).join('');
let selected=unique[0].key;
function current(){return D.scenarios.find(s=>s.key===selected&&s.path===$('path').value)}
function visible(){return D.scenarios.filter(s=>s.path===$('path').value&&($('family').value==='All'||s.family===$('family').value)&&s.name.toLowerCase().includes($('search').value.toLowerCase()))}
function actualLabel(s){return s.paper.stale?'Stale report':s.family==='Options'?'Blocked · no entry':s.paper.recorded_trades?'Recorded trades':'No trades / feed failure'}
function table(){const list=visible();$('scope').textContent=`${list.length} strategies · ${$('path').value} · Scanner ${D.selection.scanner.length} symbols / Tuesday ${D.selection.watchlist.length} symbols · Click a row for details`;$('overview').innerHTML=list.map(s=>`<tr class="pick" data-key="${esc(s.key)}"><td>${esc(s.name)}<br><span class="label">${s.family} · ${esc(s.coverage)}</span></td><td class="${tone(s.net)}">${fmt(s.net)}</td><td>${fmt(s.return_pct)}</td><td>${fmt(s.drawdown)}</td><td>${s.trades}<br><span class="label">${esc(s.trade_label)}</span></td><td>${fmt(s.win_rate,1)}</td><td>${fmt(s.profit_factor)}</td><td>${s.open}</td><td>${actualLabel(s)}</td></tr>`).join('');document.querySelectorAll('tr.pick').forEach(r=>r.onclick=()=>{selected=r.dataset.key;$('strategy').value=selected;detail();$('detail').scrollIntoView({behavior:'smooth'})})}
function ledgerTable(rows,head,body){const cols=['symbol','cycle','side','quantity','entry_ts','exit_ts','entry','exit','entry_fee','exit_fee','fees','net_pnl','reason'].filter(k=>rows.some(r=>r[k]!=null));$(head).innerHTML='<tr>'+cols.map(c=>'<th>'+esc(c.replaceAll('_',' '))+'</th>').join('')+'</tr>';$(body).innerHTML=rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c]??'—')+'</td>').join('')+'</tr>').join('')||'<tr><td>No recorded rows</td></tr>'}
function detail(){const s=current();$('strategyName').textContent=s.name+' · '+s.path;$('method').textContent=s.method;$('stats').innerHTML=[['Net / MTM P&L','₹'+fmt(s.net)],['Return',fmt(s.return_pct)+'%'],[s.capital_label,'₹'+fmt(s.capital)],[s.drawdown_label,'₹'+fmt(s.drawdown)]].map(([k,v])=>`<div class="card"><span class="label">${esc(k)}</span><span class="big">${esc(v)}</span></div>`).join('');const layout={paper_bgcolor:'#121e31',plot_bgcolor:'#121e31',font:{color:'#bacbe1'},margin:{t:38,r:16,b:45,l:70},xaxis:{type:'date',gridcolor:'#26364a'},yaxis:{gridcolor:'#26364a',tickprefix:'₹'},showlegend:false};const conf={responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']};Plotly.react('equity',[{x:s.curve.map(p=>p.timestamp),y:s.curve.map(p=>p.pnl),mode:'lines',line:{color:'#69b8ff',width:2},name:'Net P&L'}],{...layout,title:{text:s.family==='Stocks'?'Realized P&L by exit':'Minute-end net / MTM P&L',font:{size:14}}},conf);Plotly.react('dd',[{x:s.curve.map(p=>p.timestamp),y:s.curve.map(p=>p.drawdown),fill:'tozeroy',mode:'lines',line:{color:'#ff899a',width:1},name:'Drawdown'}],{...layout,title:{text:s.drawdown_label,font:{size:14}}},conf);const b=s.benchmark;$('benchmark').innerHTML=`<strong>Strategy ${fmt(s.return_pct)}% · NIFTY 50 gross ${fmt(b.return_pct)}%</strong><br>NIFTY ${fmt(b.first)} → ${fmt(b.last)} (${esc(b.start.slice(11,16))}–${esc(b.end.slice(11,16))} IST). Benchmark minute-close drawdown ${fmt(b.drawdown_pct)}%. Capital bases differ. Sharpe / Sortino: unavailable for one session.`;const pm=s.paper.metrics?.PAPER;$('actual').innerHTML=`<strong>${esc(actualLabel(s))}</strong> · Saved status: ${esc(s.paper.status)}<br>Updated ${esc(s.paper.updated_at)}. Saved closed trades: ${pm?.trades??0}; saved open trades: ${pm?.open_trades??0}; saved realized P&L: ₹${fmt(pm?.net_pnl)}. ${s.paper.stale?'<strong class="neg">This is an incomplete pre-close snapshot, not final P&L.</strong>':'Sandbox fills exclude brokerage.'}`;ledgerTable(s.ledger,'ledgerHead','ledger');ledgerTable(s.paper.ledger,'paperHead','paperLedger');$('gaps').textContent=JSON.stringify({open_legs:s.open_legs??[],completed_cycles:s.cycles??[],skipped_or_excluded:s.exclusions},null,2)}
function download(rows,name){const columns=[...new Set(rows.flatMap(Object.keys))];const cell=v=>{let t=String(v??'');if(/^[=+@]/.test(t)||(/^\s*-/.test(t)&&!/^\s*-?\d+(\.\d+)?$/.test(t)))t="'"+t;return '"'+t.replaceAll('"','""')+'"'};const text=[columns.map(cell).join(','),...rows.map(r=>columns.map(c=>cell(r[c])).join(','))].join('\r\n');const u=URL.createObjectURL(new Blob([text],{type:'text/csv'})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
$('csv').onclick=()=>download(visible().map(s=>({strategy:s.name,path:s.path,net_pnl:s.net,return_pct:s.return_pct,drawdown:s.drawdown,closed_trades_or_cycles:s.trades,win_rate:s.win_rate,profit_factor:s.profit_factor,open_legs:s.open,coverage:s.coverage})),'all-scheduled-20261006-'+$('path').value+'.csv');$('ledgerCsv').onclick=()=>download(current().ledger,current().key+'-'+current().path+'-ledger.csv');$('path').onchange=()=>{table();detail()};$('family').onchange=table;$('search').oninput=table;$('strategy').onchange=()=>{selected=$('strategy').value;detail()};
$('logSummary').innerHTML=D.audit.strategies.map(s=>`<tr><td>${esc(s.name)}</td>${['handshake_timeouts','capacity_rejections','history_connection_resets','subscription_ack_timeouts','hsm_connection_failures'].map(k=>'<td>'+s.counts[k]+'</td>').join('')}</tr>`).join('');$('appErrors').innerHTML=D.audit.application_errors.map(e=>`<p class="logline">${e.count} × ${esc(e.logger)} — ${esc(e.message)}</p>`).join('');$('evidence').innerHTML=D.audit.strategies.map(s=>`<h3>${esc(s.name)}</h3><p class="logline">${esc(s.log)}</p>${s.examples.map(e=>`<p class="logline">Line ${e.line}: ${esc(e.message)}</p>`).join('')}`).join('');$('archiveCoverage').textContent=`Option archive: ${D.archive_coverage.option_contracts_requested} contracts requested; ${D.archive_coverage.option_contracts_with_candles} returned candles; ${D.archive_coverage.option_contracts_without_candles} returned no candles. Empty contracts were not synthesized. Required held-leg prices and every completed ledger were checked during replay.`;table();detail();
</script></body></html>"""

if __name__ == "__main__":
    build()
