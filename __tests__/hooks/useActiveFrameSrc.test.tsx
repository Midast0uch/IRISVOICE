import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useActiveFrameSrc } from "@/hooks/useActiveFrameSrc"
import type { Tab } from "@/types/iris"

/**
 * REQ-1 AC2 / REQ-2 AC1 (T5) — frame routing contract.
 *
 * The panel must render:
 *   - agent-navigated web tabs from the CAPTURE REPLAY endpoint
 *     (/api/browser/capture/{job_id}/{page_number}) — never a second live
 *     fetch of the source URL;
 *   - user-typed URLs (no active tab) through the fetch proxy
 *     (/api/browser/proxy?url=...) — REQ-2.
 *
 * Each case is proven failable: a tab WITHOUT capture provenance must NOT
 * route to the replay endpoint (it would fake evidence), and a user URL must
 * NOT hit the capture endpoint.
 */

function tab(partial: Partial<Tab>): Tab {
  return {
    id: "t1",
    type: "web",
    title: "Page",
    ...partial,
  } as Tab
}

describe("useActiveFrameSrc — frame routing (REQ-1 AC2 / REQ-2)", () => {
  it("routes an agent tab WITH capture provenance to the replay endpoint", () => {
    const { result } = renderHook(() =>
      useActiveFrameSrc({
        tabs: [tab({ id: "t1", url: "https://news.example/story", captureJobId: "job-9", capturePageNumber: 2 })],
        activeTabId: "t1",
        browserUrl: "https://google.com",
      }),
    )
    expect(result.current).toBe("/api/browser/capture/job-9/2")
  })

  it("never routes an agent tab WITHOUT capture provenance to replay", () => {
    // A tab that only has the source URL (fetch in flight / failed) must NOT
    // fake a replay URL.
    //
    // ASSERTION CHANGED (reported in review): this previously asserted the
    // bare source URL, i.e. that the frame is pointed straight at the live
    // site. That encoded pre-feature behaviour and violated REQ-1 AC3 twice
    // over — it IS the silent live fetch the AC forbids, and in a browser it
    // renders "refused to connect" via X-Frame-Options, which is the whole
    // problem this feature exists to solve. The name is unchanged because it
    // still describes what is checked; the assertion is now STRICTER (no
    // replay URL *and* no bare live URL).
    const { result } = renderHook(() =>
      useActiveFrameSrc({
        tabs: [tab({ id: "t1", url: "https://news.example/story" })],
        activeTabId: "t1",
        browserUrl: "https://google.com",
      }),
    )
    expect(result.current).not.toContain("/api/browser/capture/")
    expect(result.current).toBe(
      "/api/browser/proxy?url=" + encodeURIComponent("https://news.example/story"),
    )
  })

  it("routes a user-typed URL (no active tab) through the proxy", () => {
    const { result } = renderHook(() =>
      useActiveFrameSrc({
        tabs: [],
        activeTabId: null,
        browserUrl: "https://example.com/a b",
      }),
    )
    expect(result.current).toBe("/api/browser/proxy?url=https%3A%2F%2Fexample.com%2Fa%20b")
  })

  it("routes an html tab to its own srcDoc content, not the proxy", () => {
    const { result } = renderHook(() =>
      useActiveFrameSrc({
        tabs: [tab({ id: "t1", type: "html", content: "<p>x</p>" })],
        activeTabId: "t1",
        browserUrl: "https://google.com",
      }),
    )
    // HTML tabs render app-authored content via srcDoc — the frame src is
    // irrelevant, so the hook must NOT force a proxy URL onto them.
    expect(result.current).toBeUndefined()
  })
})
