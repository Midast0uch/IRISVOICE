import { chromium } from 'playwright';

const COHERE_KEY = 'rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn';

const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox']
});

const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

// Log websocket messages
page.on('websocket', ws => {
  ws.on('framesent', frame => {
    try { const d = JSON.parse(frame.payload); if (d.type === 'text_message') console.log('>>', d.payload?.text?.slice(0, 80)); } catch {}
  });
  ws.on('framereceived', frame => {
    try { const d = JSON.parse(frame.payload); if (d.type === 'chat_chunk') process.stdout.write(d.payload?.chunk || ''); if (d.type === 'chat_message') console.log('\n[DONE]'); } catch {}
  });
});

// Load page - use domcontentloaded to avoid WebSocket idle hang
await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 10000 });
await page.waitForTimeout(5000);
console.log('Page loaded: ' + await page.title());

// Take a screenshot
await page.screenshot({ path: 'benchmarks/output/01-loaded.png' });

// Find and click the "Tap iris for menu" text using evaluate + real click
const found = await page.evaluate(() => {
  const all = document.querySelectorAll('p, span, div');
  for (const el of all) {
    const t = el.textContent?.trim() || '';
    if ((t.includes('Tap') || t.includes('Double-click') || t.includes('chat')) && t.length < 50) {
      const r = el.getBoundingClientRect();
      if (r.width > 10 && r.height > 5) {
        return { x: r.x + r.width/2, y: r.y + r.height/2, text: t.slice(0, 40) };
      }
    }
  }
  return null;
});

if (found) {
  console.log(`Found text: "${found.text}" at (${found.x}, ${found.y})`);
  await page.mouse.click(found.x, found.y);
  await page.waitForTimeout(1500);
} else {
  console.log('Text not found, clicking center...');
  await page.mouse.click(640, 180);
  await page.waitForTimeout(1500);
}

await page.screenshot({ path: 'benchmarks/output/02-after-click.png' });

// Dump what's visible now
const state = await page.evaluate(() => {
  return document.body.innerText.substring(0, 1000);
});
console.log('State after click:', state);

await browser.close();
