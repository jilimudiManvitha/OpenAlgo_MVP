const path = require('path');
const fs = require('fs');
const {pathToFileURL} = require('url');
const root = path.resolve(__dirname, '../..');
const {chromium} = require(path.join(root, 'frontend/node_modules/@playwright/test'));
const out = path.join(__dirname, 'results');

(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1200}});
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(pathToFileURL(path.join(out, 'index.html')).href);
    if (await page.locator('#ranking tbody tr').count() !== 404) throw Error('Wrong strategy count');
    await page.locator('#search').fill('sell');
    if (await page.locator('#ranking tbody tr:visible').count() !== 202) throw Error('Search failed');
    await page.locator('#search').fill('');
    await page.screenshot({path:path.join(out,'overview.png')});
    const selected = new Map();
    for (const file of fs.readdirSync(path.join(out,'strategies')).filter(x=>x.endsWith('.json'))) {
      const report = JSON.parse(fs.readFileSync(path.join(out,'strategies',file),'utf8'));
      for (const t of report.trades) {
        const key = `${t.side}_${t.minutes}_${t.scenario}`;
        if (!selected.has(key)) selected.set(key,t);
        if (t.fills.length>2 && !selected.has('partial')) selected.set('partial',t);
        for (const kind of ['rsi','macd','supertrend'])
          if(t.name.includes(kind) && !selected.has(kind)) selected.set(kind,t);
      }
    }
    let first=true;
    for (const [key,t] of selected) {
      await page.goto(pathToFileURL(path.join(out,'trades',t.id+'.html')).href);
      await page.waitForFunction(()=>document.querySelector('#chart')?._fullLayout);
      const details = await page.locator('#chart').evaluate(node=>({
        names:node.data.map(x=>x.name), colors:[node.data[0].increasing.fillcolor,node.data[0].decreasing.fillcolor],
        categories:node._fullLayout.xaxis.categoryarray,
        count:node.data[0].x.length, entry:node.data.find(x=>x.name==='Entry fill').y[0],
        exits:node.data.find(x=>x.name==='Exit fills').y.length
      }));
      if(!details.names.includes('Completed signal')) throw Error('Missing signal: '+t.id);
      if(details.colors.join(',')!=='#22c55e,#ef4444') throw Error('Wrong candle colors');
      if(details.categories[0]!=='09:15'||details.categories.at(-1)!=='15:30') throw Error('Wrong session span');
      if(details.entry!==t.entry_price||details.exits!==t.fills.length-1) throw Error('Fill markers differ');
      if(t.name.includes('rsi_') && !details.names.includes('RSI')) throw Error('Missing RSI panel');
      if(t.name.includes('macd_') && !details.names.includes('MACD_SIGNAL')) throw Error('Missing MACD panel');
      if(first || key==='partial' || key==='rsi'){
        await page.screenshot({path:path.join(out,first?'example-trade.png':`example-${key}.png`),fullPage:true});
        first=false;
      }
    }
    if(errors.length) throw Error(errors.join('\n'));
    const result={status:'passed',strategyRows:404,searchPassed:true,renderedTradeExamples:[...selected.keys()],pageErrors:errors};
    fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
