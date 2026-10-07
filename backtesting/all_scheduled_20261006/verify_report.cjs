const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium, expect} = require('../../frontend/node_modules/@playwright/test');

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const out = path.join(__dirname, 'verification');
  fs.mkdirSync(out, {recursive:true});
  const errors = [], network = [];
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => {if(/^https?:/.test(r.url())) network.push(r.url());});
    await page.goto(pathToFileURL(path.join(__dirname,'index.html')).href);
    await expect(page.locator('#overview tr')).toHaveCount(20);
    await expect(page.locator('#equity .main-svg').first()).toBeVisible();
    const data = await page.locator('#reportData').textContent().then(JSON.parse);
    assert.equal(data.scenarios.length,40);
    assert.equal(new Set(data.scenarios.map(s=>s.key)).size,20);
    for(const s of data.scenarios) {
      await page.locator('#path').selectOption(s.path);
      await page.locator('#strategy').selectOption(s.key);
      await expect(page.locator('#strategyName')).toHaveText(s.name+' · '+s.path);
      assert.equal(await page.evaluate(()=>document.getElementById('equity').data[0].y.at(-1)),s.curve.at(-1)?.pnl);
      assert.ok(!s.curve.length || Math.abs(s.curve.at(-1).pnl-s.net)<0.001);
    }
    await page.locator('#path').selectOption('OHLC');
    await page.locator('#family').selectOption('Options');
    await expect(page.locator('#overview tr')).toHaveCount(12);
    await page.locator('#search').fill('premium');
    await expect(page.locator('#overview tr')).toHaveCount(4);
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#csv').click();
    const download = await downloadPromise;
    const csv = path.join(out,'filtered-summary.csv');
    await download.saveAs(csv);
    assert.equal(fs.readFileSync(csv,'utf8').split('\r\n').length,5);
    await page.locator('#search').fill('');
    await page.locator('#family').selectOption('All');
    await page.locator('#path').selectOption('OLHC');
    await page.locator('#strategy').selectOption('nifty500_fixed');
    await expect(page.locator('#archiveCoverage')).toContainText('594 returned no candles');
    await page.screenshot({path:path.join(out,'desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await expect(page.locator('#overview tr')).toHaveCount(20);
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
    await page.screenshot({path:path.join(out,'mobile.png')});
    const overflow = await page.evaluate(()=>({width:innerWidth,body:document.documentElement.scrollWidth,elements:[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth&&!e.closest('.scroll')).map(e=>({tag:e.tagName,id:e.id,class:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})).slice(0,15)}));
    fs.writeFileSync(path.join(out,'mobile-layout.json'),JSON.stringify(overflow,null,2));
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
    assert.deepEqual(errors,[]);
    assert.deepEqual(network,[]);
    const result={passed:true,strategies:20,scenarios:40,chartsReconciled:40,filters:true,csv:true,mobileOverflow:false,pageErrors:errors,externalRequests:network};
    fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
