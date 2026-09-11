"""Render an existing scanner snapshot; no broker calls or credentials."""
import argparse
import csv
import html
import json
from pathlib import Path


TABS = [('volume_shockers', 'Volume shockers'), ('top_gainers', 'Top gainers'),
        ('top_losers', 'Top losers')]


def number(value, decimals=2, signed=False):
    if value is None:
        return 'N/A'
    return format(value, f'{"+" if signed else ""},.{decimals}f')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(encoding='utf-8'))
    if data['state'] != 'completed':
        raise ValueError('A completed scanner snapshot is required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    esc = lambda value: html.escape(str(value))
    lookback = data['options']['lookback_days']
    sections, links = [], []
    for key, label in TABS:
        rows = data[key]
        exported, body = [], []
        for rank, row in enumerate(rows, 1):
            vol_change = (row['volume'] / row['average_volume'] - 1) * 100 if row['average_volume'] else None
            record = dict(row, rank=rank, volume_change_percent=vol_change)
            exported.append(record)
            color = 'up' if row['change_percent'] > 0 else 'down' if row['change_percent'] < 0 else ''
            body.append(f'''<tr><td>{rank}</td><td class="stock"><b>{esc(row['symbol'])}</b><small>{esc(row['name'])}</small></td>
<td>{number(row['ltp'])}</td><td class="{color}">{number(row['change_percent'], signed=True)}%</td>
<td>{number(row['volume'], 0)}</td><td>{number(row['average_volume'], 0)}</td>
<td>{number(vol_change, signed=True)}{'%' if vol_change is not None else ''}</td>
<td>{number(row['rvol'])}{'x' if row['rvol'] is not None else ''}</td>
<td>{esc(row['last_trade_at'][11:19])}</td></tr>''')
        csv_path = args.output.with_name(key + '.csv')
        if exported:
            with csv_path.open('w', newline='', encoding='utf-8-sig') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(exported[0]))
                writer.writeheader()
                writer.writerows(exported)
        links.append(f'<button type="button" data-target="{key}" aria-pressed="false">{label} <span>{len(rows)}</span></button>')
        sections.append(f'''<section id="{key}"><div class="section-head"><h2>{label}</h2><a href="{key}.csv">Download CSV</a></div>
<p>Top {len(rows)} of {data['matching_counts'][key]:,} qualifying instruments in the scanned universe.</p>
<div class="scroll"><table><thead><tr><th>#</th><th>Stock</th><th>LTP ₹</th><th>Day change</th><th>Today's volume</th><th>{lookback}-session avg volume</th><th>Volume change</th><th>RVOL</th><th>Last trade IST</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div><p class="empty" hidden>No matching stocks in these top-50 rows.</p></section>''')
    issues = {}
    for item in data.get('issues', []):
        issues[item['reason']] = issues.get(item['reason'], 0) + 1
    coverage = '; '.join(f'{value} {key.replace("_", " ")}' for key, value in sorted(issues.items())) or 'No reported exclusions'
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Today's NSE market scanner</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0c111b;color:#e7edf8;font:15px system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:32px 24px}h1{font-size:clamp(26px,4vw,40px);letter-spacing:-.04em;margin:8px 0}h2{font-size:23px;margin:0}
p{line-height:1.6;color:#aab8ce}.eyebrow{text-transform:uppercase;font-size:12px;letter-spacing:.15em;color:#64d5cb}.meta{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}.meta div{background:#141e2c;border:1px solid #263448;border-radius:12px;padding:16px;min-width:180px}.meta strong{display:block;font-size:24px}.meta small{color:#aab8ce}
nav{display:flex;gap:10px;flex-wrap:wrap;margin:28px 0 16px}button,input{font:inherit;border-radius:8px;border:1px solid #35455e;background:#141e2c;color:#e7edf8;padding:12px 16px}button{cursor:pointer}button[aria-pressed=true]{background:#184b4a;border-color:#64d5cb}button span{margin-left:8px;color:#aab8ce}input{width:min(100%,380px);margin-bottom:24px}:focus-visible{outline:2px solid #64d5cb;outline-offset:3px}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:20px}a{color:#82c6ff}.scroll{overflow:auto;border:1px solid #263448;border-radius:12px}table{width:100%;border-collapse:collapse;white-space:nowrap;font-variant-numeric:tabular-nums}th,td{padding:13px 16px;text-align:right;border-bottom:1px solid #223046}th{background:#182334;font-size:12px;color:#aab8ce}th:nth-child(2),.stock{text-align:left}tr:last-child td{border:0}tbody tr:hover{background:#141e2c}.stock small{display:block;font-size:11px;color:#8e9fb9;max-width:230px;overflow:hidden;text-overflow:ellipsis;margin-top:4px}.up{color:#72e3ab}.down{color:#ff939c}footer{margin-top:28px;font-size:13px}.notice{border-left:3px solid #d4af64;padding-left:16px}section[hidden]{display:none}@media(max-width:600px){main{padding:20px 12px}.meta{gap:8px}.meta div{min-width:130px;flex:1}}
</style></head><body><main>'''
    page += f'''<div class="eyebrow">Fyers · NSE EQ · Intraday snapshot</div><h1>Today's market movers</h1>
<p>{esc(data['session_date'])} · Scan completed {esc(data['completed_at'][11:19])} IST · Snapshot; refresh requires another scan.</p>
<div class="meta"><div><strong>{data['total']:,}</strong><small>Instruments scanned</small></div><div><strong>{data['valid_quotes']:,}</strong><small>Valid current-day quotes</small></div><div><strong>{data['valid_baselines']:,}</strong><small>Usable volume baselines</small></div></div>
<p class="notice">Coverage: {'partial' if data['partial'] else 'complete'}. {esc(coverage)}. The broker's EQ universe may include ETFs.</p>
<nav aria-label="Scanner lists">{''.join(links)}</nav><label for="search" hidden>Search displayed stocks</label><input id="search" type="search" aria-label="Search displayed stocks" placeholder="Search name or symbol in top 50…">
{''.join(sections)}
<footer><p>Day change = (LTP / previous trading-session close − 1) × 100. Volume change = (today's cumulative volume / prior {lookback} completed-session average − 1) × 100. RVOL uses the same volume baseline; 2.5x = +150%.</p>
<p>Volume compares today's partial cumulative trading with historical full days. It is not adjusted for time of day. Missing baselines show N/A. Quotes arrive in batches, so rows are not simultaneous. All timestamps are IST. No price sparklines are shown because this snapshot contains no intraday price series.</p></footer>'''
    page += '''</main><script>
const buttons=[...document.querySelectorAll('nav button')], sections=[...document.querySelectorAll('section')], search=document.querySelector('#search');
function filter(){sections.forEach(s=>{let visible=0;s.querySelectorAll('tbody tr').forEach(r=>{r.hidden=!r.querySelector('.stock').textContent.toLowerCase().includes(search.value.toLowerCase());if(!r.hidden)visible++;});s.querySelector('.empty').hidden=visible!==0;});}
function select(id){buttons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.target===id)));sections.forEach(s=>s.hidden=s.id!==id);filter();}
buttons.forEach(b=>b.addEventListener('click',()=>select(b.dataset.target)));search.addEventListener('input',filter);select('volume_shockers');
</script></body></html>'''
    args.output.write_text(page, encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
