const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

  // Collect console logs
  const logs = [];
  page.on('console', msg => {
    const text = `[${msg.type()}] ${msg.text()}`;
    logs.push(text);
    console.log(text);
  });

  await page.goto('http://localhost:3000');
  await page.waitForTimeout(3000);

  console.log('\n=== TEST 1: Clicking IRIS orb ===');
  await page.click('text=IRIS', { force: true });
  await page.waitForTimeout(2000);

  console.log('\n=== TEST 2: Clicking VOICE main node ===');
  await page.click('button:has-text("VOICE")', { force: true });
  await page.waitForTimeout(2000);

  console.log('\n=== TEST 3: Clicking INPUT subnode ===');
  await page.click('button:has-text("INPUT")', { force: true });
  await page.waitForTimeout(2000);

  console.log('\n=== TEST 4: Clicking IRIS to go back (4->3) ===');
  await page.click('text=IRIS', { force: true });
  await page.waitForTimeout(2000);

  console.log('\n=== DEBUG LOGS ===');
  logs.filter(l => l.includes('DEBUG')).forEach(l => console.log(l));

  console.log('\nStaying open for 30 seconds...');
  await page.waitForTimeout(30000);
  await browser.close();
})();
