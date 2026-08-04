import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useBrowserNavOverlay } from "@/hooks/useBrowserNavOverlay"

/**
 * T47 (REQ-16 AC6/AC7/AC9) — browser-navigation overlay behavioral test.
 *
 * Drives the overlay state machine through the REAL iris:open_tab /
 * iris:crawler_* CustomEvents (the same ones useIRISWebSocket dispatches)
 * and asserts the choreographed transitions:
 *
 *   loading → dispersing (first page found — orb reaches out) →
 *   crawling (subsequent pages — shutter border) → complete
 *
 * plus:
 *   - the REQ-18 trace bridge (iris:nav_overlay_state, surface="in-app")
 *     fires on every transition, so behavioral tests assert on structured
 *     state, not pixels (AC9)
 *   - error degrades the overlay to "error" and auto-dismisses to idle
 *   - cross-origin pages cannot break the overlay (the events carry only
 *     opaque data — no DOM access — so the overlay degrades to coarse
 *     state, never throws)
 */

function fire(name: string, detail: Record<string, unknown> = {}) {
  act(() => {
    window.dispatchEvent(new CustomEvent(name, { detail }))
  })
}

describe("useBrowserNavOverlay — REQ-16 visible navigation (T47)", () => {
  it("choreographs loading → dispersing → crawling → complete on a multi-page crawl", () => {
    const trace: Array<Record<string, unknown>> = []
    const onTrace = (e: Event) => {
      trace.push((e as CustomEvent).detail as Record<string, unknown>)
    }
    window.addEventListener("iris:nav_overlay_state", onTrace)
    const { result } = renderHook(() => useBrowserNavOverlay())

    // open_url → loading orb
    fire("iris:open_tab", { type: "open_tab", tab_type: "browser", url: "https://example.com/x" })
    expect(result.current.status.state).toBe("loading")

    // crawler starts → still loading, sub-goal + page count attached
    fire("iris:crawler_started", { query: "looking for the pricing table", url_count: 3 })
    expect(result.current.status.state).toBe("loading")
    expect(result.current.status.subGoal).toBe("looking for the pricing table")
    expect(result.current.status.pagesTotal).toBe(3)

    // first page found → DISPERSION (orb reaches out to touch the page)
    fire("iris:crawler_page_fetched", { page_number: 1, total: 3 })
    expect(result.current.status.state).toBe("dispersing")
    expect(result.current.status.pagesDone).toBe(1)

    // subsequent pages → SHUTTER-crawling state
    fire("iris:crawler_page_fetched", { page_number: 2, total: 3 })
    expect(result.current.status.state).toBe("crawling")
    expect(result.current.status.pagesDone).toBe(2)

    // crawl complete → complete
    fire("iris:crawler_complete", { summary: "Found the pricing table", page_count: 3 })
    expect(result.current.status.state).toBe("complete")
    expect(result.current.status.pagesDone).toBe(3)

    // REQ-18 trace bridge: every transition recorded with surface="in-app"
    const states = trace.map(t => t.state)
    expect(states).toContain("loading")
    expect(states).toContain("dispersing")
    expect(states).toContain("crawling")
    expect(states).toContain("complete")
    expect(trace.every(t => t.surface === "in-app")).toBe(true)

    window.removeEventListener("iris:nav_overlay_state", onTrace)
  })

  it("error degrades the overlay to error state, then auto-dismisses to idle", () => {
    jest.useFakeTimers()
    const { result } = renderHook(() => useBrowserNavOverlay())

    fire("iris:crawler_started", { query: "search", url_count: 2 })
    fire("iris:crawler_page_fetched", { page_number: 1, total: 2 })
    expect(result.current.status.state).toBe("dispersing")

    fire("iris:crawler_error", {})
    expect(result.current.status.state).toBe("error")

    // Auto-dismiss after the hold window.
    act(() => {
      jest.advanceTimersByTime(3400)
    })
    expect(result.current.status.state).toBe("idle")
    jest.useRealTimers()
  })

  it("cross-origin page cannot break the overlay — coarse degradation, never throws", () => {
    const { result } = renderHook(() => useBrowserNavOverlay())

    // Cross-origin navigation: open_tab + crawler events carry ONLY opaque
    // data (no DOM access into the iframe). The overlay must not throw and
    // must degrade to coarse state.
    expect(() => {
      fire("iris:open_tab", { type: "open_tab", tab_type: "browser", url: "https://cross-origin.example" })
      fire("iris:crawler_page_fetched", { page_number: 1, total: 1 })
      fire("iris:crawler_complete", { page_count: 1 })
    }).not.toThrow()

    expect(result.current.status.state).toBe("complete")
  })
})
