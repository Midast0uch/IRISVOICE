import { chromium } from 'playwright';

const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
});

const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

await page.goto('http://localhost:3000', { timeout: 10000, waitUntil: 'domcontentloaded' });
await page.waitForTimeout(3000);

console.log('=== Looking for the chat trigger text ===');

// Find and click the actual DOM element that says "Tap iris for menu"
const clicked = await page.evaluate(() => {
  // Find the text node or element containing "Tap iris"
  const allElements = document.querySelectorAll('*');
  for (const el of allElements) {
    if (el.textContent?.includes('Tap iris') && el.offsetWidth > 0) {
      const rect = el.getBoundingClientRect();
      console.log(`Found element at (${rect.x}, ${rect.y}) size ${rect.width}x${rect.height}`);
      console.log(`Tag: ${el.tagName}, Class: ${el.className?.slice(0, 60)}`);
      // Click it via dispatch
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      return { found: true, tag: el.tagName, x: rect.x, y: rect.y };
    }
  }
  return { found: false };
});

console.log(JSON.stringify(clicked));
await page.waitForTimeout(2000);

// Check what changed
const textAfter = await page.evaluate(() => {
  return Array.from(document.querySelectorAll('*'))
    .filter(el => el.offsetWidth > 5 && el.textContent?.trim())
    .slice(0, 30)
    .map(el => ({ tag: el.tagName, text: el.textContent.trim().slice(0, 50) }));
});

console.log('\n=== Elements after click ===');
textAfter.forEach(e => console.log(`  [${e.tag}] "${e.text}"`));

// Also look for any chat input or messages
const chatElements = await page.evaluate(() => {
  return Array.from(document.querySelectorAll('input, textarea, [contenteditable], [role="textbox"]'))
    .filter(el => el.offsetWidth > 5)
    .map(el => ({
      tag: el.tagName,
      placeholder: el.placeholder || '',
      class: (el.className || '').slice(0, 40),
      x: Math.round(el.getBoundingClientRect().x),
      y: Math.round(el.getBoundingClientRect().y),
    }));
});

console.log('\n=== Input elements ===');
chatElements.forEach(e => console.log(`  [${e.tag}] placeholder="${e.placeholder}" at (${e.x},${e.y})`));

await page.screenshot({ path: 'benchmarks/output/03-after-precise-click.png' });
await browser.close();
