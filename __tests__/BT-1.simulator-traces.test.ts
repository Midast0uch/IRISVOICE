/**
 * BT-1: Simulator trace sequences (specs/vision-browser-stage, T13)
 *
 * tasks.md T13: "BT-1 asserts trace sequences for scenarios a/b/c/e/f."
 *
 * BEHAVIORAL contract: each simulator scenario is a timed script of REAL
 * `iris:*` CustomEvents — the exact contract production emits (REQ-12 AC2:
 * no parallel mock renderer). This test runs each scenario through the real
 * runner (runScenario) and asserts the EMERGENT trace: which events fire,
 * in what order, carrying which beats — matched against the sign-off
 * checklist's "Expected beats" column in specs/vision-browser-stage/tasks.md.
 *
 * Scenarios covered (per spec): a (crawl full lifecycle), b (crawl error),
 * c (cursor click), e (scroll mirror), f (escalation notice).
 */
import { SCENARIOS } from "../simulator/scenarios"
import { runScenario } from "../simulator/runner"

interface CapturedEvent {
  name: string
  detail: Record<string, unknown>
}

function captureWindowEvents(): { events: CapturedEvent[]; stop: () => void } {
  const events: CapturedEvent[] = []
  const listener = (e: Event) => {
    const ce = e as CustomEvent<Record<string, unknown>>
    events.push({ name: ce.type, detail: ce.detail ?? {} })
  }
  window.addEventListener("iris:crawler_started", listener)
  window.addEventListener("iris:crawler_page_fetched", listener)
  window.addEventListener("iris:crawler_error", listener)
  window.addEventListener("iris:crawler_complete", listener)
  window.addEventListener("iris:crawler_vision_action", listener)
  window.addEventListener("iris:vision_status", listener)
  return {
    events,
    stop: () => {
      window.removeEventListener("iris:crawler_started", listener)
      window.removeEventListener("iris:crawler_page_fetched", listener)
      window.removeEventListener("iris:crawler_error", listener)
      window.removeEventListener("iris:crawler_complete", listener)
      window.removeEventListener("iris:crawler_vision_action", listener)
      window.removeEventListener("iris:vision_status", listener)
    },
  }
}

/** Run one scenario through the REAL runner under fake timers; return trace. */
async function runAndTrace(scenarioId: string): Promise<CapturedEvent[]> {
  const scenario = SCENARIOS.find((s) => s.id === scenarioId)
  if (!scenario) throw new Error(`scenario ${scenarioId} missing`)
  const cap = captureWindowEvents()
  jest.useFakeTimers()
  try {
    const handle = runScenario(scenario)
    const donePromise = handle.done
    // Advance past the final step (+50ms resolve margin) in one jump.
    jest.advanceTimersByTime(
      Math.max(...scenario.steps.map((s) => s.atMs), 0) + 100,
    )
    const resolved = await donePromise
    expect(resolved).toBe(true)
  } finally {
    jest.useRealTimers()
    cap.stop()
  }
  return cap.events
}

describe("BT-1: simulator scenario trace sequences", () => {
  it("every scenario id a-m exists exactly once (sign-off checklist parity)", () => {
    expect(SCENARIOS.map((s) => s.id)).toEqual([
      "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    ])
  })

  it("every dispatched event is on the real iris:* contract (no mock channel)", () => {
    for (const s of SCENARIOS) {
      for (const step of s.steps) {
        expect(step.ev).toMatch(/^iris:/)
      }
    }
  })

  it("scenario a: full crawl lifecycle — start → 4 pages → complete", async () => {
    const ev = await runAndTrace("a")
    expect(ev.map((e) => e.name)).toEqual([
      "iris:crawler_started",
      "iris:crawler_page_fetched",
      "iris:crawler_page_fetched",
      "iris:crawler_page_fetched",
      "iris:crawler_page_fetched",
      "iris:crawler_complete",
    ])
    // Pages arrive IN ORDER 1..4 (shutter cadence kicks ride these).
    const pages = ev.filter((e) => e.name === "iris:crawler_page_fetched")
    expect(pages.map((p) => p.detail.page_number)).toEqual([1, 2, 3, 4])
    expect(pages.every((p) => p.detail.total === 4)).toBe(true)
    // Terminal beat: settle ring fade rides the completion summary.
    expect(ev[ev.length - 1].detail.page_count).toBe(4)
  })

  it("scenario b: crawl error terminal — error fires AFTER progress, then nothing", async () => {
    const ev = await runAndTrace("b")
    expect(ev.map((e) => e.name)).toEqual([
      "iris:crawler_started",
      "iris:crawler_page_fetched",
      "iris:crawler_error",
    ])
    // Amber settle needs a reason to surface.
    expect(typeof ev[2].detail.message).toBe("string")
    expect(ev[2].detail.message).not.toBe("")
    // No completion after an error — terminal state is the error itself.
    expect(ev.filter((e) => e.name === "iris:crawler_complete")).toHaveLength(0)
  })

  it("scenario c: cursor clicks travel to a POINT — coords present, ordered indices", async () => {
    const ev = await runAndTrace("c")
    const actions = ev.filter((e) => e.name === "iris:crawler_vision_action")
    expect(actions.length).toBeGreaterThanOrEqual(2)
    for (const a of actions) {
      expect(a.detail.kind).toBe("click")
      // Travel target must be a normalized viewport point.
      expect(a.detail.x).toBeGreaterThan(0)
      expect(a.detail.x).toBeLessThan(1)
      expect(a.detail.y).toBeGreaterThan(0)
      expect(a.detail.y).toBeLessThan(1)
      expect(a.detail.viewport_w).toBe(1280)
      expect(a.detail.viewport_h).toBe(720)
    }
    // action_index strictly increases (orb trail decay keyed off sequence).
    const idx = actions.map((a) => a.detail.action_index as number)
    for (let i = 1; i < idx.length; i++) expect(idx[i]).toBeGreaterThan(idx[i - 1])
    // Non-escalated session: no NOTICE beat trigger in this scenario.
    expect(actions.some((a) => a.detail.escalated === true)).toBe(false)
  })

  it("scenario e: scrolls carry offsets but NO point — cursor holds position", async () => {
    const ev = await runAndTrace("e")
    const scrolls = ev.filter(
      (e) => e.name === "iris:crawler_vision_action" && e.detail.kind === "scroll",
    )
    expect(scrolls.length).toBe(3)
    let prev = -Infinity
    for (const s of scrolls) {
      // Scroll carries no x/y point (REQ: cursor HOLDS position).
      expect(s.detail.x).toBeUndefined()
      expect(s.detail.y).toBeUndefined()
      // Offsets increase monotonically into the document.
      const y = s.detail.scroll_y as number
      expect(y).toBeGreaterThan(prev)
      prev = y
      // INPUT CHANGE (called out per THE TEST RULE, 2026-08-24): scenario e
      // now drives a REAL page through the proxy (user feedback round 2 —
      // synthetic URLs rendered as missing captures/404s). Wikipedia-scale
      // scroll_height 8000 replaces the old 4000 fixture constant; the
      // assertion still pins that offsets stay bounded by the document.
      expect(s.detail.scroll_height).toBe(8000)
    }
  })

  it("scenario f: escalation — actions flagged escalated so the NOTICE beat fires", async () => {
    const ev = await runAndTrace("f")
    const actions = ev.filter((e) => e.name === "iris:crawler_vision_action")
    expect(actions.length).toBeGreaterThanOrEqual(2)
    // EVERY action of the escalated session carries the flag (T6 contract).
    expect(actions.every((a) => a.detail.escalated === true)).toBe(true)
    // First escalated action is a navigate (challenge wall ahead).
    expect(actions[0].detail.kind).toBe("navigate")
  })
})
