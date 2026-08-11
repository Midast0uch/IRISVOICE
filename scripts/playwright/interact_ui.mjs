import { chromium } from 'playwright';

const COHERE_KEY = 'rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn';
const COHERE_URL = 'https://api.cohere.com/compatibility/v1';
const MODEL = 'command-a-03-2025';

const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
});

const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

// Log WebSocket messages for debugging
const wsMessages = [];
page.on('websocket', ws => {
  ws.on('framesent', frame => {
    try { wsMessages.push({ dir: '>>', payload: JSON.parse(frame.payload) }); } catch {}
  });
  ws.on('framereceived', frame => {
    try { wsMessages.push({ dir: '<<', payload: JSON.parse(frame.payload) }); } catch {}
  });
});

await page.goto('http://localhost:3000', { waitUntil: 'load', timeout: 15000 });
await page.waitForTimeout(2000);

console.log('Page loaded');

// Step 1: Click "Tap iris for menu" to open chat
const tapText = page.locator('text=Tap iris for menu, Tap here for chat, Double-click for');
let clicked = false;

// Try clicking by coordinates - the text is roughly at (640, 175) center of screen
if (await page.locator('text=/Tap (iris|here)/').count() > 0) {
  await page.locator('text=/Tap (iris|here)/').first().click();
  clicked = true;
  console.log('Clicked tap text');
} else {
  // Fallback: click center of screen
  await page.mouse.click(640, 180);
  clicked = true;
  console.log('Clicked at center (640, 180)');
}

await page.waitForTimeout(2000);
await page.screenshot({ path: 'benchmarks/output/02-chat-opened.png' });

// Look for the chat panel elements
const afterClick = await page.evaluate(() => {
  const items = [];
  document.querySelectorAll('button, a, input, textarea, [role="button"], [role="textbox"]').forEach(el => {
    const text = el.textContent?.trim() || el.getAttribute('aria-label') || el.placeholder || el.getAttribute('title') || '';
    if (!text && !el.placeholder) return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 5 || rect.height < 5) return;
    items.push({ 
      tag: el.tagName.toLowerCase(),
      text: text.slice(0, 60),
      placeholder: (el.placeholder || '').slice(0, 40),
      title: (el.getAttribute('title') || '').slice(0, 40),
      class: (el.className || '').slice(0, 30),
      x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.w), h: Math.round(rect.h)
    });
  });
  return items;
});

console.log('\n=== Interactive elements after click ===');
afterClick.forEach(e => {
  if (e.x < 1280 && e.y < 800 && e.x + e.w > 0) {
    console.log(`  [${e.tag}] (${e.x},${e.y}) ${e.w}x${e.h} "${e.text || e.placeholder || e.title}"`);
  }
});

// Log WS messages
console.log('\n=== WebSocket Messages ===');
wsMessages.slice(0, 10).forEach(m => {
  const p = m.payload;
  console.log(`  ${m.dir} ${p.type || '?'} ${JSON.stringify(p).slice(0, 250)}`);
});

console.log(`\nTotal WS messages: ${wsMessages.length}`);

await browser.close();
