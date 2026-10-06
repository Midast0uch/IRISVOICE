/**
 * The spine's gutter replaces the composer's conversation chips.
 * DONE line: hover shows the list; click calls handleChipClick; drag scrubs.
 * Structure guards: the chips are gone from the composer, the matrix has no second Xur,
 * the timeline mounts the spine.
 */
import React from "react"
import fs from "fs"
import path from "path"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import "@testing-library/jest-dom"
import { SpineGutter } from "@/components/chat/spine/SpineGutter"
import { Spine } from "@/components/chat/spine/Spine"
import type { SpineChip } from "@/components/chat/spine/spineModel"

// jsdom has no canvas and no PointerEvent (it would drop clientY).
beforeAll(() => {
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null)
  if (typeof (window as unknown as { PointerEvent?: unknown }).PointerEvent === "undefined") {
    class PointerEventPolyfill extends MouseEvent {
      pointerId: number
      constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
        super(type, init)
        this.pointerId = init.pointerId ?? 0
      }
    }
    ;(window as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill
  }
})

const chips: SpineChip[] = [
  { messageId: "m1", label: "You: fix the cap", y: 50 },
  { messageId: "m2", label: "IRIS: window - max", y: 150 },
  { messageId: "m3", label: "You: continue #T-38", y: 250, knot: "ref" },
  { messageId: "m4", label: "You: ship it", y: 600 },
]

function scroller(top: number, height: number) {
  const el = document.createElement("div")
  Object.defineProperty(el, "scrollTop", { value: top, configurable: true })
  Object.defineProperty(el, "clientHeight", { value: height, configurable: true })
  return { current: el } as React.RefObject<HTMLElement | null>
}

function setup(over: Partial<React.ComponentProps<typeof SpineGutter>> = {}) {
  const onChipClick = jest.fn()
  const onScrub = jest.fn()
  const utils = render(
    <SpineGutter chips={chips} glowColor="#00d4ff" containerRef={scroller(100, 300)} onChipClick={onChipClick} onScrub={onScrub} {...over} />,
  )
  return { onChipClick, onScrub, ...utils }
}

describe("spine gutter: hover list", () => {
  it("shows nothing until the pointer is on the left edge", () => {
    setup()
    expect(screen.queryByTestId("spine-chips")).toBeNull()
  })

  it("hover shows the list of turns; leaving hides it", async () => {
    const { container } = setup()
    fireEvent.mouseEnter(screen.getByTestId("spine-gutter"))
    const panel = await screen.findByTestId("spine-chips")
    for (const c of chips) expect(panel).toHaveTextContent(c.label)
    fireEvent.mouseLeave(container.querySelector("[data-spine-gutter-wrap]") as Element)
    await waitFor(() => expect(screen.queryByTestId("spine-chips")).toBeNull())
  })

  it("highlights the turns in view and tags a knot as from outside", async () => {
    setup()
    fireEvent.mouseEnter(screen.getByTestId("spine-gutter"))
    const panel = await screen.findByTestId("spine-chips")
    const here = Array.from(panel.querySelectorAll("button")).map((b) => b.getAttribute("data-here"))
    // scrollTop 100, height 300: y 150 and 250 are in view
    expect(here).toEqual(["false", "true", "true", "false"])
    expect(panel).toHaveTextContent("from outside")
    expect(panel.querySelectorAll("small")).toHaveLength(1)
  })

  it("an empty strand says so", async () => {
    setup({ chips: [] })
    fireEvent.mouseEnter(screen.getByTestId("spine-gutter"))
    expect(await screen.findByTestId("spine-chips")).toHaveTextContent("No turns yet.")
  })
})

describe("spine gutter: click jumps", () => {
  it("clicking a turn calls handleChipClick with its message id and closes the list", async () => {
    const { onChipClick } = setup()
    fireEvent.mouseEnter(screen.getByTestId("spine-gutter"))
    await screen.findByTestId("spine-chips")
    fireEvent.click(screen.getByText("IRIS: window - max"))
    expect(onChipClick).toHaveBeenCalledTimes(1)
    expect(onChipClick).toHaveBeenCalledWith("m2")
    expect(screen.queryByTestId("spine-chips")).toBeNull()
  })
})

describe("spine gutter: drag scrubs", () => {
  it("a press and a drag on the gutter report the fraction of its height", () => {
    const { onScrub } = setup()
    const g = screen.getByTestId("spine-gutter")
    g.getBoundingClientRect = () => ({ top: 100, height: 400, left: 0, width: 30, right: 30, bottom: 500, x: 0, y: 100, toJSON() {} }) as DOMRect
    fireEvent.pointerDown(g, { clientY: 300, pointerId: 1 })
    expect(onScrub).toHaveBeenLastCalledWith(0.5)
    fireEvent.pointerMove(g, { clientY: 500, pointerId: 1 })
    expect(onScrub).toHaveBeenLastCalledWith(1)
    fireEvent.pointerUp(g, { pointerId: 1 })
    fireEvent.pointerMove(g, { clientY: 200, pointerId: 1 })
    expect(onScrub).toHaveBeenCalledTimes(2) // moving after release does not scrub
  })
})

describe("Spine mounts its canvas and the gutter, and the chips live there", () => {
  it("renders the gutter with the conversation chips it was given", async () => {
    const containerRef = { current: document.createElement("div") } as React.RefObject<HTMLDivElement | null>
    const onChipClick = jest.fn()
    render(
      <Spine
        containerRef={containerRef}
        glowColor="#00d4ff"
        isDeveloper={false}
        prefersReducedMotion
        running={false}
        streamingId={null}
        conversationChips={[{ messageId: "a", label: "You: hello", index: 0 }]}
        onChipClick={onChipClick}
        knotTurns={[]}
      />,
    )
    fireEvent.mouseEnter(screen.getByTestId("spine-gutter"))
    fireEvent.click(await screen.findByText("You: hello"))
    expect(onChipClick).toHaveBeenCalledWith("a")
  })
})

describe("Spine canvas: draws, rides to the running step, rests under reduced motion", () => {
  function fakeCtx() {
    const calls: Record<string, number> = {}
    const ctx = new Proxy({} as Record<string, unknown>, {
      get: (t, k: string) => {
        if (k === "createLinearGradient") return () => ({ addColorStop() {} })
        if (k in t) return t[k]
        return (..._a: unknown[]) => {
          calls[k] = (calls[k] || 0) + 1
        }
      },
      set: (t, k: string, v) => {
        t[k] = v
        return true
      },
    })
    return { ctx: ctx as unknown as CanvasRenderingContext2D, calls }
  }

  function mountTimeline(opts: { reduced: boolean; dev: boolean }) {
    const { ctx, calls } = fakeCtx()
    ;(HTMLCanvasElement.prototype.getContext as jest.Mock).mockImplementation(() => ctx)
    jest.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({ top: 0, left: 0, width: 400, height: 500, right: 400, bottom: 500, x: 0, y: 0, toJSON() {} } as DOMRect)
    const raf = jest.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1)
    const host = document.createElement("div")
    host.innerHTML = opts.dev
      ? '<div id="msg-a"></div><div data-state="running"></div>'
      : '<div id="msg-a"></div><div data-task-steps><div data-task-step="working"><button><span></span></button></div></div>'
    Object.defineProperty(host, "scrollHeight", { value: 900 })
    const containerRef = { current: host } as React.RefObject<HTMLDivElement | null>
    render(
      <Spine
        containerRef={containerRef}
        glowColor="#00d4ff"
        isDeveloper={opts.dev}
        prefersReducedMotion={opts.reduced}
        running
        streamingId={null}
        conversationChips={[{ messageId: "a", label: "You: hi", index: 0 }]}
        onChipClick={() => {}}
        knotTurns={[{ ids: ["a"], kind: "ref" }]}
      />,
    )
    return { calls, raf }
  }

  afterEach(() => {
    jest.restoreAllMocks()
    jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null)
  })

  it("animated: a frame is scheduled and the first frame draws the particles, a knot and the agent Xur", () => {
    const { raf } = mountTimeline({ reduced: false, dev: true })
    expect(raf).toHaveBeenCalled()
    const cb = raf.mock.calls[raf.mock.calls.length - 1][0] as FrameRequestCallback
    expect(() => cb(1000)).not.toThrow()
  })

  it("reduced motion: draws one static frame and never schedules a second", () => {
    const { calls, raf } = mountTimeline({ reduced: true, dev: false })
    const cb = raf.mock.calls[raf.mock.calls.length - 1][0] as FrameRequestCallback
    raf.mockClear()
    cb(1000)
    expect(calls.arc || 0).toBeGreaterThan(50) // particles + the knot loop
    expect(raf).not.toHaveBeenCalled() // no loop under prefers-reduced-motion
  })
})

describe("structure: one spine, one agent Xur, chips only on the spine", () => {
  const root = path.resolve(__dirname, "../..")
  const read = (p: string) => fs.readFileSync(path.join(root, p), "utf8")

  it("the composer no longer renders ConversationChips", () => {
    const src = read("components/chat/Composer.tsx")
    expect(src).not.toMatch(/<ConversationChips/)
    expect(src).not.toMatch(/conversationChips|handleChipClick/)
  })
  it("the matrix rail has no Xur of its own (the spine draws the one agent Xur)", () => {
    const src = read("components/chat/matrix/LiveMatrix.tsx")
    expect(src).not.toMatch(/data-matrix-xur/)
    expect(src).not.toMatch(/<Xur\b/)
    expect(src).toMatch(/data-matrix-body/) // the rail line stays
  })
  it("the timeline mounts the spine and gets the chips from chat-view", () => {
    expect(read("components/chat/Timeline.tsx")).toMatch(/<Spine\b/)
    expect(read("components/chat-view.tsx")).toMatch(/<Timeline[\s\S]*conversationChips=\{conversationChips\}[\s\S]*\/>\s*\{\/\* Document View Modal/)
  })
  it("the task card marks its steps and their status for the spine", () => {
    const src = read("components/chat/TaskListCard.tsx")
    expect(src).toMatch(/data-task-steps/)
    expect(src).toMatch(/data-task-step=\{step\.status\}/)
  })
})
