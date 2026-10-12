/**
 * TakeoverLiveSurface in watch mode (2026-10-12): the owner saw the agent's
 * 1366x768 page as a small strip with big bars in a tall narrow panel. The
 * surface now reports its box (CSS px) so the backend can give the agent's
 * browser the panel's aspect, and reports where the image really sits so the
 * overlay's cursor lands on the page.
 */
import "@testing-library/jest-dom"
import { render, act } from "@testing-library/react"
import { TakeoverLiveSurface, containedRect, type ImageRect } from "@/components/iris/browser/TakeoverLiveSurface"
import { recordFrame, clearRun } from "@/lib/liveBrowser"

// jsdom has no layout: the surface's box is whatever the test says it is.
let box = { w: 344, h: 688 }
let roCallbacks: Array<() => void> = []

beforeAll(() => {
  class FakeRO {
    constructor(cb: () => void) { roCallbacks.push(cb) }
    observe() {}
    disconnect() {}
  }
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = FakeRO
  const isSurface = (el: HTMLElement) => el.getAttribute("role") === "application"
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get() { return isSurface(this) ? box.w : 0 } })
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get() { return isSurface(this) ? box.h : 0 } })
  // 40px of chrome (tab + address bar) above the surface inside the card.
  Object.defineProperty(HTMLElement.prototype, "offsetTop", { configurable: true, get() { return isSurface(this) ? 40 : 0 } })
  Object.defineProperty(HTMLElement.prototype, "offsetLeft", { configurable: true, get() { return 0 } })
  Object.defineProperty(HTMLElement.prototype, "offsetParent", { configurable: true, get() { return this.parentElement } })
})

beforeEach(() => {
  box = { w: 344, h: 688 }
  roCallbacks = []
  jest.useFakeTimers()
})

afterEach(() => {
  jest.useRealTimers()
  clearRun("run-1")
})

function viewportEvents() {
  const seen: Array<Record<string, unknown>> = []
  const on = (e: Event) => seen.push((e as CustomEvent).detail)
  window.addEventListener("iris:browser_viewport", on)
  return { seen, stop: () => window.removeEventListener("iris:browser_viewport", on) }
}

const resize = (w: number, h: number) => {
  box = { w, h }
  act(() => { roCallbacks.forEach((cb) => cb()) })
}

describe("containedRect", () => {
  it("centres an object-fit: contain image and leaves bars on the short axis", () => {
    const r = containedRect(344, 688, 1366, 768)
    expect(r.w).toBeCloseTo(344)
    expect(r.h).toBeCloseTo(344 * (768 / 1366))
    expect(r.x).toBeCloseTo(0)
    expect(r.y).toBeCloseTo((688 - r.h) / 2)
  })

  it("fills the box when the source size is unknown", () => {
    expect(containedRect(300, 200)).toEqual({ x: 0, y: 0, w: 300, h: 200 })
  })
})

describe("watch-mode viewport report", () => {
  it("sends the box size once on mount", () => {
    const { seen, stop } = viewportEvents()
    render(<TakeoverLiveSurface watch runId="run-1" width="100%" height="100%" />)
    stop()
    expect(seen).toEqual([{ run_id: "run-1", width: 344, height: 688 }])
  })

  it("ignores a change under 8px and debounces a real one into a single event", () => {
    const { seen, stop } = viewportEvents()
    render(<TakeoverLiveSurface watch runId="run-1" width="100%" height="100%" />)
    seen.length = 0

    resize(348, 691) // < 8px on both axes
    act(() => { jest.advanceTimersByTime(600) })
    expect(seen).toHaveLength(0)

    resize(380, 700)
    resize(400, 720) // a drag: only the last size is sent, after the debounce
    act(() => { jest.advanceTimersByTime(300) })
    expect(seen).toHaveLength(0)
    act(() => { jest.advanceTimersByTime(300) })
    stop()
    expect(seen).toEqual([{ run_id: "run-1", width: 400, height: 720 }])
  })

  it("does not report outside watch mode", () => {
    const { seen, stop } = viewportEvents()
    render(<TakeoverLiveSurface runId="run-1" questionId="q" width="100%" height="100%" />)
    stop()
    expect(seen).toHaveLength(0)
  })
})

describe("watch-mode image rect", () => {
  it("reports the letterboxed image area in card coordinates", () => {
    recordFrame({ run_id: "run-1", viewport_w: 1366, viewport_h: 768, format: "jpeg", bytes: "AAAA" })
    const rects: Array<ImageRect | null> = []
    render(
      <div data-browser-card>
        <TakeoverLiveSurface watch runId="run-1" width="100%" height="100%" onImageRect={(r) => rects.push(r)} />
      </div>,
    )
    const last = rects[rects.length - 1] as ImageRect
    const h = 344 * (768 / 1366)
    expect(last.x).toBeCloseTo(0)
    expect(last.w).toBeCloseTo(344)
    expect(last.h).toBeCloseTo(h)
    // 40px chrome above the surface + the top letterbox bar.
    expect(last.y).toBeCloseTo(40 + (688 - h) / 2)
  })
})
