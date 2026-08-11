// IRIS Live Benchmark — Browser-driven via Playwright
import { chromium } from 'playwright';

const IRIS_URL = 'http://localhost:3000';
const COHERE_API_KEY = 'rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn';
const COHERE_BASE_URL = 'https://api.cohere.com/compatibility/v1';
const MODEL_NAME = 'command-a-03-2025';

const BENCHMARK_PROMPTS = [
  { n: 1,  text: 'What files are in my project?', category: 'file_tool' },
  { n: 2,  text: 'Search the web for Python async best practices', category: 'web_tool' },
  { n: 3,  text: 'Read the README and summarize it', category: 'file+reasoning' },
  { n: 4,  text: 'Remember that I prefer dark mode', category: 'memory_store' },
  { n: 5,  text: 'What did I ask you to remember?', category: 'memory_recall' },
  { n: 6,  text: 'Create a todo list for my project', category: 'file_write' },
  { n: 7,  text: 'Check my git status', category: 'git_tool' },
  { n: 8,  text: 'What tools do you have available?', category: 'introspection' },
  { n: 9,  text: 'List all test files and tell me which are slow', category: 'file+analysis' },
  { n: 10, text: 'Write a Python function to calculate fibonacci', category: 'code_gen' },
  { n: 11, text: 'Show me my recent memory trajectory', category: 'memory_query' },
  { n: 12, text: 'Summarize everything we have done in this session', category: 'memory+reasoning' },
];

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function main() {
  console.log('=== IRIS Live Benchmark ===');
  console.log(`URL: ${IRIS_URL}`);
  console.log(`Model: ${MODEL_NAME}`);

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 }
  });
  const page = await context.newPage();

  // Intercept WebSocket messages for timing
  const wsTimings = [];
  page.on('websocket', ws => {
    ws.on('framesent', frame => {
      try {
        const data = JSON.parse(frame.payload);
        wsTimings.push({ type: 'send', time: Date.now(), data });
      } catch {}
    });
    ws.on('framereceived', frame => {
      try {
        const data = JSON.parse(frame.payload);
        wsTimings.push({ type: 'recv', time: Date.now(), data });
      } catch {}
    });
  });

  // Navigate to IRIS
  console.log('\n[1/5] Loading IRIS frontend...');
  await page.goto(IRIS_URL, { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(2000);
  console.log('  ✓ IRIS loaded');

  // Take initial screenshot
  await page.screenshot({ path: 'benchmarks/output/01-initial-view.png', fullPage: false });

  // Step 2: Find the chat input and configure API
  console.log('\n[2/5] Configuring API via settings...');

  // Click the chat activation text to open the chat panel
  // The chat-activation-text shows "Tap here for chat" below the iris orb
  const chatTrigger = page.locator('text=Tap here for chat, Tap iris for menu, Double-click for');
  const chatTriggerAny = page.locator('text=/Tap here|Tap iris|Double-click/');
  
  if (await chatTriggerAny.count() > 0) {
    await chatTriggerAny.first().click();
    console.log('  ✓ Clicked chat activation text');
    await sleep(1500);
  } else {
    console.log('  - Chat trigger not found, trying alternatives...');
  }

  // Take screenshot after opening
  await page.screenshot({ path: 'benchmarks/output/02-chat-opened.png' });

  // Try to find and interact with the chat input
  const chatInput = page.locator('input[type="text"], textarea, [contenteditable="true"], input[placeholder*="message" i], input[placeholder*="chat" i], input[placeholder*="type" i]');
  
  if (await chatInput.count() > 0) {
    console.log('  ✓ Chat input found');
    
    // Check if there's a settings/dashboard button to configure the API
    // Look for BarChart3 icon button (Dashboard) to open settings
    const dashboardBtn = page.locator('button:has(svg), [title*="Dashboard" i], [title*="Settings" i]');
    const btnCount = await dashboardBtn.count();
    console.log(`  Found ${btnCount} buttons with icons`);

    // For now, let's try to send a message directly
    // The backend should respond with a "not configured" message since no API is set
    console.log('\n[3/5] Running benchmark prompts...');

    const results = [];

    for (const prompt of BENCHMARK_PROMPTS.slice(0, 3)) { // Start with first 3
      console.log(`\n  Round ${prompt.n}: "${prompt.text.substring(0, 50)}..."`);
      
      // Clear and type
      await chatInput.first().fill('');
      await sleep(300);
      await chatInput.first().fill(prompt.text);
      await sleep(200);

      // Send (Enter key)
      const sendStart = Date.now();
      await chatInput.first().press('Enter');
      
      // Wait for response - look for assistant messages
      let firstTokenTime = null;
      let responseText = '';
      
      for (let i = 0; i < 60; i++) { // Wait up to 60s
        await sleep(1000);
        
        if (firstTokenTime === null) {
          firstTokenTime = Date.now();
        }
        
        // Check if typing indicator stopped (response complete)
        const typingVisible = await page.locator('[class*="typing"], [class*="Typing"]').count();
        
        // Look for the last assistant message
        const messages = await page.locator('text=/.*/').all();
        
        if (typingVisible === 0 && i > 5) {
          // Response seems complete
          const timeToFirstToken = firstTokenTime - sendStart;
          const totalTime = Date.now() - sendStart;
          
          results.push({
            round: prompt.n,
            category: prompt.category,
            timeToFirstToken,
            totalTime,
            response: responseText.substring(0, 200)
          });
          
          console.log(`     Time-to-first-token: ${timeToFirstToken}ms`);
          console.log(`     Total time: ${totalTime}ms`);
          break;
        }
      }
    }

    // Print results
    console.log('\n\n=== PRELIMINARY RESULTS ===');
    console.log('Round | Category | TTFB | Total');
    console.log('------|----------|------|------');
    for (const r of results) {
      console.log(`  ${r.round}  | ${r.category.padEnd(15)} | ${r.timeToFirstToken}ms | ${r.totalTime}ms`);
    }

  } else {
    console.log('  ✗ Chat input not found');
    await page.screenshot({ path: 'benchmarks/output/03-no-input.png' });
  }

  // Final screenshot
  await page.screenshot({ path: 'benchmarks/output/04-final.png' });

  await browser.close();
  console.log('\n✓ Benchmark session complete');
}

main().catch(err => {
  console.error('Benchmark failed:', err);
  process.exit(1);
});
