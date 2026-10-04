const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const { chromium, expect } = require(path.join(root, 'frontend/node_modules/@playwright/test'));
const folder = path.join(root, 'backtest/nifty_options/2026-07-03_2026-10-01/results');
const data = JSON.parse(fs.readFileSync(path.join(folder, 'combined_dashboard_data.json')));
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [], requests = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1536, height: 1100 } });
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', req => { if (req.url().startsWith('http')) requests.push(req.url()); });
    await page.goto(pathToFileURL(path.join(folder, 'combined_dashboard.html')).href);
    await expect(page.locator('#comparison tbody tr')).toHaveCount(12);
    await expect(page.locator('.js-plotly-plot')).toHaveCount(6);
    for (const [scenario, rows] of Object.entries(data.scenarios)) {
      await page.locator('#path').selectOption(scenario);
      await expect(page.locator('#comparison tbody tr')).toHaveCount(12);
      for (const row of rows) {
        await page.locator('#strategy').selectOption(row.strategy);
        await expect(page.locator('#cycles tbody tr')).toHaveCount(row.cycles.length);
        const bars = await page.locator('#tradeChart').evaluate(el => el.data[0].y);
        assert.deepEqual(bars, row.cycles.filter(c => c.complete).map(c => c.pnl));
      }
      const tableTotal = await page.locator('#comparison tbody tr').evaluateAll(rows =>
        rows.reduce((sum, row) => sum + Number(row.children[1].textContent.replaceAll(',', '')), 0));
      assert.ok(Math.abs(tableTotal - rows.reduce((sum, row) => sum + row.net_pnl, 0)) < .1);
    }
    await page.locator('#path').selectOption('OLHC');
    await page.locator('#family').selectOption('premium');
    await expect(page.locator('#comparison tbody tr')).toHaveCount(4);
    await page.locator('#search').fill('positional next');
    await expect(page.locator('#comparison tbody tr')).toHaveCount(1);
    await page.locator('#search').fill('no matching strategy');
    await expect(page.locator('#comparison tbody tr')).toHaveCount(0);
    await expect(page.locator('#detailStats')).toContainText('No matching');
    await page.locator('#search').fill('');
    await page.locator('#family').selectOption('all');
    await page.locator('[data-sort="completed_cycles"]').click();
    const counts = await page.locator('#comparison tbody tr').evaluateAll(rows => rows.map(r => Number(r.children[3].textContent)));
    assert.deepEqual(counts, [...counts].sort((a,b)=>b-a));
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#download').click();
    const download = await downloadPromise;
    const csv = fs.readFileSync(await download.path(), 'utf8');
    assert.equal(csv.trim().split(/\r?\n/).length, 13);
    assert.ok(csv.includes('Profit factor') && csv.includes('Win rate %'));
    await page.locator('[data-sort="net_pnl"]').click();
    await page.screenshot({ path: path.join(folder, 'combined_dashboard_desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.screenshot({ path: path.join(folder, 'combined_dashboard_mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    const result = { passed: true, scenarios: 24, charts: 6, checked: ['all strategy trade bars and cycle counts', 'displayed P&L totals', 'path and family filters', 'search and empty state', 'numeric sorting', 'CSV download', 'mobile overflow'], pageErrors: errors, networkRequests: requests };
    fs.writeFileSync(path.join(folder, 'combined_dashboard_browser_verification.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
