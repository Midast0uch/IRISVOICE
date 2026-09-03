import { chromium } from 'playwright';

const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
});

const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

// Navigate with shorter timeout
await page.goto('http://localhost:3000', { timeout: 10000, waitUntil: 'domcontentloaded' });
await page.waitForTimeout(3000);

// Screenshot
await page.screenshot({ path: 'benchmarks/output/01-initial.png' });

// Dump ALL text nodes to find what's visible
const allText = await page.evaluate(() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) {
    const t = walker.currentNode.textContent.trim();
    if (t) texts.push(t.slice(0, 100));
  }
  return texts;
});
console.log('=== All visible text ===');
allText.forEach(t => console.log(`  "${t}"`));

// Try clicking the IRIS orb (center of page, slightly above middle)
// From v4: "Tap iris for menu" was at (640, 175)
console.log('\nClicking at (640, 180)...');
await page.mouse.click(640, 180);
await page.waitForTimeout(2000);

// Check what changed
const allText2 = await page.evaluate(() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) {
    const t = walker.currentNode.textContent.trim();
    if (t) texts.push(t.slice(0, 100));
  }
  return texts;
});
console.log('\n=== After click ===');
allText2.forEach(t => console.log(`  "${t}"`));

// Show new elements
const afterClick = await page.evaluate(() => {
  return Array.from(document.querySelectorAll('button, input, textarea, [role="button"], [role="textbox"], [contenteditable]'))
    .filter(el => el.offsetWidth > 5)
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      text: (el.textContent || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 60),
      x: Math.round(el.getBoundingClientRect().x),
      y: Math.round(el.getBoundingClientRect().y),
      w: Math.round(el.getBoundingClientRect().width),
      h: Math.round(el.getBoundingClientRect().height),
    }));
});
console.log('\n=== Interactive elements after click ===');
afterClick.forEach(e => console.log(`  [${e.tag}] (${e.x},${e.y}) ${e.w}x${e.h} "${e.text}"`));

await page.screenshot({ path: 'benchmarks/output/02-after-click.png' });
await browser.close();
console.log('\nDone');
