import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

await page.goto('http://localhost:3000', { timeout: 10000, waitUntil: 'domcontentloaded' });
await page.waitForTimeout(5000);

// Dump full DOM structure at center of page (z-index, visibility)
const domInfo = await page.evaluate(() => {
  // Get ALL elements with their positions and z-indices
  const all = document.querySelectorAll('*');
  const results = [];
  
  // Focus on center area (x: 500-780, y: 100-500)
  all.forEach(el => {
    const r = el.getBoundingClientRect();
    const tag = el.tagName.toLowerCase();
    const text = el.textContent?.trim()?.slice(0, 80) || '';
    
    // Only show elements in the center region
    if (r.x > 500 && r.x < 780 && r.y > 100 && r.y < 500 && r.width > 5 && r.height > 5) {
      const z = parseInt(getComputedStyle(el).zIndex) || 0;
      const pe = getComputedStyle(el).pointerEvents;
      results.push({
        tag, text: text.slice(0, 60),
        z, pe,
        x: Math.round(r.x), y: Math.round(r.y), 
        w: Math.round(r.width), h: Math.round(r.height),
        opacity: getComputedStyle(el).opacity,
        display: getComputedStyle(el).display,
        visibility: getComputedStyle(el).visibility,
      });
    }
  });
  
  return results.sort((a, b) => a.z - b.z);
});

console.log('=== Elements in center region (sorted by z-index) ===');
domInfo.forEach(e => {
  console.log(`  z=${e.z} [${e.tag}] (${e.x},${e.y}) ${e.w}x${e.h} op=${e.opacity} pe=${e.pe} "${e.text}"`);
});

// Also dump the full page HTML structure (just first levels)
const structure = await page.evaluate(() => {
  function getStructure(el, depth = 0) {
    if (depth > 3) return '';
    let result = '';
    const indent = '  '.repeat(depth);
    const tag = el.tagName.toLowerCase();
    const text = el.textContent?.trim()?.slice(0, 40) || '';
    const cls = (el.className || '').slice(0, 40);
    const r = el.getBoundingClientRect();
    
    if (r.width > 10 && r.height > 10) {
      result += `${indent}<${tag} class="${cls}" (${Math.round(r.x)},${Math.round(r.y)}) ${Math.round(r.w)}x${Math.round(r.h)}>\n`;
      if (text && !['script', 'style'].includes(tag)) {
        result += `${indent}  "${text}"\n`;
      }
      for (const child of el.children) {
        result += getStructure(child, depth + 1);
      }
    }
    return result;
  }
  return getStructure(document.body);
});

console.log('\n=== Page structure ===');
console.log(structure.slice(0, 5000));

await page.screenshot({ path: 'benchmarks/output/06-structure.png' });
await browser.close();
