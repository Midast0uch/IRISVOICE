/**
 * UT-1 + BT-2 (specs/vision-browser-stage REQ-7 / REQ-9, T8).
 *
 * UT-1: mapPoint — letterbox-aware aspect correction for the vision cursor.
 * BT-2: mid-run mount backfill — a hook mounted with an ACTIVE CrawlProvider
 * seed shows the run immediately (loading with the right page counts) instead
 * of idling until the next event; real events keep ownership afterwards and
 * snapshot replays cannot double-seed.
 */

import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useBrowserNavOverlay, type NavOverlaySeed } from "@/hooks/useBrowserNavOverlay"
// mapPoint is exported from the overlay component module; import it directly.
import { mapPoint } from "@/components/iris/browser/BrowserNavigationOverlay"

// ── UT-1: aspect-correct cursor mapping (REQ-9 AC1/AC2) ─────────────────────

describe("mapPoint — letterbox-aware cursor mapping", () => {
  it("returns the point unchanged when aspects match", () => {
    expect(mapPoint(0.25, 0.75, 1280, 720, 640, 360)).toEqual({ x: 0.25, y: 0.75 })
  })

  it("falls back to naive mapping when viewport dims are absent (AC2)", () => {
    expect(mapPoint(0.3, 0.6)).toEqual({ x: 0.3, y: 0.6 })
    expect(mapPoint(0.3, 0.6, undefined, undefined, 500, 400)).toEqual({ x: 0.3, y: 0.6 })
  })

  it("wider source in taller box: y compresses into the vertical band", () => {
    // 16:9 source in a 1:1 box -> vertical letterbox band = 9/16 of height.
    const out = mapPoint(0.5, 0.0, 1600, 900, 500, 500)
    expect(out.x).toBeCloseTo(0.5)
    expect(out.y).toBeCloseTo(0.5 - 0.5 * (500 / 500 / (1600 / 900)))
  })

  it("taller source in wider box: x compresses into the horizontal band", () => {
    const out = mapPoint(0.0, 0.5, 900, 1600, 500, 500)
    expect(out.y).toBeCloseTo(0.5)
    expect(out.x).toBeCloseTo(0.5 - 0.5 * ((900 / 1600) / 1))
  })

  it("keeps corners inside the letterbox band (never escapes to edges)", () => {
    const out = mapPoint(0.5, 1.0, 1600, 900, 500, 700)
    expect(out.y).toBeLessThanOrEqual(1)
    expect(out.y).toBeGreaterThanOrEqual(0)
  })
})

// ── BT-2: mid-run mount backfill (REQ-7 AC1/AC2) ────────────────────────────

function fire(name: string, detail: Record<string, unknown> = {}) {
  act(() => {
    window.dispatchEvent(new CustomEvent(name, { detail }))
  })
}

describe("useBrowserNavOverlay — REQ-7 mid-run backfill", () => {
  it("seeds loading state from an ACTIVE provider seed on mount", () => {
    const seed: NavOverlaySeed = {
      active: true,
      pagesDone: 2,
      pagesTotal: 5,
      subGoal: "research query",
    }
    const { result } = renderHook(() => useBrowserNavOverlay(seed))
    expect(result.current.status.state).toBe("loading")
    expect(result.current.status.pagesDone).toBe(2)
    expect(result.current.status.pagesTotal).toBe(5)
    expect(result.current.status.subGoal).toBe("research query")
  })

  it("stays idle when the seed is inactive", () => {
    const { result } = renderHook(() =>
      useBrowserNavOverlay({ active: false, pagesDone: 3, pagesTotal: 5 }),
    )
    expect(result.current.status.state).toBe("idle")
  })

  it("real events own the surface after seeding; replays cannot double-seed", () => {
    const seed: NavOverlaySeed = { active: true, pagesDone: 1, pagesTotal: 3, subGoal: "q" }
    const { result } = renderHook(() => useBrowserNavOverlay(seed))
    expect(result.current.status.state).toBe("loading")

    // Live event advances the run. Seeded state was "loading", so the FIRST
    // fetch disperses (same choreography as a fresh run).
    fire("iris:crawler_page_fetched", { page_number: 2, total: 3 })
    expect(result.current.status.state).toBe("dispersing")
    expect(result.current.status.pagesDone).toBe(2)

    // A stale seed re-emission (snapshot replay) must NOT reset live progress.
    fire("iris:crawler_page_fetched", { page_number: 3, total: 3 })
    expect(result.current.status.state).toBe("crawling")
    expect(result.current.status.pagesDone).toBe(3)
  })

  it("carries escalated + viewport dims through vision actions (REQ-8/REQ-9)", () => {
    const { result } = renderHook(() => useBrowserNavOverlay())
    fire("iris:crawler_started", { query: "q", url_count: 2 })
    fire("iris:crawler_vision_action", {
      kind: "click",
      action_index: 1,
      total: 8,
      x: 0.4,
      y: 0.6,
      viewport_w: 1280,
      viewport_h: 720,
      escalated: true,
    })
    expect(result.current.status.visionEscalated).toBe(true)
    expect(result.current.status.visionViewportW).toBe(1280)
    expect(result.current.status.visionViewportH).toBe(720)
    expect(result.current.status.visionAction).toBe("click")
  })
})
