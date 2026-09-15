const fs=require('fs'),path=require('path'),{spawn}=require('child_process');
const root=path.resolve(__dirname,'../..'),{chromium}=require(path.join(root,'frontend/node_modules/@playwright/test'));
const artifacts=path.join(__dirname,'artifacts');fs.mkdirSync(artifacts,{recursive:true});
function start(output){return new Promise((resolve,reject)=>{const child=spawn(path.join(root,'backtesting/.venv/Scripts/python.exe'),['-m','backtesting.ha_bb_vwap_allstocks','serve','--output',output,'--port','0'],{cwd:root,windowsHide:true});let text='';const timer=setTimeout(()=>{child.kill();reject(Error('Dashboard start timed out'));},20000);child.stdout.on('data',chunk=>{text+=chunk;const m=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve({child,url:m[0]});}});child.stderr.on('data',chunk=>text+=chunk);child.on('exit',code=>{clearTimeout(timer);if(!text.match(/http:\/\//))reject(Error('Dashboard exited: '+code+' '+text));});});}
(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'});let server;try{
 const page=await browser.newPage({viewport:{width:1550,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 server=await start('backtesting/ha_bb_vwap_allstocks/demo_output');await page.goto(server.url);await page.waitForFunction(()=>document.querySelector('#cards').children.length===12);
 if(!(await page.locator('#status').innerText()).includes('SYNTHETIC DEMO'))throw Error('Demo banner missing');
 let groups=0;for(const group of ['day','week','month','quarter','half_year','year','five_year','all']){await page.locator('#group').selectOption(group);await page.waitForResponse(r=>r.url().includes('/api/report')&&r.url().includes('group='+group)&&r.status()===200);await page.waitForTimeout(100);if(await page.locator('#periods tbody tr').count()<1)throw Error('Missing period rows');groups++;}
 await page.locator('#group').selectOption('month');await page.waitForTimeout(400);
 await page.screenshot({path:path.join(artifacts,'dashboard-demo.png'),fullPage:true});
 await page.locator('#at').fill('10:40:00');await page.locator('#inspect').click();await page.waitForFunction(()=>document.querySelector('#openSummary').textContent.startsWith('2 open trades'));
 if(await page.locator('#openPositions tbody tr').count()!==2)throw Error('Time lookup position count');
 await page.locator('#openPositions [data-trade]').first().click();await page.waitForFunction(()=>document.querySelector('#candleChart')?._fullLayout);
 const chart=await page.locator('#candleChart').evaluate(node=>({colors:[node.data[0].increasing.fillcolor,node.data[0].decreasing.fillcolor],times:node._fullLayout.xaxis.categoryarray}));
 if(chart.colors.join()!=='#22c55e,#ef4444'||chart.times[0]!=='09:15'||chart.times.at(-1)!=='15:30')throw Error('Candle chart differs');
 await page.screenshot({path:path.join(artifacts,'trade-demo.png')});await page.locator('#closeTrade').click();
 const csv=await page.request.get(server.url+'/api/export?strategy=D001&path=OLHC&kind=periods&group=year');if(csv.status()!==200||!(await csv.text()).includes('peak_capital'))throw Error('CSV export failed');
 server.child.kill();server=await start('backtesting/ha_bb_vwap_allstocks/artifacts/no_results');await page.goto(server.url);await page.waitForSelector('#empty:visible');if(!(await page.locator('#status').innerText()).includes('has not been run'))throw Error('Missing honest empty state');
 await page.screenshot({path:path.join(artifacts,'dashboard-not-run.png')});if(errors.length)throw Error(errors.join('\n'));
 const result={status:'passed',calendarGroupingChecks:groups,timeLookup:true,partialExitPositions:true,tradeChart:true,csvExport:true,notRunState:true,pageErrors:errors,syntheticOnly:true};fs.writeFileSync(path.join(artifacts,'browser-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(server)server.child.kill();await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
