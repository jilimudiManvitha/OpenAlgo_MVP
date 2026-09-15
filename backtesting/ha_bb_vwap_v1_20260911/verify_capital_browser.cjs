const path=require('path'),fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require(path.resolve(__dirname,'../../frontend/node_modules/@playwright/test'));
const out=path.join(__dirname,'results');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1200}}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(pathToFileURL(path.join(out,'capital_overview.html')).href);
  if(await page.locator('#metrics tbody tr').count()!==808)throw Error('Missing strategy/path metrics');
  await page.locator('#search').fill('S092');
  if(await page.locator('#metrics tbody tr:visible').count()!==2)throw Error('Search failed');
  let checks=0;
  for(const sid of ['S092','S109','S299','S305','S060']){
   await page.goto(pathToFileURL(path.join(out,'capital',sid+'.html')).href);
   await page.waitForFunction(()=>document.querySelector('#chart')?._fullLayout);
   for(const scenario of ['OLHC','OHLC']){
    await page.locator('#scenario').selectOption(scenario);
    for(const time of ['09:15:00','10:51:00','12:00:00','15:30:00']){
     await page.locator('#at').fill(time);
     const expected=await page.evaluate(({scenario,time})=>{
      const stamp=Date.parse('2026-09-11T'+time+'+05:30');
      return window.CAPITAL[scenario].timeline.filter(r=>Date.parse(r.time)<=stamp).at(-1).open_positions;
     },{scenario,time});
     const text=await page.locator('#snapshot').innerText();
     if(!text.includes(expected+' open trades'))throw Error('Time lookup count differs');
     if(await page.locator('#snapshot table tr').count()!==expected+1)throw Error('Position rows differ');
     if((time==='09:15:00'||time==='15:30:00')&&expected!==0)throw Error('Boundary positions');
     checks++;
    }
    const counts=await page.locator('#chart').evaluate(el=>el.data.map(t=>t.name));
    if(!counts.includes('Open trades')||!counts.includes('Bar-close drawdown'))throw Error('Chart traces missing');
   }
  }
  await page.goto(pathToFileURL(path.join(out,'capital/S092.html')).href+'#OHLC');
  await page.waitForFunction(()=>document.querySelector('#chart')?._fullLayout);
  await page.locator('#at').fill('10:51:00');
  if(!(await page.locator('#snapshot').innerText()).includes('9 open trades'))throw Error('S092 known peak count');
  await page.screenshot({path:path.join(out,'capital-example.png'),fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));
  const result={status:'passed',strategyPathRows:808,lookupChecks:checks,testedStrategyIds:['S092','S109','S299','S305','S060'],knownPeakVerified:'S092/OHLC 10:51 IST: 9 open trades',pageErrors:errors};
  fs.writeFileSync(path.join(out,'capital-browser-verification.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
