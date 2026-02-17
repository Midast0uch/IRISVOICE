const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  // Ensure test-results directory exists
  const resultsDir = path.join(__dirname, 'test-results');
  if (!fs.existsSync(resultsDir)) {
    fs.mkdirSync(resultsDir, { recursive: true });
  }

  console.log('[TEST] Launching browser...');
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();

  try {
    // Navigate to the app
    console.log('[TEST] Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    
    // Take initial screenshot
    await page.screenshot({ path: 'test-results/1-initial.png', fullPage: true });
    console.log('[TEST] ✓ Screenshot 1: Initial state saved');

    // Click IRIS orb to expand main nodes
    console.log('[TEST] Looking for IRIS orb...');
    const irisOrb = page.locator('text=IRIS').first();
    await irisOrb.waitFor({ state: 'visible', timeout: 5000 });
    console.log('[TEST] Clicking IRIS orb...');
    await irisOrb.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'test-results/2-expanded.png', fullPage: true });
    console.log('[TEST] ✓ Screenshot 2: After clicking IRIS orb');

    // Click VOICE node
    console.log('[TEST] Looking for VOICE node...');
    const voiceNode = page.locator('text=VOICE').first();
    await voiceNode.waitFor({ state: 'visible', timeout: 5000 });
    console.log('[TEST] Clicking VOICE node...');
    await voiceNode.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'test-results/3-voice-subnodes.png', fullPage: true });
    console.log('[TEST] ✓ Screenshot 3: After clicking VOICE node');

    // Click INPUT subnode to trigger MiniNodeStack
    console.log('[TEST] Looking for INPUT subnode...');
    const inputSubnode = page.locator('text=INPUT').first();
    await inputSubnode.waitFor({ state: 'visible', timeout: 5000 });
    console.log('[TEST] Clicking INPUT subnode...');
    await inputSubnode.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'test-results/4-mininode-stack.png', fullPage: true });
    console.log('[TEST] ✓ Screenshot 4: After clicking INPUT subnode');

    // Check for MiniNodeStack
    console.log('[TEST] Checking for MiniNodeStack...');
    const saveButton = page.locator('text=Save').first();
    const miniNodeStack = page.locator('.mini-node-stack, [class*="mini-node"]').first();
    
    const saveVisible = await saveButton.isVisible().catch(() => false);
    const stackVisible = await miniNodeStack.isVisible().catch(() => false);
    
    console.log(`[TEST] Save button visible: ${saveVisible}`);
    console.log(`[TEST] MiniNodeStack visible: ${stackVisible}`);

    if (saveVisible || stackVisible) {
      console.log('[TEST] ✓ SUCCESS: MiniNodeStack is visible!');
    } else {
      console.log('[TEST] ✗ FAIL: MiniNodeStack NOT found');
      
      // Debug: list all text on page
      const allText = await page.locator('body').textContent();
      console.log('[TEST] Page content:', allText.substring(0, 500));
    }

    // Keep browser open for manual inspection
    console.log('[TEST] Keeping browser open for 30 seconds...');
    await page.waitForTimeout(30000);

  } catch (error) {
    console.error('[TEST] Error:', error);
    await page.screenshot({ path: 'test-results/error.png', fullPage: true });
  } finally {
    await browser.close();
    console.log('[TEST] Browser closed');
  }
})();
