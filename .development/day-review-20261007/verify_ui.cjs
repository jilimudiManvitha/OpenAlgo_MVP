const path=require('node:path'),fs=require('node:fs'),{pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'../..');
const {chromium,expect}=require(path.join(root,'frontend/node_modules/@playwright/test'));
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});try{
 const page=await browser.newPage({viewport:{width:1728,height:1080}}),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.goto(pathToFileURL(path.join(root,'backtesting/all_strategies_2026-10-07.html')).href);
 await expect(page.getByRole('heading',{name:'Strategy journal',exact:true})).toBeVisible();
 await expect(page.locator('#strategy option')).toHaveCount(29);
 for(const scenario of ['OLHC','OHLC']){
  await page.locator('#path').selectOption(scenario);
  const check=await page.evaluate(()=>({actual:window.reportState.metrics,expected:JSON.parse(document.getElementById('data').textContent).scenarios[window.reportState.path]}));
  for(const [a,b]of [['net','net_pnl'],['gross','gross_pnl'],['trades','trades'],['wins','wins'],['losses','losses'],['fees','charges'],['peak','peak_capital'],['open','open_trades'],['total','total_net']]){
    if(Math.abs(check.actual[a]-check.expected[b])>.01)throw Error(`${scenario}: ${a} mismatch`);
  }
 }
 await page.locator('#path').selectOption('OLHC');
 const out=path.join(root,'log/test/day-review-20261007/screenshots');fs.mkdirSync(out,{recursive:true});
 await page.screenshot({path:path.join(out,'journal-desktop.png'),fullPage:false});
 await page.locator('#strategy').selectOption('weekday_fixed');
 await expect(page.locator('#scope')).toContainText('1 strategies');
 const symbol=await page.evaluate(()=>{const d=JSON.parse(document.getElementById('data').textContent);return d.results.find(r=>r.strategy==='weekday_fixed'&&r.path==='OLHC').trades[0].symbol});
 await page.locator('#symbol').selectOption(symbol);
 const one=await page.evaluate(()=>window.reportState.metrics);
 if(one.entries<1||one.trades<1)throw Error('filtered ledger empty');
 await page.locator('#selectedDay').click();
 await page.locator('#detailGroups details details').first().locator('summary').first().click();
 await expect(page.locator('#detailGroups table').first()).toBeVisible();
 await page.screenshot({path:path.join(out,'stock-detail.png'),fullPage:false});
 await page.locator('#dailyButton').click();await expect(page.locator('#dailyEntry')).toBeVisible();
 await expect(page.locator('#calendarGrid')).toBeHidden();
 await page.locator('#calendarButton').click();await expect(page.locator('#calendarGrid')).toBeVisible();
 await page.locator('#reset').click();
 await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:path.join(out,'journal-mobile.png'),fullPage:false});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('horizontal page overflow');
 await page.locator('#strategy').selectOption('nifty500_short_fixed');
 await expect(page.locator('#scope')).toContainText('1 strategies');
 await page.locator('#selectedDay').click();
 await page.screenshot({path:path.join(out,'short-mobile.png'),fullPage:false});
 if(errors.length)throw Error(errors.join('\n'));
 if(requests.some(u=>/^https?:/.test(u)))throw Error('report fetched external assets');
 console.log(JSON.stringify({desktop:true,mobile:true,pathTotalsMatch:true,filters:true,calendar:true,ledger:true,jsErrors:errors,externalRequests:0}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
