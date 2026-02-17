import { chromium } from 'playwright';

async function testNavigation() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 }
  });
  
  const page = await context.newPage();
  
  // Capture console logs
  const consoleLogs: any[] = [];
  page.on('console', (msg) => {
    const log = `[${msg.type()}] ${msg.text()}`;
    consoleLogs.push(log);
    console.log(log);
  });
  
  // Navigate to the app
  console.log('Navigating to http://localhost:3000...');
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  
  // Test Level 1 → 2: Click IRIS to expand
  console.log('\n=== TEST 1: Clicking IRIS orb to expand (Level 1 → 2) ===');
  const irisOrb = await page.locator('[class*="rounded-full"]', { hasText: /IRIS/i }).first();
  if (await irisOrb.isVisible().catch(() => false)) {
    await irisOrb.click({ force: true });
    await page.waitForTimeout(1500);
  } else {
    console.log('IRIS orb not found, trying alternative selector...');
    const alternative = await page.locator('text=IRIS').first();
    await alternative.click({ force: true });
    await page.waitForTimeout(1500);
  }
  
  // Test Level 2 → 3: Click main node
  console.log('\n=== TEST 2: Clicking main node (Level 2 → 3) ===');
  const mainNodes = await page.locator('button[class*="absolute"]').all();
  console.log(`Found ${mainNodes.length} main nodes`);
  
  if (mainNodes.length > 0) {
    await mainNodes[0].click({ force: true });
    await page.waitForTimeout(2000);
  }
  
  // Test Level 3 → 4: Click subnode
  console.log('\n=== TEST 3: Clicking subnode (Level 3 → 4) ===');
  const subnodes = await page.locator('button[class*="absolute"]').all();
  console.log(`Found ${subnodes.length} buttons (potential subnodes)`);
  
  if (subnodes.length > 0) {
    await subnodes[0].click({ force: true });
    await page.waitForTimeout(2000);
  }
  
  // Test Level 4 mini-stack click
  console.log('\n=== TEST 4: Checking for mini-stack (Level 4) ===');
  const miniStack = await page.locator('[class*="mini-node-stack"]').first();
  const hasMiniStack = await miniStack.isVisible().catch(() => false);
  console.log(`Mini-stack visible: ${hasMiniStack}`);
  
  if (hasMiniStack) {
    const cards = await page.locator('[class*="mini-node-card"]').all();
    console.log(`Found ${cards.length} mini-node cards`);
    
    if (cards.length > 0) {
      console.log('Clicking mini-stack card...');
      await cards[0].click({ force: true });
      await page.waitForTimeout(1000);
    }
  }
  
  // Log all captured console messages
  console.log('\n=== ALL CONSOLE LOGS ===');
  consoleLogs.filter(log => log.includes('[DEBUG]')).forEach(log => console.log(log));
  
  // Keep browser open for inspection
  console.log('\nBrowser will stay open for 30 seconds for inspection...');
  await page.waitForTimeout(30000);
  
  await browser.close();
}

testNavigation().catch(console.error);
