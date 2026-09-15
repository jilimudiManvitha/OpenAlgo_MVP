const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('../../frontend/node_modules/@playwright/test');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const output = path.join(__dirname, 'results');
    await page.goto(pathToFileURL(path.join(output, 'index.html')).href);
    await page.waitForFunction(() => document.querySelector('#chart')._fullLayout);
    if (await page.locator('#rows tr').count() !== 404) throw Error('Missing ranked versions');
    if (await page.locator('#choice option').count() !== 404) throw Error('Missing strategy choices');
    for (const sid of ['S001','S101','S102','S202','S203','S303','S304','S404']) {
      await page.locator('#choice').selectOption(sid);
      await page.waitForFunction(id => document.querySelector('#chart').data[0].name.startsWith(id), sid);
      if (!(await page.locator('#stats').innerText()).includes('Overnight trades')) throw Error('Missing statistics');
    }
    await page.locator('#search').fill('S092');
    if (await page.locator('#rows tr').count() !== 1) throw Error('Filter failed');
    await page.locator('#search').fill('');
    await page.locator('#choice').selectOption(await page.locator('#choice option').first().getAttribute('value'));
    await page.screenshot({ path: path.join(output, 'report-preview.png'), fullPage: true });
    const links = await page.locator('a[href]').evaluateAll(nodes => nodes.map(n=>n.getAttribute('href')));
    for (const href of links.filter(x => !x.startsWith('#') && !/^https?:/.test(x))) {
      if (!fs.existsSync(path.join(output, href))) throw Error('Missing linked file '+href);
    }
    if (errors.length) throw Error(errors.join('\n'));
    const evidence = { passed: true, rankedRows: 404, strategies: 404, chartCases: 8,
                       filter: true, offlineLinks: true, pageErrors: errors };
    fs.writeFileSync(path.join(output,'browser-verification.json'), JSON.stringify(evidence,null,2));
    console.log(JSON.stringify(evidence));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
