import { chromium } from 'playwright';
console.log('Launching browser...');
const browser = await chromium.launch({ 
  headless: true,
  args: ['--no-sandbox']
});
console.log('Browser launched, opening page...');
const page = await browser.newPage();
console.log('Page opened');
await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 10000 });
console.log('Page loaded, title:', await page.title());
await browser.close();
console.log('Done');
