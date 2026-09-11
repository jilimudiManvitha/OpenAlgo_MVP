const {chromium, expect} = require('../../frontend/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const now = new Date().toISOString();
let price=110, enabled=true;
const baseRow=(i)=>({symbol:`TEST${String(i).padStart(2,'0')}`,name:`Fixture company ${i}`,exchange:'NSE',
  ltp:price, previous_close:100,change_percent:price-100,volume:250000,volume_change_percent:150,rvol:2.5,
  stale:false,last_trade_at:now,quote_fetched_at:now,baseline_status:'ready',
  sparkline:[[new Date(Date.now()-60000).toISOString(),105],[now,price]]});
const errors=[];
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/auth/csrf-token',r=>r.fulfill({json:{csrf_token:'fixture'}}));
    await page.route('**/market-scanner/api/**',async route=>{
      const req=route.request();
      if(req.method()==='POST'){
        const payload=req.postDataJSON(); if(typeof payload.enabled==='boolean') enabled=payload.enabled;
        return route.fulfill({json:{status:'success'}});
      }
      const category=new URL(req.url()).searchParams.get('category');
      const rows=Array.from({length:category==='nifty50'?2:50},(_,i)=>baseRow(i));
      return route.fulfill({json:{status:'success',data:{volume_shockers:rows,top_gainers:rows,
        top_losers:[{...baseRow(99),ltp:90,change_percent:-10}],enabled,broker:'fyers',
        categories:[{id:'nifty50',label:'Nifty 50',source:'ind_nifty50list.csv',effective_date:null}],
        options:{lookback_days:5},stale:false,market_open:true,updated_at:now,state:'completed',
        matching_counts:{volume_shockers:rows.length,top_gainers:rows.length,top_losers:1},
        valid_quotes:100,total:100,valid_baselines:100,filtered_quotes:100,timestamp_support:'native',
        membership:category==='nifty50'?{source:'ind_nifty50list.csv',effective_date:null}:null}}});
    });
    await page.goto('http://127.0.0.1:5187/scanner-preview.html');
    await expect(page.locator('tbody tr')).toHaveCount(50);
    await expect(page.locator('tbody tr').first()).toContainText('+10.00%');
    await expect(page.locator('tbody tr').first()).toContainText('+150.00%');
    await expect(page.locator('svg[role="img"]')).toHaveCount(50);
    price=120;
    await expect(page.locator('tbody tr').first()).toContainText('+20.00%',{timeout:10000});
    await page.getByLabel('Category',{exact:true}).selectOption('nifty50');
    await expect(page.locator('tbody tr')).toHaveCount(2);
    await expect(page.getByText('Membership: date unknown',{exact:false})).toBeVisible();
    await page.getByRole('tab',{name:/Volume Shockers/}).focus();
    await page.keyboard.press('End');
    await expect(page.getByRole('tab',{name:/Top Losers/})).toHaveAttribute('aria-selected','true');
    await expect(page.locator('tbody tr').first()).toContainText('-10.00%');
    await page.getByRole('button',{name:'Pause auto refresh'}).click();
    await expect(page.getByRole('button',{name:'Resume auto refresh'})).toBeVisible();
    const out=path.join(__dirname,'artifacts'); fs.mkdirSync(out,{recursive:true});
    await page.screenshot({path:path.join(out,'scanner-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'scanner-mobile.png'),fullPage:true});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('Page overflows mobile viewport');
    if(errors.length) throw Error(errors.join('\n'));
    fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify({passed:true,checks:[
      '50 rows','price and volume percentages','automatic price update','50 SVG charts',
      'category filtering','keyboard tabs','pause control','desktop/mobile rendering'],pageErrors:errors},null,2));
    console.log('PASS: 8 browser checks, 0 page errors');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
