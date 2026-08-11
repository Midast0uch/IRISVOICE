/**
 * Wave 4 (T17/T18): useCrawl new listeners + restore.
 *
 * T17 — the hook owns four NEW crawl detail events (REQ-11 AC4, REQ-12 AC2):
 *   iris:crawler_progress        (in-flight stage message)
 *   iris:crawler_phase           (structured phase; WS dispatch name)
 *   iris:task:event              (SAME phase, SSE transport name — ux_map maps
 *                                 CRAWLER_PHASE -> msg_type "task:event")
 *   iris:crawler_vision_action   (vision acted on a page — panel annotation)
 *   iris:crawler_source_parked   (a walled source was parked, non-blocking)
 *
 * T18 — restore(sessionId, afterSeq) replays the server-side event log on
 * remount: only events with seq > afterSeq, or EVERY event when the log
 * evicted some (snapshot.sync_required / client syncRequired flag).
 *
 * Same conventions as __tests__/useCrawl.test.tsx: dispatch CustomEvents
 * directly (transport-agnostic contract) and assert state transitions.
 */
import { renderHook, act } from "@testing-library/react"
import { render } from "@testing-library/react"
import { useCrawl } from "@/hooks/useCrawl"
import { CrawlProvider, useCrawlContext, type CrawlContextValue } from "@/hooks/CrawlProvider"

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

// This jsdom env does not expose global fetch; install a controllable stub.
const _originalFetch = (globalThis as unknown as { fetch?: unknown }).fetch

function mockFetch(impl: () => Promise<unknown>) {
  const stub = jest.fn(impl)
  ;(globalThis as unknown as { fetch: unknown }).fetch = stub
  return stub
}

afterEach(() => {
  jest.restoreAllMocks()
  ;(globalThis as unknown as { fetch?: unknown }).fetch = _originalFetch
  try {
    sessionStorage.removeItem("iris:crawl:session_id")
  } catch {}
})

function fire(name: string, detail: unknown) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

describe("useCrawl wave4 listeners (T17)", () => {
  it("tracks the in-flight stage message from crawler_progress", () => {
    const { result } = renderHook(() => useCrawl(true))
    expect(result.current.state.progress).toBeNull()

    act(() => fire("iris:crawler_progress", { stage: "narrowing", message: "Narrowing search…" }))
    expect(result.current.state.progress).toBe("Narrowing search…")
    expect(result.current.state.active).toBe(true)
  })

  it("tracks phase + phaseSequence from crawler_phase (WS dispatch name)", () => {
    const { result } = renderHook(() => useCrawl(true))
    act(() => fire("iris:crawler_phase", { phase: "searching", phase_sequence: 1 }))
    expect(result.current.state.phase).toBe("searching")
    expect(result.current.state.phaseSequence).toBe(1)
  })

  it("accepts the phase via iris:task:event (the SSE contract name)", () => {
    // backend/crawler/ux_map.py: CRAWLER_PHASE -> msg_type "task:event", and
    // useCrawlSSE re-dispatches `iris:${type}`. The hook MUST accept this name
    // or the SSE fallback path never surfaces a phase (REQ-31 AC4).
    const { result } = renderHook(() => useCrawl(true))
    act(() => fire("iris:task:event", { phase: "extracting", phase_sequence: 3 }))
    expect(result.current.state.phase).toBe("extracting")
    expect(result.current.state.phaseSequence).toBe(3)
  })

  it("accumulates vision actions (REQ-11 AC4)", () => {
    const { result } = renderHook(() => useCrawl(true))
    expect(result.current.state.visionActions).toHaveLength(0)

    act(() => fire("iris:crawler_vision_action", {
      job_id: "j1", url: "https://a.com", kind: "scroll",
      reason: "new content", action_index: 1, total: 4,
    }))
    act(() => fire("iris:crawler_vision_action", {
      job_id: "j1", url: "https://a.com", kind: "click",
      reason: "expand", action_index: 2, total: 4,
    }))
    expect(result.current.state.visionActions).toHaveLength(2)
    expect(result.current.state.visionActions[1].action_index).toBe(2)
  })

  it("accumulates parked sources (REQ-13 AC4)", () => {
    const { result } = renderHook(() => useCrawl(true))
    expect(result.current.state.parkedSources).toHaveLength(0)

    act(() => fire("iris:crawler_source_parked", {
      url: "https://walled.com", domain: "walled.com",
      wall_kind: "challenge", run_id: "r1", question_id: "q1",
    }))
    expect(result.current.state.parkedSources).toHaveLength(1)
    expect(result.current.state.parkedSources[0].url).toBe("https://walled.com")
    expect(result.current.state.parkedSources[0].wall_kind).toBe("challenge")
  })

  it("keeps crawl detail across a page event (no clobbering)", () => {
    const { result } = renderHook(() => useCrawl(true))
    act(() => fire("iris:crawler_started", { query: "q", url_count: 1, session_id: "s1" }))
    act(() => fire("iris:crawler_phase", { phase: "searching", phase_sequence: 1 }))
    act(() => fire("iris:crawler_progress", { stage: "narrowing", message: "Narrowing…" }))
    act(() => fire("iris:crawler_page_fetched", { url: "https://a.com/x", page_number: 1, total: 1 }))
    // started resets to IDLE — but a subsequent page event must not wipe the
    // phase/progress detail accumulated after it.
    expect(result.current.state.phase).toBe("searching")
    expect(result.current.state.progress).toBe("Narrowing…")
    expect(result.current.state.pages).toHaveLength(1)
  })
})

describe("useCrawl restore(sessionId, afterSeq) (T18)", () => {
  function mockSnapshot(body: unknown) {
    return mockFetch(async () => ({
      ok: true,
      json: async () => body,
    }))
  }

  it("applies only events with seq > afterSeq when no eviction occurred", async () => {
    mockSnapshot({
      ok: true,
      session_id: "sess-1",
      last_seq: 5,
      sync_required: false,
      events: [
        { seq: 1, type: "crawler_started", payload: { query: "old", url_count: 2, session_id: "sess-1" } },
        { seq: 2, type: "crawler_progress", payload: { stage: "narrowing", message: "Narrowing search…" } },
        { seq: 4, type: "task:event", payload: { phase: "searching", phase_sequence: 1 } },
      ],
    })

    const { result } = renderHook(() => useCrawl(true))
    act(() => {
      result.current.restore("sess-1", 2)
    })
    await act(async () => {})

    // seq 4 (> afterSeq 2) applied; seq 1 + 2 skipped.
    expect(result.current.state.phase).toBe("searching")
    expect(result.current.state.phaseSequence).toBe(1)
    expect(result.current.state.query).toBe("")
    expect(result.current.state.progress).toBeNull()
  })

  it("does a FULL re-sync (every event) when the log evicted events", async () => {
    mockSnapshot({
      ok: true,
      session_id: "sess-1",
      last_seq: 5,
      sync_required: true, // TTL eviction — partial replay would lie
      events: [
        { seq: 1, type: "crawler_started", payload: { query: "q", url_count: 2, session_id: "sess-1" } },
        { seq: 2, type: "crawler_progress", payload: { stage: "narrowing", message: "Narrowing search…" } },
        { seq: 3, type: "task:event", payload: { phase: "citing", phase_sequence: 5 } },
      ],
    })

    const { result } = renderHook(() => useCrawl(true))
    act(() => {
      // afterSeq beyond every buffered seq — only a full sync applies them.
      result.current.restore("sess-1", 99)
    })
    await act(async () => {})

    expect(result.current.state.query).toBe("q")
    expect(result.current.state.progress).toBe("Narrowing search…")
    expect(result.current.state.phase).toBe("citing")
    // Mirror the authoritative server flag into client state (AC6).
    expect(result.current.state.syncRequired).toBe(true)
  })

  it("tolerates a failed fetch (best-effort, no throw)", async () => {
    mockFetch(async () => {
      throw new Error("network down")
    })
    const { result } = renderHook(() => useCrawl(true))
    act(() => {
      result.current.restore("sess-1", 0)
    })
    await act(async () => {})
    expect(result.current.state.active).toBe(false)
  })
})

describe("CrawlProvider (T17/T18 wiring)", () => {
  it("exposes crawl state through context", () => {
    let value: CrawlContextValue | null = null
    function Probe() {
      value = useCrawlContext()
      return null
    }
    render(
      <CrawlProvider>
        <Probe />
      </CrawlProvider>,
    )
    expect(value).not.toBeNull()
    expect(value!.state.active).toBe(false)
    expect(typeof value!.reset).toBe("function")
  })

  it("restores the last run from the event log on mount (REQ-12 AC3)", async () => {
    try {
      sessionStorage.setItem("iris:crawl:session_id", "sess-9")
    } catch {}
    mockFetch(async () => ({
      ok: true,
      json: async () => ({
        ok: true,
        session_id: "sess-9",
        last_seq: 2,
        sync_required: false,
        events: [
          { seq: 1, type: "crawler_started", payload: { query: "restored", url_count: 1, session_id: "sess-9" } },
        ],
      }),
    }))

    let value: CrawlContextValue | null = null
    function Probe() {
      value = useCrawlContext()
      return null
    }
    render(
      <CrawlProvider>
        <Probe />
      </CrawlProvider>,
    )
    await act(async () => {})

    expect(value!.state.active).toBe(true)
    expect(value!.state.query).toBe("restored")
    expect(value!.state.sessionId).toBe("sess-9")
  })

  it("throws when consumed outside the provider", () => {
    // Silence the expected console.error from the uncaught render error.
    const spy = jest.spyOn(console, "error").mockImplementation(() => {})
    function Broken() {
      useCrawlContext()
      return null
    }
    expect(() => render(<Broken />)).toThrow(/CrawlProvider/)
    spy.mockRestore()
  })
})
