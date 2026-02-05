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

  console.log('\n=== STEP 1: Clicking IRIS orb ===');
  await page.click('text=IRIS');
  await page.waitForTimeout(2000);

  console.log('\n=== STEP 2: Clicking main node ===');
  // Find and click a main node
  const mainNode = await page.locator('button').filter({ hasText: /VOICE|AGENT|AUTOMATE/i }).first();
  await mainNode.click();
  await page.waitForTimeout(3000);

  console.log('\n=== ALL DEBUG LOGS ===');
  logs.filter(l => l.includes('DEBUG')).forEach(l => console.log(l));

  // Keep browser open for inspection
  console.log('\nBrowser staying open for 60 seconds...');
  await page.waitForTimeout(60000);
  await browser.close();
})();
