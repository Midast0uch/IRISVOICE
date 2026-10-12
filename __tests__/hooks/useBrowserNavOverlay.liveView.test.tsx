/**
 * Live browser view (2026-10-12): the agent drives a REAL page that is streamed
 * under the nav overlay. Three faults the owner saw:
 *
 *   - a loading orb stuck in the middle of the frame (a dashboard mounted
 *     mid-run was seeded "loading" and saw none of the events that had already
 *     happened; and the resting orb covers the live page for no reason),
 *   - the cursor not on the page (its fractions are of the page, but the live
 *     image is letterboxed inside the box, so they landed on the bars).
 */
import "@testing-library/jest-dom"
import { renderHook, render, act } from "@testing-library/react"
import { useBrowserNavOverlay } from "@/hooks/useBrowserNavOverlay"
import { BrowserNavigationOverlay } from "@/components/iris/browser/BrowserNavigationOverlay"

// The orb is a canvas engine; only its presence and position matter here.
jest.mock("@/components/iris/orb/OrbCanvas", () => ({
  OrbCanvas: () => <div data-testid="orb" />,
}))

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

describe("mid-run mount does not stay in loading", () => {
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  it("settles a seeded run that already read pages when no event arrives", () => {
    const { result } = renderHook(() =>
      useBrowserNavOverlay({ active: true, pagesDone: 2, pagesTotal: 5, subGoal: "q" }),
    )
    expect(result.current.status.state).toBe("loading")
    act(() => { jest.advanceTimersByTime(4500) })
    expect(result.current.status.state).toBe("crawling")
    expect(result.current.status.pagesDone).toBe(2)
  })

  it("a real event before the timer keeps ownership", () => {
    const { result } = renderHook(() =>
      useBrowserNavOverlay({ active: true, pagesDone: 2, pagesTotal: 5, subGoal: "q" }),
    )
    act(() => {
      window.dispatchEvent(new CustomEvent("iris:crawler_page_fetched", { detail: { page_number: 3, total: 5 } }))
    })
    expect(result.current.status.state).toBe("dispersing")
    act(() => { jest.advanceTimersByTime(4500) })
    expect(result.current.status.state).toBe("dispersing")
  })

  it("a run that has read nothing yet stays loading (its opening is real)", () => {
    const { result } = renderHook(() =>
      useBrowserNavOverlay({ active: true, pagesDone: 0, pagesTotal: 5, subGoal: "q" }),
    )
    act(() => { jest.advanceTimersByTime(10000) })
    expect(result.current.status.state).toBe("loading")
  })
})

describe("BrowserNavigationOverlay over the live page", () => {
  it("shows the resting orb while loading, but not over the live page", () => {
    const { queryByTestId, rerender } = render(<BrowserNavigationOverlay state="loading" />)
    expect(queryByTestId("orb")).not.toBeNull()
    rerender(<BrowserNavigationOverlay state="loading" live />)
    expect(queryByTestId("orb")).toBeNull()
    rerender(<BrowserNavigationOverlay state="dispersing" live />)
    expect(queryByTestId("orb")).toBeNull()
  })

  it("still shows the cursor on an action while live", () => {
    const { getByTestId } = render(
      <BrowserNavigationOverlay state="crawling" live visionStep={1} visionX={0.5} visionY={0.5} />,
    )
    expect(getByTestId("orb")).toBeInTheDocument()
  })

  it("aims the cursor at the live image rect, not the whole box", () => {
    // The page covers x 10..210, y 100..400 of the overlay (letterbox bars
    // around it). A click at the page's centre belongs at (110, 250).
    const { getByTestId } = render(
      <BrowserNavigationOverlay
        state="crawling"
        live
        liveRect={{ x: 10, y: 100, w: 200, h: 300 }}
        visionStep={1}
        visionX={0.5}
        visionY={0.5}
        visionViewportW={1366}
        visionViewportH={768}
      />,
    )
    const wrap = getByTestId("orb").parentElement as HTMLElement
    expect(wrap.style.left).toBe("110px")
    expect(wrap.style.top).toBe("250px")
  })
})
