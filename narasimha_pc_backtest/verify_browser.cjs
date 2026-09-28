const fs=require('fs'),path=require('path');
const {chromium}=require('../frontend/node_modules/@playwright/test');
(async()=>{
 const artifacts=path.join(__dirname,'artifacts');fs.mkdirSync(artifacts,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1500,height:1050}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8782',{waitUntil:'load',timeout:60000});
  await page.waitForFunction(()=>document.querySelectorAll('#cards .card').length===6);
  if(!await page.locator('#tradeCount').innerText().then(s=>s.includes('56,701')))throw Error('Wrong default trade count');
  for(const id of ['equity','drawdown','period','stocks']) if(!await page.locator('#'+id).evaluate(n=>!!n._fullLayout))throw Error('Missing plot '+id);
  if(await page.locator('#stocks').evaluate(n=>n._fullLayout.xaxis.type)!=='category')throw Error('Stock chart axis must contain symbols');
  await page.screenshot({path:path.join(artifacts,'dashboard.png'),fullPage:true});
  await page.locator('#path').selectOption('OHLC');
  if(!await page.locator('#tradeCount').innerText().then(s=>s.includes('57,239')))throw Error('Path filter failed');
  await page.locator('#symbol').selectOption('SBIN');
  await page.locator('#start').fill('2026-09-01');await page.locator('#start').dispatchEvent('change');
  await page.locator('#end').fill('2026-09-24');await page.locator('#end').dispatchEvent('change');
  if(!await page.locator('#tradeCount').innerText().then(s=>s.includes('14 matching')))throw Error('Date/symbol filter failed');
  for(const group of ['year','day','month']){await page.locator('#group').selectOption(group);if(!await page.locator('#period').evaluate(n=>n.data[0].x.length>0))throw Error('Grouping failed');}
  await page.locator('#trades button').first().click();
  await page.waitForFunction(()=>document.querySelector('#tradeChart').data?.[0]?.type==='candlestick');
  const candles=await page.locator('#tradeChart').evaluate(n=>n.data[0].x.length);
  if(candles!==375)throw Error('Wrong session candles '+candles);
  if(await page.locator('#tradeChart').evaluate(n=>n._fullLayout.height)<500)throw Error('Trade plot height too small');
  const firstHA=await page.locator('#tradeChart').evaluate(n=>n.data[0].open[0]);
  await page.locator('#candleType').selectOption('raw');
  if(await page.locator('#tradeChart').evaluate(n=>n.data[0].name)!=='Market OHLC')throw Error('Raw toggle failed');
  await page.locator('#tradePanel').screenshot({path:path.join(artifacts,'trade-chart.png')});
  await page.locator('#reset').click();await page.locator('#next').click();
  if(!await page.locator('#page').innerText().then(s=>s.startsWith('Page 2')))throw Error('Pagination failed');
  const bad=await page.request.get('http://127.0.0.1:8782/api/candles?symbol=..&date=2026-09-24');if(bad.status()!==400)throw Error('Unknown symbol accepted');
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));
  await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+2);
  await page.screenshot({path:path.join(artifacts,'mobile.png'),fullPage:false});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw Error('Mobile horizontal overflow');
  if(errors.length)throw Error(errors.join('\n'));
  const result={status:'PASSED',checks:['both paths','symbol/date filters','all period groups','four summary charts','HA/raw trade candles','375-minute session','pagination','invalid API symbol','mobile layout'],pageErrors:errors,firstHA};
  fs.writeFileSync(path.join(artifacts,'browser-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
