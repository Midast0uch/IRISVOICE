/**
 * useCrawl — the live browser (browser_open / browser_act) shares the crawler
 * events with web search; its events carry `source: "browser"`.
 *
 * A browser session opening after a finished search must not wipe the search's
 * sources, count its frames as sources, or overwrite the search summary with
 * "browser session closed". Its pages still land in `pages` - the panel derives
 * the live-reading tab's capture provenance from there.
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

afterEach(() => {
  try {
    sessionStorage.removeItem("iris:crawl:session_id")
  } catch {}
})

function fire(name: string, detail: unknown) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

describe("useCrawl browser-source events", () => {
  it("a browser session after a search leaves sources, summary and session alone", () => {
    const { result } = renderHook(() => useCrawl(true))

    act(() => fire("iris:crawler_started", {
      query: "best laptops", url_count: 2, urls: ["https://a.com/x", "https://b.com/y"], session_id: "sess-1",
    }))
    act(() => fire("iris:crawler_page_fetched", {
      url: "https://a.com/x", page_number: 1, total: 2, host: "a.com", job_id: "job-search",
    }))
    act(() => fire("iris:crawler_complete", {
      query: "best laptops", summary: "search summary", cited_markdown: "[1](https://a.com/x)", credibility_top_score: 0.9,
    }))
    const before = result.current.state
    expect(before.sources.map((s) => s.url)).toEqual(["https://a.com/x", "https://b.com/y"])

    act(() => fire("iris:crawler_started", {
      query: "https://c.com/z", url_count: 1, source: "browser", job_id: "run-1",
    }))
    expect(result.current.state.active).toBe(true)
    expect(result.current.state.sources).toEqual(before.sources)
    expect(result.current.state.query).toBe("best laptops")
    expect(result.current.state.summary).toBe("search summary")
    expect(result.current.state.sessionId).toBe("sess-1")

    act(() => fire("iris:crawler_page_fetched", {
      url: "https://c.com/z", page_number: 7, total: 7, host: "c.com", job_id: "run-1", capture_page: 7, source: "browser",
    }))
    const s = result.current.state
    expect(s.sources).toEqual(before.sources)
    expect(s.total).toBe(before.total)
    // The frame IS in pages: that is where the live tab's provenance comes from.
    expect(s.pages.map((p) => p.url)).toContain("https://c.com/z")
    expect(s.pages.find((p) => p.url === "https://c.com/z")?.jobId).toBe("run-1")

    act(() => fire("iris:crawler_complete", {
      query: "https://c.com/z", summary: "browser session closed", source: "browser",
    }))
    expect(result.current.state.summary).toBe("search summary")
    expect(result.current.state.citedMarkdown).toBe("[1](https://a.com/x)")
    expect(result.current.state.credibilityTopScore).toBe(0.9)
    // The browser close does not settle the run: turn_end does.
    expect(result.current.state.active).toBe(true)

    act(() => fire("iris:turn_end", {}))
    expect(result.current.state.active).toBe(false)
  })
})
