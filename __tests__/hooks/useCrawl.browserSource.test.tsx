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

  it("a browser run in a LATER turn starts with a clean crawl state", () => {
    // Live 2026-10-12: in a new thread, a browser run kept the previous turn's
    // header ("Searching quotes.toscrape.com"), its counter ("[5/5]", then "8/5")
    // and its sources. The turn end marks the search as history.
    const { result } = renderHook(() => useCrawl(true))
    const urls = [1, 2, 3, 4, 5].map((n) => `https://quotes.toscrape.com/page/${n}/`)

    act(() => fire("iris:crawler_started", {
      query: "quotes.toscrape.com", url_count: 5, urls, session_id: "sess-2", job_id: "job-web",
    }))
    urls.forEach((url, i) => act(() => fire("iris:crawler_page_fetched", {
      url, page_number: i + 1, total: 5, host: "quotes.toscrape.com", job_id: "job-web",
    })))
    act(() => fire("iris:crawler_progress", { stage: "fetching", message: "[5/5] quotes.toscrape.com quote" }))
    act(() => fire("iris:crawler_vision_action", { type: "crawler_vision_action", action: "click", run_id: "job-web", seq: 1 }))
    expect(result.current.state.sources).toHaveLength(5)
    expect(result.current.state.visionActions).toHaveLength(1)

    act(() => fire("iris:turn_end", {}))
    act(() => fire("iris:crawler_started", {
      query: "https://example.com/", url_count: 1, source: "browser", job_id: "run-2",
    }))
    const s = result.current.state
    expect(s.active).toBe(true)
    expect(s.query).toBe("")
    expect(s.total).toBe(0)
    expect(s.progress).toBeNull()
    expect(s.pages).toEqual([])
    expect(s.sources).toEqual([])
    expect(s.visionActions).toEqual([])
  })

  it("a browser run in the SAME turn as a web crawl keeps the search state", () => {
    // Same sequence as above, without the turn end: the search is still the
    // current turn's work, so the browser start must not wipe it.
    const { result } = renderHook(() => useCrawl(true))
    const urls = [1, 2, 3, 4, 5].map((n) => `https://quotes.toscrape.com/page/${n}/`)

    act(() => fire("iris:crawler_started", {
      query: "quotes.toscrape.com", url_count: 5, urls, session_id: "sess-2", job_id: "job-web",
    }))
    urls.forEach((url, i) => act(() => fire("iris:crawler_page_fetched", {
      url, page_number: i + 1, total: 5, host: "quotes.toscrape.com", job_id: "job-web",
    })))
    act(() => fire("iris:crawler_progress", { stage: "fetching", message: "[5/5] quotes.toscrape.com quote" }))
    act(() => fire("iris:crawler_vision_action", { type: "crawler_vision_action", action: "click", run_id: "job-web", seq: 1 }))

    act(() => fire("iris:crawler_started", {
      query: "https://example.com/", url_count: 1, source: "browser", job_id: "run-2",
    }))
    const s = result.current.state
    expect(s.active).toBe(true)
    expect(s.query).toBe("quotes.toscrape.com")
    expect(s.sources).toHaveLength(5)
    expect(s.visionActions).toHaveLength(1)
  })
})
