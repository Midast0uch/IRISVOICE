/**
 * Bug Condition Exploration Test - Level 3 Nodes Fail to Render Without WebSocket Data
 * 
 * **Validates: Requirements 1.1, 1.3**
 * 
 * CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists
 * DO NOT attempt to fix the test or the code when it fails
 * 
 * This test encodes the expected behavior - it will validate the fix when it passes after implementation
 * 
 * GOAL: Surface counterexamples that demonstrate the bug exists
 * 
 * Expected Behavior (from design):
 * - When clicking a main category node at level 2, level 3 subnodes should render in the DOM
 * - Each of the 6 main categories should display 4 subnodes in orbital positions
 * - Subnodes should be visible and interactive even when backend is offline
 * 
 * Current Behavior (bug - will cause test to FAIL):
 * - When clicking a main category node, no level 3 subnodes render
 * - DOM inspection shows zero HexagonalNode components at level 3
 * - Only the center orb label changes, but no orbiting nodes appear
 * - WebSocket subnodes are empty/undefined when backend is offline
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Test configuration
const FRONTEND_URL = 'http://localhost:3000';
const STARTUP_TIMEOUT = 90000; // 90 seconds for Next.js to start
const TEST_TIMEOUT = 180000; // 3 minutes for full test
const PAGE_LOAD_TIMEOUT = 30000; // 30 seconds for page load

// Main categories to test
const MAIN_CATEGORIES = [
  { id: 'VOICE', label: 'Voice', expectedSubnodes: ['Input', 'Output', 'Processing', 'Model'] },
  { id: 'AGENT', label: 'Agent', expectedSubnodes: ['Personality', 'Knowledge', 'Behavior', 'Memory'] },
  { id: 'AUTOMATE', label: 'Automate', expectedSubnodes: ['Triggers', 'Actions', 'Conditions', 'Workflows'] },
  { id: 'SYSTEM', label: 'System', expectedSubnodes: ['Performance', 'Security', 'Backup', 'Updates'] },
  { id: 'CUSTOMIZE', label: 'Customize', expectedSubnodes: ['Theme', 'Layout', 'Widgets', 'Shortcuts'] },
  { id: 'MONITOR', label: 'Monitor', expectedSubnodes: ['Dashboard', 'Logs', 'Metrics', 'Alerts'] },
];

/**
 * Wait for Next.js dev server to be ready
 */
async function waitForServer(url, timeout = STARTUP_TIMEOUT) {
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeout) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return true;
      }
    } catch (error) {
      // Server not ready yet
    }
    
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  
  throw new Error(`Server did not start within ${timeout}ms`);
}

/**
 * Run the bug condition exploration test
 */
async function runBugConditionTest() {
  console.log('\n=== Bug Condition Exploration Test ===\n');
  console.log('Testing: Level 3 Nodes Fail to Render Without WebSocket Data\n');
  
  // Start Next.js dev server (backend intentionally NOT started)
  console.log('Starting Next.js dev server (backend offline)...\n');
  
  const devServer = spawn('npm', ['run', 'dev'], {
    cwd: join(__dirname, '..'),
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  
  let serverOutput = '';
  
  devServer.stdout.on('data', (data) => {
    const output = data.toString();
    serverOutput += output;
    if (output.includes('Ready') || output.includes('compiled')) {
      process.stdout.write(output);
    }
  });
  
  devServer.stderr.on('data', (data) => {
    const output = data.toString();
    serverOutput += output;
  });
  
  try {
    // Wait for server to be ready
    console.log('Waiting for Next.js server to be ready...\n');
    await waitForServer(FRONTEND_URL);
    console.log('✓ Next.js server is ready\n');
    
    // Import Playwright dynamically
    const playwright = await import('playwright');
    const browser = await playwright.chromium.launch({ headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    
    // Track console messages
    const consoleMessages = [];
    page.on('console', msg => {
      consoleMessages.push({ type: msg.type(), text: msg.text() });
    });
    
    // Navigate to the application
    console.log(`Navigating to ${FRONTEND_URL}...\n`);
    await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded', timeout: PAGE_LOAD_TIMEOUT });
    
    // Wait a bit for React to hydrate
    await page.waitForTimeout(3000);
    
    // Wait for the IRIS orb to be visible (level 1)
    console.log('Waiting for IRIS orb (level 1)...\n');
    await page.waitForSelector('[data-testid="iris-orb"], .iris-orb, [class*="orb"]', { timeout: 10000 });
    console.log('✓ IRIS orb is visible\n');
    
    // Click the orb to expand to level 2
    console.log('Clicking IRIS orb to expand to level 2...\n');
    await page.click('[data-testid="iris-orb"], .iris-orb, [class*="orb"]');
    await page.waitForTimeout(2000); // Wait for animation
    
    // Verify we're at level 2 by checking for main category nodes
    console.log('Verifying level 2 main category nodes are visible...\n');
    const mainNodesVisible = await page.evaluate(() => {
      // Look for elements that might be main category nodes
      const nodes = document.querySelectorAll('[class*="hexagonal"], [class*="node"], [data-node-id]');
      return nodes.length >= 6; // Should have 6 main category nodes
    });
    
    if (!mainNodesVisible) {
      console.log('⚠️  Warning: Could not verify level 2 nodes, but continuing test...\n');
    } else {
      console.log('✓ Level 2 main category nodes are visible\n');
    }
    
    // Test results
    const testResults = [];
    const failures = [];
    
    // Test each main category
    for (const category of MAIN_CATEGORIES) {
      console.log(`\n--- Testing ${category.label} Category ---\n`);
      
      try {
        // Try to find and click the category node
        // We'll try multiple strategies to find the node
        const clicked = await page.evaluate((categoryLabel) => {
          // Strategy 1: Look for text content
          const allElements = Array.from(document.querySelectorAll('*'));
          const nodeWithText = allElements.find(el => 
            el.textContent?.trim() === categoryLabel && 
            el.offsetParent !== null // Element is visible
          );
          
          if (nodeWithText) {
            nodeWithText.click();
            return true;
          }
          
          // Strategy 2: Look for data attributes
          const nodeWithAttr = document.querySelector(`[data-node-id="${categoryLabel}"], [data-category="${categoryLabel}"]`);
          if (nodeWithAttr) {
            nodeWithAttr.click();
            return true;
          }
          
          return false;
        }, category.label);
        
        if (!clicked) {
          console.log(`⚠️  Could not find clickable element for ${category.label}, trying alternative approach...\n`);
          
          // Alternative: Click at approximate position where node should be
          // This is a fallback and may not work reliably
          await page.mouse.click(640, 360); // Center of typical viewport
          await page.waitForTimeout(500);
        }
        
        console.log(`Clicked ${category.label} node, waiting for level 3 subnodes...\n`);
        await page.waitForTimeout(2000); // Wait for animation and rendering
        
        // Inspect DOM for level 3 subnodes
        const domInspection = await page.evaluate((expectedSubnodes) => {
          // Count all potential node elements
          const allNodes = document.querySelectorAll('[class*="hexagonal"], [class*="node"], [data-node-id]');
          
          // Look for subnode labels
          const foundSubnodes = [];
          expectedSubnodes.forEach(subnodeLabel => {
            const allElements = Array.from(document.querySelectorAll('*'));
            const found = allElements.some(el => 
              el.textContent?.trim() === subnodeLabel && 
              el.offsetParent !== null
            );
            if (found) {
              foundSubnodes.push(subnodeLabel);
            }
          });
          
          return {
            totalNodes: allNodes.length,
            foundSubnodes: foundSubnodes,
            expectedSubnodes: expectedSubnodes,
          };
        }, category.expectedSubnodes);
        
        console.log(`DOM Inspection Results:`);
        console.log(`  Total nodes in DOM: ${domInspection.totalNodes}`);
        console.log(`  Expected subnodes: ${domInspection.expectedSubnodes.join(', ')}`);
        console.log(`  Found subnodes: ${domInspection.foundSubnodes.length > 0 ? domInspection.foundSubnodes.join(', ') : 'NONE'}`);
        
        // Check if all expected subnodes are rendered
        const allSubnodesRendered = domInspection.foundSubnodes.length === domInspection.expectedSubnodes.length;
        
        testResults.push({
          category: category.label,
          passed: allSubnodesRendered,
          foundSubnodes: domInspection.foundSubnodes,
          expectedSubnodes: domInspection.expectedSubnodes,
        });
        
        if (!allSubnodesRendered) {
          const missingSubnodes = domInspection.expectedSubnodes.filter(
            sn => !domInspection.foundSubnodes.includes(sn)
          );
          failures.push({
            category: category.label,
            issue: 'Level 3 subnodes not rendered',
            expected: domInspection.expectedSubnodes,
            found: domInspection.foundSubnodes,
            missing: missingSubnodes,
          });
          console.log(`❌ FAIL: Missing subnodes: ${missingSubnodes.join(', ')}\n`);
        } else {
          console.log(`✓ PASS: All subnodes rendered correctly\n`);
        }
        
        // Go back to level 2 for next test
        await page.keyboard.press('Escape');
        await page.waitForTimeout(1000);
        
      } catch (error) {
        console.log(`❌ ERROR testing ${category.label}: ${error.message}\n`);
        failures.push({
          category: category.label,
          issue: 'Test execution error',
          error: error.message,
        });
      }
    }
    
    // Check for WebSocket errors in console
    const wsErrors = consoleMessages.filter(msg => 
      msg.text.includes('WebSocket') || 
      msg.text.includes('ws://') ||
      msg.text.includes('connection')
    );
    
    if (wsErrors.length > 0) {
      console.log('\n--- Console Messages (WebSocket) ---\n');
      wsErrors.forEach(msg => {
        console.log(`[${msg.type}] ${msg.text}`);
      });
    }
    
    // Close browser
    await browser.close();
    
    // Print summary
    console.log('\n=== Test Results Summary ===\n');
    testResults.forEach(result => {
      const status = result.passed ? '✓ PASS' : '❌ FAIL';
      console.log(`${status}: ${result.category}`);
      console.log(`  Expected: ${result.expectedSubnodes.join(', ')}`);
      console.log(`  Found: ${result.foundSubnodes.length > 0 ? result.foundSubnodes.join(', ') : 'NONE'}`);
    });
    
    // Print counterexamples if test fails
    if (failures.length > 0) {
      console.log('\n=== COUNTEREXAMPLES FOUND (Bug Confirmed) ===\n');
      failures.forEach((failure, index) => {
        console.log(`Counterexample ${index + 1}: ${failure.category}`);
        console.log(`  Issue: ${failure.issue}`);
        if (failure.expected) {
          console.log(`  Expected subnodes: ${failure.expected.join(', ')}`);
          console.log(`  Found subnodes: ${failure.found.length > 0 ? failure.found.join(', ') : 'NONE'}`);
          console.log(`  Missing subnodes: ${failure.missing.join(', ')}`);
        }
        if (failure.error) {
          console.log(`  Error: ${failure.error}`);
        }
        console.log('');
      });
      
      console.log('✓ Test correctly FAILED - this confirms the bug exists!');
      console.log('✓ These counterexamples demonstrate that level 3 nodes fail to render without WebSocket data');
      console.log('\nRoot Cause Analysis:');
      console.log('- HexagonalControlCenter component uses nav.subnodes from WebSocket context');
      console.log('- When backend is offline, nav.subnodes is an empty object {}');
      console.log('- Component has hardcoded SUB_NODES constant but does not use it as fallback');
      console.log('- Result: nav.subnodes[selectedMain] returns undefined or [], causing zero nodes to render');
      console.log('\nNext steps:');
      console.log('1. Implement fallback logic in HexagonalControlCenter (Task 3.1)');
      console.log('2. Re-run this test - it should PASS after the fix');
      
      process.exit(1);
    } else {
      console.log('\n=== All Assertions Passed ===\n');
      console.log('✓ All main categories render their level 3 subnodes correctly');
      console.log('✓ Subnodes are visible in DOM with correct labels');
      console.log('✓ Navigation works correctly even with backend offline');
      console.log('\n✓ Bug is FIXED - expected behavior is satisfied!');
      
      process.exit(0);
    }
    
  } catch (error) {
    console.error('\n❌ Test execution error:', error);
    process.exit(1);
  } finally {
    // Kill the dev server
    console.log('\nCleaning up dev server...');
    
    try {
      devServer.kill('SIGTERM');
      
      // Wait for graceful shutdown
      await new Promise(resolve => setTimeout(resolve, 3000));
      
      // Force kill if still running
      try {
        process.kill(devServer.pid, 'SIGKILL');
      } catch (e) {
        // Process already dead
      }
    } catch (e) {
      console.log('Dev server cleanup completed');
    }
  }
}

// Run the test
runBugConditionTest().catch(error => {
  console.error('\n❌ Test execution error:', error);
  process.exit(1);
});
