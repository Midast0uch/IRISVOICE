import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

await page.goto('http://localhost:3000', { timeout: 10000, waitUntil: 'load' });
await page.waitForTimeout(3000);

await page.screenshot({ path: 'benchmarks/output/00-verified.png' });

const text = await page.evaluate(() => document.body.innerText);
console.log('Page text:', text.slice(0, 500));
console.log('Title:', await page.title());

const buttons = await page.evaluate(() => 
  Array.from(document.querySelectorAll('button')).filter(b => b.offsetWidth > 5).length
);
console.log(`Buttons: ${buttons}`);

await browser.close();
