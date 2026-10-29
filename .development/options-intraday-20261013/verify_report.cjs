const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '../..');
const { chromium, expect } = require(path.join(root, 'frontend/node_modules/@playwright/test'));
const folder = path.join(root, 'backtest/options_intraday_2026-10-13/results');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [], requests = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (r.url().startsWith('http')) requests.push(r.url()); });
    await page.goto(pathToFileURL(path.join(folder, 'index.html')).href);
    await expect(page.locator('h1')).toHaveText('Six options intraday strategies');
    await expect(page.locator('table tbody tr')).toHaveCount(12);
    await expect(page.locator('.js-plotly-plot')).toHaveCount(2);
    const summaries = JSON.parse(fs.readFileSync(path.join(folder, 'summary.json')));
    for (let i = 0; i < 12; i++) {
      const row = page.locator('table tbody tr').nth(i);
      const s = summaries[i];
      await expect(row.locator('td').nth(0)).toHaveText(s.strategy);
      const net = Number((await row.locator('td').nth(1).textContent()).replaceAll(',', ''));
      assert.ok(Math.abs(net - s.net_pnl) < .011);
    }
    const traces = await page.locator('.js-plotly-plot').evaluateAll(nodes => nodes.map(n => n.data.length));
    assert.deepEqual(traces, [12, 12]);
    await page.screenshot({ path: path.join(folder, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(400);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(folder, 'mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    const result = { passed: true, scenarios: 12, charts: 2, checked: ['rendered P&L agrees with ledgers', 'six strategy traces per panel', 'mobile page width', 'offline network independence'], errors, requests };
    fs.writeFileSync(path.join(folder, 'browser_verification.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
