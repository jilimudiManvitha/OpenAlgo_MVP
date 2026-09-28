const fs=require('fs'),path=require('path');
const {chromium}=require('../../frontend/node_modules/@playwright/test');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const folder=path.join(__dirname,'artifacts');fs.mkdirSync(folder,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1450,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8783');
  await page.waitForFunction(()=>document.querySelectorAll('#cards .card').length===6);
  for(const p of ['OLHC','OHLC']){
   await page.locator('#path').selectOption(p);
   if(!(await page.locator('#tradeCount').innerText()).includes('53'))throw Error('Trade total');
  }
  await page.screenshot({path:path.join(folder,'report.png'),fullPage:true});
  await page.locator('#trades button').first().click();
  await page.waitForFunction(()=>document.querySelector('#tradeChart').data?.[0]?.type==='candlestick');
  if(await page.locator('#tradeChart').evaluate(n=>n.data[0].x.length)<366)throw Error('Cutoff candles missing');
  await page.locator('#candleType').selectOption('raw');
  if(await page.locator('#tradeChart').evaluate(n=>n.data[0].name)!=='Market OHLC')throw Error('Raw toggle');
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(500);
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw Error('Mobile overflow');
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(folder,'browser.json'),JSON.stringify({status:'PASSED',checks:['both scenario totals','trade candle chart','raw toggle','mobile width'],errors},null,2));
  console.log('Report browser checks passed');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
