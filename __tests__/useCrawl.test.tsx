/**
 * T12/T16: useCrawl hook — crawl state from unified CustomEvents.
 *
 * Verifies the hook is transport-agnostic: it consumes the SAME CustomEvent
 * names whether delivered by WS (useIRISWebSocket) or SSE (useCrawlSSE). We
 * dispatch the events directly to confirm state transitions and that the
 * terminal crawler_complete resets active state (REQ-29/30).
 */
import { renderHook, act } from "@testing-library/react"
import { useCrawl } from "@/hooks/useCrawl"

// jsdom lacks matchMedia; useReducedMotion (pulled in by useCrawl) needs it.
beforeAll(() => {
  if (!window.matchMedia) {
    window.matchMedia = (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList
  }
})

function fire(name: string, detail: unknown) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

describe("useCrawl", () => {
  it("transitions started -> page -> complete and resets active", () => {
    const { result } = renderHook(() => useCrawl(true))

    act(() => fire("iris:crawler_started", { query: "best laptops", url_count: 2, session_id: "sess-1" }))
    expect(result.current.state.active).toBe(true)
    expect(result.current.state.query).toBe("best laptops")
    expect(result.current.state.total).toBe(2)
    expect(result.current.state.sessionId).toBe("sess-1")

    act(() => fire("iris:crawler_page_fetched", { url: "https://a.com/x", page_number: 1, total: 2, host: "a.com" }))
    expect(result.current.state.pages).toHaveLength(1)
    expect(result.current.state.pages[0].host).toBe("a.com")

    act(() => fire("iris:open_tab", { tab_type: "dashboard", id: "t1", title: "Laptops", data: { summary: "s" } }))
    expect(result.current.state.dashboard).toEqual({ summary: "s" })

    act(() => fire("iris:crawler_complete", { query: "best laptops", summary: "done", cited_markdown: "[1](https://a.com/x)", credibility_top_score: 0.9 }))
    expect(result.current.state.active).toBe(false)
    expect(result.current.state.complete).toBe(true)
    expect(result.current.state.summary).toBe("done")
    expect(result.current.state.credibilityTopScore).toBe(0.9)
  })

  it("error sets error and deactivates", () => {
    const { result } = renderHook(() => useCrawl(true))
    act(() => fire("iris:crawler_started", { query: "q", url_count: 1 }))
    act(() => fire("iris:crawler_error", { message: "web disabled" }))
    expect(result.current.state.active).toBe(false)
    expect(result.current.state.error).toBe("web disabled")
  })

  it("sync_required flag is set on sync_required event", () => {
    const { result } = renderHook(() => useCrawl(true))
    act(() => fire("iris:crawler_sync_required", {}))
    expect(result.current.state.syncRequired).toBe(true)
  })

  it("reset returns to idle", () => {
    const { result } = renderHook(() => useCrawl(true))
    act(() => fire("iris:crawler_started", { query: "q", url_count: 1 }))
    act(() => result.current.reset())
    expect(result.current.state.active).toBe(false)
    expect(result.current.state.query).toBe("")
  })
})
