const { chromium } = require('../../frontend/node_modules/playwright');
const { resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const folder = resolve(process.argv[2]);
    await page.goto(pathToFileURL(resolve(folder, 'trade_explorer.html')).href);
    await page.waitForFunction(() => document.querySelector('#detail').data?.length > 0);
    assert.equal(await page.locator('#select option').count(), 73);
    assert.equal(await page.locator('#ledger tr').count(), 73);
    assert.equal(await page.locator('#select').inputValue(), '72');
    await page.selectOption('#select', '0');
    await page.waitForFunction(() => document.querySelector('#detail').layout.title.text.includes('Trade #1 selected'));
    assert.match(await page.locator('#tradeStats').innerText(), /1,305.73/);
    await page.locator('#next').click();
    assert.equal(await page.locator('#select').inputValue(), '1');
    await page.locator('#ledger tr[data-id="72"]').click();
    assert.equal(await page.locator('#select').inputValue(), '72');
    await page.locator('#all').click();
    await page.waitForFunction(() => document.querySelector('#detail').data[0].x.length === 25050);
    const markerCounts = await page.evaluate(() => document.querySelector('#detail').data
      .filter(trace => ['BUY (real fill)', 'EXIT (real fill)'].includes(trace.name))
      .map(trace => trace.x.length));
    assert.deepEqual(markerCounts, [73, 73]);
    await page.selectOption('#select', '0');
    await page.waitForFunction(() => document.querySelector('#detail').data[0].x.length === 75);
    await page.locator('#detail').screenshot({ path: resolve(folder, 'trade_detail_preview.png') });
    assert.deepEqual(errors, []);
    console.log('PASS: chart renders; all 73 trades and 146 fill markers; dropdown, navigation, ledger and full-history view; no browser errors.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
