import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

// Capture console errors
page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
page.on('console', msg => {
  if (msg.type() === 'error') console.log('CONSOLE ERROR:', msg.text());
});

console.log('Navigating...');
await page.goto('http://localhost:3000', { timeout: 15000, waitUntil: 'load' });
console.log('Page loaded, waiting for hydration...');
await page.waitForTimeout(8000);

// Now check actual layout
const layout = await page.evaluate(() => {
  const items = [];
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.x > -1 && r.y > -1 && r.x < 1280 && r.y < 800) {
      const text = el.textContent?.trim()?.slice(0, 50) || '';
      const tag = el.tagName.toLowerCase();
      const z = parseInt(getComputedStyle(el).zIndex) || 0;
      if (text && tag !== 'script' && tag !== 'style') {
        items.push({
          tag, text, z,
          x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
          pe: getComputedStyle(el).pointerEvents,
          visible: getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).opacity !== '0'
        });
      }
    }
  });
  return items;
});

console.log('\n=== ALL visible elements ===');
layout.filter(e => e.visible).forEach(e => {
  console.log(`  z=${e.z} [${e.tag}] (${e.x},${e.y}) ${e.w}x${e.h} "${e.text}"`);
});

await page.screenshot({ path: 'benchmarks/output/07-full-layout.png' });
await browser.close();
