const { chromium, expect } = require('../../frontend/node_modules/@playwright/test');
const fs = require('fs');
(async () => {
 const browser = await chromium.launch({channel:'chrome',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:5011/dashboard');
  const panel=page.getByRole('region',{name:'Options capital and charges'});
  await expect(panel).toBeVisible();
  await expect(page.getByText('Sandbox blocked funds',{exact:true})).toBeVisible();
  await expect(panel.getByText('₹2,40,00,000',{exact:true})).toBeVisible();
  await expect(panel.getByRole('button',{name:'Get FYERS margin',exact:true})).toHaveCount(12);
  await panel.getByRole('button',{name:'Get FYERS margin',exact:true}).first().click();
  await expect(panel.locator('dl:visible').filter({hasText:'Including existing positions: ₹16,25,000'}).first()).toBeVisible();
  await panel.getByRole('button',{name:'Get combined FYERS margin'}).click();
  await expect(panel.getByText('Including existing positions: ₹16,25,000').first()).toBeVisible();
  await panel.getByText('Saved quantities',{exact:true}).first().click();
  await expect(panel.getByText(/650 qty \/ 10 lots/).first()).toBeVisible();
  await panel.locator('summary').filter({hasText:'Estimated · confirmed fills'}).first().click();
  await expect(panel.getByText('gst',{exact:true}).first()).toBeVisible();
  await page.screenshot({path:'log/test/options-margin/dashboard-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('Mobile page overflow');
  await panel.screenshot({path:'log/test/options-margin/capital-mobile.png'});
  await page.goto('http://127.0.0.1:5011/strategy-reports');
  await page.getByText('Current options capital & charges',{exact:true}).click();
  await expect(panel).toBeVisible();
  await page.getByLabel('Execution scenario').selectOption('LIVE');
  await expect(panel).toHaveCount(0);
  if(errors.length) throw Error(errors.join('\n'));
  fs.writeFileSync('log/test/options-margin/browser-result.json',JSON.stringify({passed:true,checks:['dashboard','12 baskets','quotes','quantities','charges','mobile overflow','reports mode isolation'],pageErrors:errors},null,2));
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
