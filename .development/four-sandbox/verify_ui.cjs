// Local browser fixtures only: authenticating/mutating production APIs is not part of this test.
const path = require('node:path');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const { chromium, expect } = require(path.join(root, 'frontend/node_modules/@playwright/test'));
const reports = JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), ['-c',
  "import sqlite3,json; from contextlib import closing\nwith closing(sqlite3.connect('file:db/scanner_strategy_reports.db?mode=ro',uri=True)) as c:\n print(json.dumps([json.loads(r[0]) for r in c.execute(\"SELECT payload FROM reports WHERE id LIKE 'backtest-2026-09-29-%'\") if json.loads(r[0]).get('strategy_id') in ('nifty500_fixed','nifty500_trailing','weekday_fixed','weekday_trailing')]))"], { cwd: root, encoding:'utf8', maxBuffer:32*1024*1024 }));
(async()=>{
  const browser = await chromium.launch({channel:'chrome',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    await page.route('**/auth/session-status', r=>r.fulfill({json:{status:'success',logged_in:true,user:'fixture',broker:'fyers',active_sessions:1}}));
    await page.route('**/api/broker/capabilities', r=>r.fulfill({json:{status:'success',data:{broker_name:'fyers',broker_type:'IN_stock',supported_exchanges:['NSE']}}}));
    await page.route('**/auth/analyzer-mode', r=>r.fulfill({json:{status:'success',data:{analyze_mode:true}}}));
    await page.route('**/auth/csrf-token', r=>r.fulfill({json:{csrf_token:'fixture'}}));
    await page.route('**/market-scanner/api/**', r=>{
      const url = new URL(r.request().url());
      if(r.request().method()!=='GET') return r.abort();
      const id=decodeURIComponent(url.pathname.split('/').at(-1));
      const data=id==='reports'?reports.map(({id,day,kind,status})=>({id,day,kind,status})):reports.find(x=>x.id===id);
      return r.fulfill({json:{status:'success',data}});
    });
    await page.goto('http://127.0.0.1:5000/strategy-reports');
    await expect(page.getByRole('heading',{name:'Strategy Reports',exact:true})).toBeVisible();
    for(const report of reports){
      await page.getByLabel('Report session',{exact:true}).selectOption(report.id);
      for(const scenario of report.paths){
        await page.getByLabel('Execution scenario',{exact:true}).selectOption(scenario);
        await expect(page.locator('tbody tr')).toHaveCount(report.trades.filter(t=>t.path===scenario).length);
        await expect(page.locator('svg[role="img"]')).toHaveCount(1);
        await expect(page.locator('svg polyline')).toHaveCount(3);
      }
    }
    await page.getByLabel('Heikin Ashi candles').check();
    await page.getByLabel('Full session').check();
    const out=path.join(__dirname,'artifacts'); fs.mkdirSync(out,{recursive:true});
    await page.screenshot({path:path.join(out,'reports-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'reports-mobile.png'),fullPage:true});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('Mobile page overflow');
    if(errors.length) throw Error(errors.join('\n'));
    console.log(JSON.stringify({reports:reports.length,scenarios:8,indicatorLines:3,errors,auth:'mocked browser fixture; not a live authenticated check'}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
