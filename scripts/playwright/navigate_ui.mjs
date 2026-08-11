import { chromium } from 'playwright';

const COHERE_KEY = 'rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn';
const COHERE_URL = 'https://api.cohere.com/compatibility/v1';
const MODEL = 'command-a-03-2025';

const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
});

const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

await page.goto('http://localhost:3000', { timeout: 10000, waitUntil: 'domcontentloaded' });
await page.waitForTimeout(4000);

await page.screenshot({ path: 'benchmarks/output/01-start.png' });

// Click iris orb to open category menu
await page.mouse.click(640, 180);
await page.waitForTimeout(1500);

// Get category positions
const cats = await page.evaluate(() => {
  const items = Array.from(document.querySelectorAll('button, [role="button"], a'))
    .filter(el => el.offsetWidth > 10 && el.textContent?.trim())
    .map(el => ({
      text: el.textContent.trim().slice(0, 20),
      x: Math.round(el.getBoundingClientRect().x + el.getBoundingClientRect().width / 2),
      y: Math.round(el.getBoundingClientRect().y + el.getBoundingClientRect().height / 2),
    }));
  return items;
});

console.log('=== Interactive elements ===');
cats.forEach(c => console.log(`  "${c.text}" at (${c.x}, ${c.y})`));

// Click "Agent" category
const agentBtn = cats.find(c => c.text.includes('Agent'));
if (agentBtn) {
  console.log(`\nClicking Agent at (${agentBtn.x}, ${agentBtn.y})`);
  await page.mouse.click(agentBtn.x, agentBtn.y);
  await page.waitForTimeout(2000);
  
  // Take screenshot
  await page.screenshot({ path: 'benchmarks/output/02-agent-category.png' });
  
  // See what sections appear
  const sections = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('button, [role="button"], [role="tab"], a'))
      .filter(el => el.offsetWidth > 10 && el.textContent?.trim())
      .map(el => ({
        text: el.textContent.trim().slice(0, 30),
        x: Math.round(el.getBoundingClientRect().x),
        y: Math.round(el.getBoundingClientRect().y),
      }));
  });
  
  console.log('\n=== Sections in Agent ===');
  sections.forEach(s => console.log(`  "${s.text}" at (${s.x}, ${s.y})`));
  
  // Find and click "Model Selection" card
  const modelCard = sections.find(s => s.text.includes('Model') || s.text.includes('model'));
  if (modelCard) {
    console.log(`\nClicking Model Selection at (${modelCard.x}, ${modelCard.y})`);
    await page.mouse.click(modelCard.x, modelCard.y);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'benchmarks/output/03-model-selection.png' });
    
    // Look for input fields, confirm button
    const inputs = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('input, textarea, button, select'))
        .filter(el => el.offsetWidth > 10)
        .map(el => ({
          tag: el.tagName,
          type: el.type || '',
          placeholder: el.placeholder || '',
          text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30),
          x: Math.round(el.getBoundingClientRect().x),
          y: Math.round(el.getBoundingClientRect().y),
        }));
    });
    
    console.log('\n=== Form elements ===');
    inputs.forEach(i => console.log(`  [${i.tag}] type=${i.type} placeholder="${i.placeholder}" text="${i.text}" at (${i.x},${i.y})`));
  }
}

await browser.close();
