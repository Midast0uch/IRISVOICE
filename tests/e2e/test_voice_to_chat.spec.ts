/**
 * E2E tests for the Parakeet ASR voice → chat pipeline (PR 3 + PR 4).
 *
 * These tests verify that the CustomEvent wiring between useIRISWebSocket.ts
 * and chat-view.tsx works correctly.
 *
 * == How it works ==
 *   Backend (IRIS gateway) ──WS──→ useIRISWebSocket.ts ──CustomEvent──→ chat-view.tsx
 *                                       ↑                              ↑
 *                                   tts_word / voice_result      iris:tts_word /
 *                                                                 iris:voice_final
 *
 * We test the RIGHT side (CustomEvent → DOM) by dispatching synthetic events
 * via page.evaluate.  We test the LEFT side (WS → CustomEvent) by mocking
 * the WebSocket with page.routeWebSocket.
 *
 * == Running ==
 *   npm run dev                     # start Next.js on :3000
 *   npx playwright test --config playwright.e2e.config.ts
 *
 * @module test_voice_to_chat
 */

import { expect, type Page, test } from "@playwright/test"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate to the app, open the chat wing, and wait for it to render. */
async function goToChat(page: Page) {
  await page.goto("/", { waitUntil: "networkidle", timeout: 15000 })
  // Wait for React hydration
  await page.waitForTimeout(1000)

  // The chat-view (ChatWing) is embedded inside the dashboard.  Clicking the
  // "→ Chat ←" label in the dock/wing triggers onOpenChat which sets
  // isChatOpen → true, mounting the chat-view component with its CustomEvent
  // listeners.
  const chatLabel = page.getByText("Chat", { exact: false }).first()
  if (await chatLabel.isVisible().catch(() => false)) {
    await chatLabel.click()
    // Allow the ChatWing transition animation + React state flush
    await page.waitForTimeout(1000)
  }
}

/**
 * Dispatch a CustomEvent on the window from inside the browser.
 */
async function dispatch(page: Page, eventType: string, detail: Record<string, unknown>) {
  await page.evaluate(
    ({ type, detail }: { type: string; detail: Record<string, unknown> }) => {
      window.dispatchEvent(new CustomEvent(type, { detail }))
    },
    { type: eventType, detail },
  )
}

/**
 * Check if a given text string exists somewhere in the page DOM.
 */
async function pageContains(page: Page, text: string): Promise<boolean> {
  return page.evaluate((t: string) => document.body.innerText.includes(t), text)
}

/**
 * Count how many times a text fragment appears on the page.
 * Used to detect duplicate messages.
 */
async function countTextOccurrences(page: Page, text: string): Promise<number> {
  return page.evaluate((t: string) => {
    const body = document.body.innerText
    let count = 0
    let pos = 0
    while ((pos = body.indexOf(t, pos)) !== -1) {
      count++
      pos += t.length
    }
    return count
  }, text)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Voice → Chat pipeline (PR 3 + PR 4)", () => {
  // ─── 1. voice_final displays transcript ────────────────────────────────
  test("iris:voice_final adds user transcript to the page", async ({ page }) => {
    await goToChat(page)

    await dispatch(page, "iris:voice_final", {
      text: "What is the weather like today?",
      confidence: 0.92,
      turn_id: "voice-test-001",
    })

    // Allow React state to flush and DOM to update
    await page.waitForTimeout(300)

    const found = await pageContains(page, "weather")
    expect(found).toBeTruthy()
  })

  // ─── 2. turn_id dedup on text_response ─────────────────────────────────
  test("same turn_id does not add duplicate assistant messages", async ({ page }) => {
    await goToChat(page)

    // First dispatch
    await dispatch(page, "iris:text_response", {
      text: "Hello! How can I help you?",
      sender: "assistant",
      turn_id: "dedup-test-001",
    })
    await page.waitForTimeout(200)

    const countAfterFirst = await countTextOccurrences(page, "How can I help you")
    expect(countAfterFirst).toBeGreaterThanOrEqual(1)

    // Second dispatch with the SAME turn_id (simulates WS replay / REST fallback)
    await dispatch(page, "iris:text_response", {
      text: "Hello! How can I help you?",
      sender: "assistant",
      turn_id: "dedup-test-001",
    })
    await page.waitForTimeout(200)

    const countAfterSecond = await countTextOccurrences(page, "How can I help you")
    // Should not have increased
    expect(countAfterSecond).toBe(countAfterFirst)
  })

  // ─── 3. Different turn_ids → both appear ───────────────────────────────
  test("different turn_ids add separate messages", async ({ page }) => {
    await goToChat(page)

    await dispatch(page, "iris:text_response", {
      text: "First message content A",
      sender: "assistant",
      turn_id: "multi-msg-001",
    })
    await page.waitForTimeout(150)

    await dispatch(page, "iris:text_response", {
      text: "Second message content B",
      sender: "assistant",
      turn_id: "multi-msg-002",
    })
    await page.waitForTimeout(150)

    const found1 = await pageContains(page, "First message")
    const found2 = await pageContains(page, "Second message")
    expect(found1).toBeTruthy()
    expect(found2).toBeTruthy()
  })

  // ─── 4. voice_final dedup by turn_id ───────────────────────────────────
  test("same turn_id on voice_final does not duplicate user message", async ({ page }) => {
    await goToChat(page)

    await dispatch(page, "iris:voice_final", {
      text: "Repeat this text phrase",
      turn_id: "voice-dedup-001",
    })
    await page.waitForTimeout(150)

    const countAfterFirst = await countTextOccurrences(page, "Repeat this text phrase")
    expect(countAfterFirst).toBeGreaterThanOrEqual(1)

    await dispatch(page, "iris:voice_final", {
      text: "Repeat this text phrase",
      turn_id: "voice-dedup-001",
    })
    await page.waitForTimeout(150)

    const countAfterSecond = await countTextOccurrences(page, "Repeat this text phrase")
    expect(countAfterSecond).toBe(countAfterFirst)
  })

  // ─── 5. text_response without turn_id (backward compat) ────────────────
  test("text_response without turn_id falls through and still works", async ({ page }) => {
    await goToChat(page)

    await dispatch(page, "iris:text_response", {
      text: "Legacy message without turn_id",
      sender: "assistant",
      // no turn_id — must still render
    })
    await page.waitForTimeout(200)

    const found = await pageContains(page, "Legacy message")
    expect(found).toBeTruthy()
  })

  // ─── 6. tts_word event fires without crashing ──────────────────────────
  test("iris:tts_word event does not cause JS errors", async ({ page }) => {
    await goToChat(page)

    const jsErrors: string[] = []
    page.on("pageerror", (err) => jsErrors.push(err.message))

    await dispatch(page, "iris:tts_word", {
      word_index: 5,
      total_words: 10,
      is_final: false,
    })

    await page.waitForTimeout(100)
    expect(jsErrors.length).toBe(0)
  })

  // ─── 7. WS message integration (routeWebSocket mock) ───────────────────
  test("voice_result WS message dispatches iris:voice_final CustomEvent", async ({ page }) => {
    let wsSend: ((msg: string) => void) | null = null
    let wsConnected = false

    await page.routeWebSocket("**/ws/iris", (ws) => {
      ws.onMessage(() => {
        // client sent something — ignore for this test
      })
      ws.onClose(() => { wsConnected = false })
      wsConnected = true
      wsSend = (msg: string) => { ws.send(msg) }

      // Send initial state so the app doesn't wait indefinitely
      ws.send(JSON.stringify({
        type: "initial_state",
        payload: {
          state: { active_conversation: null, conversations: [], settings: {} },
        },
      }))
    })

    await goToChat(page)
    // Wait for WS to connect and app to process initial state
    await page.waitForTimeout(1500)

    if (!wsConnected) {
      test.skip(true, "WebSocket connection was not established")
      return
    }

    // Listen for the CustomEvent
    const customEventFired = page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        const handler = () => {
          window.removeEventListener("iris:voice_final", handler)
          resolve(true)
        }
        window.addEventListener("iris:voice_final", handler)
        setTimeout(() => {
          window.removeEventListener("iris:voice_final", handler)
          resolve(false)
        }, 3000)
      })
    })

    // Simulate backend sending voice_result
    if (wsSend) {
      wsSend(JSON.stringify({
        type: "voice_result",
        payload: {
          text: "Hello from Parakeet mock",
          confidence: 0.95,
          turn_id: "ws-mock-001",
        },
      }))
    }

    const fired = await customEventFired
    expect(fired).toBeTruthy()
  })

  // ─── 8. tts_word WS message dispatches iris:tts_word CustomEvent ───────
  test("tts_word WS message dispatches iris:tts_word CustomEvent", async ({ page }) => {
    let wsSend: ((msg: string) => void) | null = null
    let wsConnected = false

    await page.routeWebSocket("**/ws/iris", (ws) => {
      ws.onMessage(() => {})
      ws.onClose(() => { wsConnected = false })
      wsConnected = true
      wsSend = (msg: string) => { ws.send(msg) }
      ws.send(JSON.stringify({
        type: "initial_state",
        payload: {
          state: { active_conversation: null, conversations: [], settings: {} },
        },
      }))
    })

    await goToChat(page)
    await page.waitForTimeout(1500)

    if (!wsConnected) {
      test.skip(true, "WebSocket connection was not established")
      return
    }

    const customEventFired = page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        const handler = () => {
          window.removeEventListener("iris:tts_word", handler)
          resolve(true)
        }
        window.addEventListener("iris:tts_word", handler)
        setTimeout(() => {
          window.removeEventListener("iris:tts_word", handler)
          resolve(false)
        }, 3000)
      })
    })

    if (wsSend) {
      wsSend(JSON.stringify({
        type: "tts_word",
        payload: {
          word_index: 3,
          total_words: 8,
          is_final: false,
        },
      }))
    }

    const fired = await customEventFired
    expect(fired).toBeTruthy()
  })
})
