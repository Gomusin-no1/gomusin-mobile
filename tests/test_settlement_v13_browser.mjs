// Run with the disposable server in serve_settlement_v13_e2e.py, never a live site.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const folder = process.argv[2];
assert(folder, 'Pass the disposable fixture/output directory.');
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
  headless: true,
  args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-software-rasterizer','--no-zygote','--single-process'],
});
const page = await browser.newPage({viewport:{width:1365,height:1000},colorScheme:'light'});
const errors=[];
page.on('pageerror', e=>errors.push(e.message));
const checks=[];
try {
  await page.goto('http://127.0.0.1:5013/login');
  await page.locator('[name="company_code"]').fill('v13-test');
  await page.locator('[name="username"]').fill('test-admin');
  await page.locator('[name="password"]').fill('test-only-password');
  await page.locator('.signature-submit').click();
  await page.waitForURL('http://127.0.0.1:5013/');
  const menu=page.getByRole('link',{name:'정산 대사 v1.3',exact:true});
  await page.getByText('매장 운영',{exact:true}).click();
  await menu.click();await page.waitForURL('**/settlements/v13');
  checks.push('login and TrustMap navigation');
  await page.locator('[name="month"]').fill('2026-09');
  for(let i=0;i<3;i++)await page.locator(`[name="sales_${i}"]`).setInputFiles(`${folder}/sales-${i}.xlsx`);
  await page.locator('[name="vendor_gyeonggi"]').setInputFiles(`${folder}/gyeonggi.xlsx`);
  await page.locator('[name="vendor_juan"]').setInputFiles(`${folder}/juan.xlsx`);
  await page.screenshot({path:`${folder}/upload-desktop.png`,fullPage:true});
  await page.getByRole('button',{name:'정산 대조하기',exact:true}).click();
  await page.waitForURL(/\/settlements\/v13\/\d+$/);
  await page.locator('.row[data-key]').first().waitFor();
  assert.equal(await page.locator('.tab').count(),2);
  assert.equal(await page.locator('.row[data-key]').count(),3);
  assert.match(await page.locator('.row[data-key]').first().textContent(),/덜 받음/);
  await page.locator('.row[data-key]').first().click();
  assert.match(await page.locator('.detail.show').textContent(),/10,000원 덜/);
  assert.match(await page.locator('.detail.show').textContent(),/항목별 대조/);
  await page.screenshot({path:`${folder}/result-desktop.png`,fullPage:true});
  checks.push('three branches, two vendor files, amounts and expandable details');
  await page.locator('.card[data-k="more"]').click();
  assert.equal(await page.locator('.row[data-key]').count(),1);
  await page.locator('#fStore').selectOption({label:'3호점'});
  assert.equal(await page.locator('.row[data-key]').count(),0);
  await page.locator('.card[data-k=""]').click();
  assert.equal(await page.locator('.row[data-key]').count(),1);
  await page.locator('#fStore').selectOption('');
  await page.locator('#fq').fill('테스트일치');
  assert.equal(await page.locator('.row[data-key]').count(),1);
  await page.locator('#fq').fill('');
  checks.push('status, store and customer filters');
  await page.locator('.tab').nth(1).click();
  assert.equal(await page.locator('.row[data-key]').count(),1);
  assert.match(await page.locator('.row[data-key]').textContent(),/일치/);
  const download=page.waitForEvent('download');
  await page.getByRole('link',{name:'엑셀 다운로드',exact:true}).first().click();
  const d=await download;await d.saveAs(`${folder}/browser-export.xlsx`);
  assert(fs.statSync(`${folder}/browser-export.xlsx`).size>1000);
  checks.push('vendor tabs and Excel download');
  await page.reload();await page.locator('.row[data-key]').first().waitFor();
  assert.equal(await page.locator('.row[data-key]').count(),3);
  await page.setViewportSize({width:390,height:844});
  await page.locator('.row[data-key]').first().focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('.detail.show').count(),1);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await page.screenshot({path:`${folder}/result-mobile.png`,fullPage:true});
  checks.push('persisted reload, mobile layout and keyboard detail');
  assert.deepEqual(errors,[]);
  const result={passed:true,browser:browser.version(),checks,pageErrors:errors};
  fs.writeFileSync(`${folder}/browser-results.json`,JSON.stringify(result,null,2));console.log(JSON.stringify(result));
} finally {await browser.close();}
