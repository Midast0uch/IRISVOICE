import { chromium } from 'playwright';

const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
});

const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

await page.goto('http://localhost:3000', { timeout: 10000, waitUntil: 'domcontentloaded' });
await page.waitForTimeout(5000);

// Take initial screenshot
await page.screenshot({ path: 'benchmarks/output/01-initial.png' });

// Find all clickable elements and their event handlers
const layout = await page.evaluate(() => {
  const items = [];
  document.querySelectorAll('*').forEach(el => {
    const text = el.textContent?.trim();
    if (!text || text.length > 100 || text.length < 2) return;
    const r = el.getBoundingClientRect();
    if (r.width < 5 || r.height < 5) return;
    const hasClick = el.hasAttribute('onclick') || el.tagName === 'BUTTON' || el.tagName === 'A' || el.getAttribute('role') === 'button';
    items.push({
      tag: el.tagName.toLowerCase(),
      text: text.slice(0, 40),
      hasClick,
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      zIndex: parseInt(getComputedStyle(el).zIndex) || 0,
      pointerEvents: getComputedStyle(el).pointerEvents,
    });
  });
  return items;
});

console.log('=== Elements with text ===');
layout.filter(e => e.pointerEvents !== 'none').forEach(e => {
  console.log(`  [${e.tag}] "${e.text}" ${e.hasClick ? 'CLICKABLE' : ''} z=${e.zIndex} (${e.x},${e.y}) ${e.w}x${e.h}`);
});

// Try clicking the ChatActivationText container by finding the motion.div
const clickResult = await page.evaluate(() => {
  // Find the motion.div containing the cycling text
  // It should be a motion div that's a child of the main container
  const allDivs = document.querySelectorAll('div, p, span');
  for (const el of allDivs) {
    const text = el.textContent?.trim() || '';
    if ((text.includes('Tap') || text.includes('Double-click') || text.includes('chat')) && text.length < 80) {
      const r = el.getBoundingClientRect();
      if (r.width > 10 && r.height > 10 && r.x > 300 && r.x < 900) {
        // Found it - click using dispatchEvent with proper MouseEvent
        const event = new MouseEvent('click', {
          bubbles: true,
          cancelable: true,
          view: window,
          clientX: r.x + r.width / 2,
          clientY: r.y + r.height / 2,
        });
        el.dispatchEvent(event);
        return { found: true, text: text.slice(0, 40), tag: el.tagName, x: Math.round(r.x), y: Math.round(r.y) };
      }
    }
  }
  return { found: false };
});

console.log(`\nClicked: ${JSON.stringify(clickResult)}`);
await page.waitForTimeout(2000);

// Check if chat opened by looking for new DOM elements
const afterState = await page.evaluate(() => {
  // Check for text input (chat input)
  const inputs = [];
  document.querySelectorAll('input[type="text"], input:not([type="hidden"]), textarea, [contenteditable="true"]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 20) inputs.push({
      tag: el.tagName,
      placeholder: el.placeholder || '',
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)
    });
  });
  
  // Check for chat panel
  const panels = [];
  document.querySelectorAll('[class*="chat"], [class*="Chat"], [class*="message"], [role="dialog"]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 50) panels.push({ tag: el.tagName, class: (el.className || '').slice(0, 50), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width) });
  });
  
  return { inputs, panels, buttons: document.querySelectorAll('button').length };
});

console.log(`\n=== After click state ===`);
console.log(`Inputs: ${afterState.inputs.length}, Panels: ${afterState.panels.length}, Buttons: ${afterState.buttons}`);
afterState.inputs.forEach(i => console.log(`  Input: placeholder="${i.placeholder}" at (${i.x},${i.y}) ${i.w}x${i.h}`));
afterState.panels.forEach(p => console.log(`  Panel: class="${p.class}" at (${p.x},${p.y})`));

await page.screenshot({ path: 'benchmarks/output/02-after-click.png' });
await browser.close();
