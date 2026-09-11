const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');
const root = path.resolve(__dirname, '../..');
const { chromium } = require(path.join(root, 'frontend/node_modules/@playwright/test'));

(async () => {
  const report = path.resolve(process.argv[2]);
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(pathToFileURL(path.join(report, 'index.html')).href);
    await page.waitForFunction(() => document.querySelectorAll('.plotly-graph-div').length === 1 && document.querySelector('.plotly-graph-div')._fullLayout);
    const count = await page.locator('#trades tbody tr').count();
    const expected = fs.readdirSync(path.join(report, 'trades')).filter(name => name.endsWith('.html')).length;
    if (count !== expected) throw new Error(`Expected ${expected} trades, found ${count}`);
    await page.screenshot({path: path.join(report, 'overview.png')});
    const stocks = await page.locator('#trades tbody tr td:first-child').allTextContents();
    await page.locator('#search').fill(stocks[0]);
    if (await page.locator('#trades tbody tr:visible').count() !== stocks.filter(s => s.includes(stocks[0])).length) throw new Error('Trade search count mismatch');
    const links = await page.locator('#trades a').evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
    for (const file of links) {
      await page.goto(pathToFileURL(path.join(report, file)).href);
      await page.waitForFunction(() => document.querySelector('.plotly-graph-div')?._fullLayout);
      const traces = await page.locator('.plotly-graph-div').evaluate(node => node.data.map(trace => trace.name));
      if (!traces.includes('Entry') || !traces.includes('Completed signal')) throw new Error(`Missing trade markers in ${file}`);
    }
    await page.goto(pathToFileURL(path.join(report, links[0])).href);
    await page.waitForFunction(() => document.querySelector('.plotly-graph-div')?._fullLayout);
    await page.screenshot({path: path.join(report, 'example-trade.png'), fullPage: true});
    if (errors.length) throw new Error(errors.join('\n'));
    const result = {renderedTradePages: links.length, searchPassed: true, pageErrors: errors};
    fs.writeFileSync(path.join(report, 'browser-verification.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
