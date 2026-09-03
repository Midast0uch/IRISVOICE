import { test, expect, Page } from '@playwright/test'
import { writeFileSync, appendFileSync, existsSync, mkdirSync, readFileSync } from 'fs'
import { join } from 'path'

// Load .env.benchmark if present (never commit this file)
try {
  const envPath = join(process.cwd(), '.env.benchmark')
  if (existsSync(envPath)) {
    const envContent = readFileSync(envPath, 'utf-8')
    for (const line of envContent.split('\n')) {
      const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/)
      if (match && process.env[match[1]] === undefined) {
        process.env[match[1]] = match[2].replace(/^["']|["']$/g, '')
      }
    }
  }
} catch { /* ignore */ }

const EXPECTED_PROVIDER = process.env.IRIS_BENCHMARK_PROVIDER ?? 'any'
const EXPECTED_MODEL = process.env.IRIS_BENCHMARK_MODEL ?? 'any'

interface RunMetrics {
  prompt: string
  sendTime: number
  firstChunkTime: number | null
  finalMessageTime: number | null
  ttftMs: number | null
  e2eMs: number | null
  success: boolean
  error?: string
  model?: string
  provider?: string
  tps?: number
}

const RESULTS_FILE = join(process.cwd(), 'test-results', 'benchmark-latency.jsonl')
const PROMPTS = [
  "What is 2+2?",
  "Explain quantum computing in one sentence.",
  "Write a Python function that reverses a string.",
]

function ensureResultsDir() {
  const dir = join(process.cwd(), 'test-results')
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
}

function logResult(run: RunMetrics) {
  ensureResultsDir()
  appendFileSync(RESULTS_FILE, JSON.stringify(run) + '\n')
}

async function waitForChatOpen(page: Page) {
  // The activation text container animates continuously (scale + text cycling).
  // We wait for the text to appear, then click the container with force: true
  // because Playwright's stability check fails on never-ending animations.
  const activationText = page.locator('text=/Tap here for chat|Tap iris for menu|Double-click for/i').first()
  await activationText.waitFor({ timeout: 60000 })

  // Click the nearest positioned ancestor (the motion.div container)
  const activationContainer = activationText.locator('xpath=ancestor::div[contains(@class, "cursor-pointer")]').first()
  await activationContainer.click({ force: true })

  // Wait for the chat textarea to appear
  const textarea = page.locator('textarea[placeholder*="Type command"], textarea[placeholder*="Listening"]').first()
  await textarea.waitFor({ timeout: 5000 })
  return textarea
}

// Capture inference_event via WS to identify model/provider
let _lastInferenceEvent: any = null

function setupInferenceListener(page: Page) {
  page.on('websocket', (ws) => {
    ws.on('framereceived', (data) => {
      try {
        const msg = JSON.parse(data.payload as string)
        if (msg.type === 'inference_event' && msg.payload) {
          _lastInferenceEvent = msg.payload
        }
      } catch { /* ignore non-JSON frames */ }
    })
  })
}

async function measureLatency(page: Page, prompt: string): Promise<RunMetrics> {
  const textarea = await waitForChatOpen(page)

  // Reset inference capture
  _lastInferenceEvent = null

  // Clear any existing text and type prompt
  await textarea.fill(prompt)

  // Count messages before send
  const messagesBefore = await page.locator('[id^="msg-"]').count()

  // Send message (Enter key)
  const sendTime = Date.now()
  await textarea.press('Enter')

  let firstChunkTime: number | null = null
  let finalMessageTime: number | null = null
  let success = false
  let error: string | undefined

  try {
    // Wait for typing indicator to appear (signals backend received message)
    await page.locator('text=/thinking|Typing|Processing/i').first().waitFor({ timeout: 5000 })
  } catch {
    // Typing indicator may not appear for very fast responses
  }

  // Poll for new message appearing (first chunk / final message)
  for (let i = 0; i < 120; i++) { // 120 * 500ms = 60s max
    await page.waitForTimeout(500)
    const messagesNow = await page.locator('[id^="msg-"]').count()

    if (messagesNow > messagesBefore && firstChunkTime === null) {
      firstChunkTime = Date.now()
    }

    // Check if typing indicator is gone AND we have more messages
    const typingVisible = await page.locator('text=/thinking|Typing|Processing/i').first().isVisible().catch(() => false)
    if (firstChunkTime !== null && !typingVisible) {
      finalMessageTime = Date.now()
      success = true
      break
    }
  }

  if (firstChunkTime === null) {
    error = 'No response received within 60s'
  } else if (finalMessageTime === null) {
    // Partial response — use first chunk as best-effort final
    finalMessageTime = firstChunkTime
    success = true
  }

  const ttftMs = firstChunkTime ? firstChunkTime - sendTime : null
  const e2eMs = finalMessageTime ? finalMessageTime - sendTime : null

  // Give WS a moment to deliver inference_event
  await page.waitForTimeout(200)
  const model = _lastInferenceEvent?.model as string | undefined
  const tps = _lastInferenceEvent?.tps as number | undefined

  return {
    prompt,
    sendTime,
    firstChunkTime,
    finalMessageTime,
    ttftMs,
    e2eMs,
    success,
    error,
    model,
    tps,
  }
}

test.describe.configure({ mode: 'serial' })

test.describe('IRIS Chat Latency Benchmark', () => {
  test.setTimeout(180_000) // 180s: slow filesystem dev cold-start + WS response

  test.beforeEach(async ({ page }) => {
    // Warm-up: Next.js dev server may cold-compile on first request.
    // On slow filesystems this can take 60-90s.  We retry once.
    let navigated = false
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        await page.goto('/', { timeout: 90000, waitUntil: 'domcontentloaded' })
        navigated = true
        break
      } catch {
        if (attempt === 0) {
          console.log('[benchmark] Navigation timeout, retrying after 5s...')
          await page.waitForTimeout(5000)
        }
      }
    }
    if (!navigated) {
      await page.screenshot({ path: 'test-results/benchmark-nav-failure.png' })
      throw new Error('Failed to navigate to IRIS app after 2 attempts')
    }
    // Wait for IRIS UI to mount (orb + activation text)
    await page.waitForLoadState('networkidle', { timeout: 60000 })
    await page.waitForTimeout(5000) // Allow WS connection + animations + model loading

    // Listen for inference events on the WS
    setupInferenceListener(page)
  })

  test('baseline latency with simple prompts', async ({ page }) => {
    test.setTimeout(600000) // 10 min for local model cold-start
    const results: RunMetrics[] = []

    for (const prompt of PROMPTS) {
      const run = await measureLatency(page, prompt)
      results.push(run)
      logResult(run)

      // Small pause between runs to let backend settle
      await page.waitForTimeout(2000)
    }

    // Summary console output
    const actualModel = results.find(r => r.model)?.model ?? 'unknown'
    console.log('\n=== Benchmark Results ===')
    console.log(`Expected: ${EXPECTED_PROVIDER}/${EXPECTED_MODEL}`)
    console.log(`Actual model: ${actualModel}`)
    if (EXPECTED_PROVIDER !== 'any' && !actualModel.toLowerCase().includes(EXPECTED_PROVIDER.toLowerCase())) {
      console.warn(`⚠ Provider mismatch! Expected ${EXPECTED_PROVIDER} but got ${actualModel}`)
      console.warn('  → Configure the correct provider in IRIS Settings before benchmarking.')
    }
    for (const r of results) {
      const ttft = r.ttftMs !== null ? `${r.ttftMs}ms` : 'N/A'
      const e2e = r.e2eMs !== null ? `${r.e2eMs}ms` : 'N/A'
      const status = r.success ? '✓' : '✗'
      const tps = r.tps !== undefined ? `${r.tps} tok/s` : ''
      console.log(`${status} "${r.prompt}" → TTFT: ${ttft} | E2E: ${e2e} ${tps}`)
    }

    const successful = results.filter(r => r.success && r.ttftMs !== null)
    if (successful.length > 0) {
      const avgTtft = successful.reduce((s, r) => s + (r.ttftMs || 0), 0) / successful.length
      const avgE2e = successful.reduce((s, r) => s + (r.e2eMs || 0), 0) / successful.length
      console.log(`\nAverages — TTFT: ${avgTtft.toFixed(0)}ms | E2E: ${avgE2e.toFixed(0)}ms`)
    }

    // Assert baseline sanity (should complete within 60s)
    expect(results.some(r => r.success)).toBe(true)
  })

  test('streaming stability — rapid consecutive sends', async ({ page }) => {
    test.setTimeout(600000) // 10 min for local model
    const prompt = "Count from 1 to 5."
    const results: RunMetrics[] = []

    for (let i = 0; i < 3; i++) {
      const run = await measureLatency(page, prompt)
      results.push(run)
      logResult(run)
      await page.waitForTimeout(1500)
    }

    // All 3 should succeed
    expect(results.every(r => r.success)).toBe(true)
  })
})
