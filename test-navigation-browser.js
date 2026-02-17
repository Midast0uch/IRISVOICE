const { chromium } = require('playwright');

async function testNavigation() {
  console.log('Starting navigation test...');
  
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  await page.goto('http://localhost:3000');
  await page.waitForTimeout(3000);
  
  // Test 1: Click IRIS orb to expand (L1→L2)
  console.log('Test 1: Clicking IRIS orb (L1→L2)...');
  await page.click('[class*="rounded-full"]', { position: { x: 400, y: 400 } });
  await page.waitForTimeout(2000);
  
  // Test 2: Try dragging the orb
  console.log('Test 2: Testing drag...');
  await page.mouse.move(400, 400);
  await page.mouse.down();
  await page.mouse.move(450, 450, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(2000);
  
  console.log('Tests completed. Check console logs in browser.');
  
  await browser.close();
}

testNavigation().catch(console.error);
