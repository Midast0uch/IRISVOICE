/**
 * Owner fix 2 (2026-10-06): a knot on the spine is a real, focusable hit target (a button over
 * the canvas; the canvas stays pointer-events none). Hover or focus shows a small card:
 *   ref knot     -> the ref addresses (each a link that opens it), the turn's first words, the time
 *   author knot  -> "From <author>"
 *   helper knot  -> "Reported back from <strand>"
 * Click jumps to the turn (the spine chips' path: onChipClick). Tab reaches knots, Enter jumps
 * (a native button: the browser turns Enter into this click), Esc closes the card.
 * The knot data contract (data-knot, knotTurns) is unchanged.
 */
import React from "react"
import { render, screen, fireEvent, within, act } from "@testing-library/react"
import "@testing-library/jest-dom"
import { Spine, type KnotRefTarget } from "@/components/chat/spine/Spine"
import { turnKnots } from "@/components/chat/spine/spineModel"
import { Timeline } from "@/components/chat/Timeline"
import { closeLens, getLens } from "@/lib/lens/lensStore"
import { CONV, card, mountTimeline, msg, reduce, startMsg, TURN } from "../turnui/harness"
import type { TurnRecord } from "@/lib/turns/turnStore"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#22d3ee" }, shimmer: { primary: "#22d3ee" }, accent: "#22d3ee" }),
  }),
  BrandColorProvider: ({ children }: { children: React.ReactNode }) => children,
}))
jest.mock("framer-motion", () => {
  const React = require("react")
  const motion: any = new Proxy({}, { get: (_t: any, tag: string) => React.forwardRef((p: any, ref: any) => {
    const { initial, animate, exit, transition, whileHover, whileTap, layout, ...rest } = p || {}
    return React.createElement(tag, { ...rest, ref }, p?.children)
  }) })
  return { motion, AnimatePresence: ({ children }: any) => children }
})
jest.mock("@/components/Xur", () => ({ Xur: () => <div data-testid="xur" /> }))

beforeAll(() => {
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null)
})
beforeEach(() => closeLens())

const T0 = new Date(2026, 9, 6, 14, 5).getTime() / 1000

function turn(id: string, clientRef: string, over: Record<string, unknown>): TurnRecord {
  const r = reduce([
    msg("turn.start", { turn_id: id, strand_id: CONV, author: "user", to: ["@iris"], refs: [], mode: "developer", client_ref: clientRef, ts: T0, ...over }),
  ])
  return r.byId[id]
}

const REF_TURN = turn("t-ref", "u-ref", { refs: ["#T-38", "#doc-1", "#strand-2", "#nowhere"], prompt: "Continue T-38 with the rule from budget rules please and then run the tests" })
const AUTHOR_TURN = turn("t-auth", "u-auth", { author: "ana.iris", prompt: "A fix to try: subtract a 256 token reserve" })

function mountSpine(over: Partial<React.ComponentProps<typeof Spine>> = {}) {
  const host = document.createElement("div")
  host.innerHTML =
    '<div id="msg-u-ref">Continue T-38</div>' +
    '<div id="msg-u-auth">A fix to try</div>' +
    '<div id="msg-h1" data-knot="helper" data-knot-from="check callers">only generate() uses the cap</div>' +
    '<div id="msg-plain">no knot here</div>'
  document.body.appendChild(host)
  const containerRef = { current: host } as React.RefObject<HTMLDivElement | null>
  const onChipClick = jest.fn()
  const resolveRef = jest.fn((a: string): KnotRefTarget | null => {
    if (a === "#T-38") return { kind: "card", open: opens.card }
    if (a === "#doc-1") return { kind: "artifact", open: opens.artifact }
    if (a === "#strand-2") return { kind: "strand", open: opens.strand }
    return null
  })
  const opens = { card: jest.fn(), artifact: jest.fn(), strand: jest.fn() }
  const turns = [REF_TURN, AUTHOR_TURN]
  const utils = render(
    <Spine
      containerRef={containerRef}
      glowColor="#00d4ff"
      isDeveloper
      prefersReducedMotion
      running={false}
      streamingId={null}
      conversationChips={[]}
      onChipClick={onChipClick}
      knotTurns={turnKnots(turns)}
      turns={turns}
      resolveRef={resolveRef}
      {...over}
    />,
  )
  return { host, onChipClick, opens, ...utils }
}

const knot = (kind: string) => screen.getAllByTestId("spine-knot").find((b) => b.getAttribute("data-knot-kind") === kind) as HTMLElement
const wrapOf = (b: HTMLElement) => b.parentElement as HTMLElement

describe("a knot is a real hit target", () => {
  it("has one focusable button per knot (and none for a plain turn); the canvas stays pointer-events none", () => {
    const { container } = mountSpine()
    const buttons = screen.getAllByTestId("spine-knot")
    expect(buttons.map((b) => b.getAttribute("data-knot-kind")).sort()).toEqual(["author", "helper", "ref"])
    for (const b of buttons) {
      expect(b.tagName).toBe("BUTTON")
      expect(b).toHaveAttribute("type", "button")
      expect(b.getAttribute("tabindex")).toBeNull() // in the Tab order
      expect(b.style.pointerEvents).toBe("auto")
      expect(wrapOf(b).style.pointerEvents).toBe("none")
    }
    expect((container.querySelector("[data-spine-canvas]") as HTMLElement).style.pointerEvents).toBe("none")
    expect((container.querySelector("[data-spine]") as HTMLElement).style.pointerEvents).toBe("none")
    expect(screen.queryByTestId("spine-knot-card")).toBeNull()
  })

  it("the data contract is unchanged: data-knot on an entry and knotTurns still make the knots", () => {
    const { host } = mountSpine()
    expect(host.querySelector('[data-knot="helper"]')).not.toBeNull()
    expect(screen.getAllByTestId("spine-knot")).toHaveLength(3)
  })
})

describe("the hover card, per kind", () => {
  it("ref knot: each ref address, the first words of the turn, the time", () => {
    mountSpine()
    fireEvent.mouseEnter(wrapOf(knot("ref")))
    const card = screen.getByTestId("spine-knot-card")
    expect(card).toHaveTextContent("Pulled in")
    for (const a of ["#T-38", "#doc-1", "#strand-2", "#nowhere"]) expect(card).toHaveTextContent(a)
    expect(card).toHaveTextContent("Continue T-38 with the rule from budget rules…") // first 8 words
    expect(card).not.toHaveTextContent("run the tests")
    expect(card).toHaveTextContent(new Date(T0 * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))
  })

  it("author knot: the author", () => {
    mountSpine()
    fireEvent.mouseEnter(wrapOf(knot("author")))
    const card = screen.getByTestId("spine-knot-card")
    expect(card).toHaveTextContent("From ana.iris")
    expect(card).toHaveTextContent("A fix to try: subtract a 256 token…")
  })

  it("helper knot: 'Reported back from <strand>'", () => {
    mountSpine()
    fireEvent.mouseEnter(wrapOf(knot("helper")))
    const card = screen.getByTestId("spine-knot-card")
    expect(card).toHaveTextContent("Reported back from check callers")
    expect(card).toHaveTextContent("only generate() uses the cap") // no turn record: the entry's own first words
  })

  it("leaving the knot closes the card", () => {
    mountSpine()
    fireEvent.mouseEnter(wrapOf(knot("ref")))
    expect(screen.getByTestId("spine-knot-card")).toBeInTheDocument()
    fireEvent.mouseLeave(wrapOf(knot("ref")))
    expect(screen.queryByTestId("spine-knot-card")).toBeNull()
  })
})

describe("click and keyboard", () => {
  it("click jumps to the turn through the chips' path (onChipClick with the message id)", () => {
    const { onChipClick } = mountSpine()
    fireEvent.click(knot("ref"))
    expect(onChipClick).toHaveBeenCalledWith("u-ref")
    fireEvent.click(knot("helper"))
    expect(onChipClick).toHaveBeenLastCalledWith("h1")
    expect(onChipClick).toHaveBeenCalledTimes(2)
  })

  it("focus shows the card, Esc closes it; a focused knot is a button, so Enter is its click (the jump)", () => {
    const { onChipClick } = mountSpine()
    const b = knot("author")
    act(() => b.focus())
    expect(document.activeElement).toBe(b)
    expect(screen.getByTestId("spine-knot-card")).toHaveTextContent("From ana.iris")
    expect(b).toHaveAttribute("aria-describedby", screen.getByTestId("spine-knot-card").id)
    fireEvent.keyDown(b, { key: "Escape" })
    expect(screen.queryByTestId("spine-knot-card")).toBeNull()
    expect(onChipClick).not.toHaveBeenCalled()
    fireEvent.click(b) // what the browser sends for Enter on a focused button
    expect(onChipClick).toHaveBeenCalledWith("u-auth")
  })

  it("blur closes the card", () => {
    mountSpine()
    const b = knot("ref")
    act(() => b.focus())
    expect(screen.getByTestId("spine-knot-card")).toBeInTheDocument()
    act(() => b.blur())
    expect(screen.queryByTestId("spine-knot-card")).toBeNull()
  })

  it("every ref that resolves is a link that opens it; one that does not stays plain text", () => {
    const { opens } = mountSpine()
    fireEvent.mouseEnter(wrapOf(knot("ref")))
    const card = screen.getByTestId("spine-knot-card")
    const links = within(card).getAllByRole("button")
    expect(links.map((l) => l.getAttribute("data-knot-ref"))).toEqual(["#T-38", "#doc-1", "#strand-2"])
    expect(card.querySelector('span[data-knot-ref="#nowhere"]')).not.toBeNull()
    fireEvent.click(links[0])
    expect(opens.card).toHaveBeenCalledTimes(1)
    fireEvent.mouseEnter(wrapOf(knot("ref")))
    fireEvent.click(within(screen.getByTestId("spine-knot-card")).getByText(/#doc-1/))
    expect(opens.artifact).toHaveBeenCalledTimes(1)
    fireEvent.mouseEnter(wrapOf(knot("ref")))
    fireEvent.click(within(screen.getByTestId("spine-knot-card")).getByText(/#strand-2/))
    expect(opens.strand).toHaveBeenCalledTimes(1)
  })

  it("without a resolver the refs are shown as addresses only", () => {
    mountSpine({ resolveRef: undefined })
    fireEvent.mouseEnter(wrapOf(knot("ref")))
    const card = screen.getByTestId("spine-knot-card")
    expect(within(card).queryAllByRole("button")).toHaveLength(0)
    expect(card).toHaveTextContent("#T-38")
  })
})

describe("through the real Timeline: a ref opens its target", () => {
  function mountWithRefs() {
    const user = turn(TURN, "u1", { refs: ["#card-1", "#doc-1", "#strand-2"], prompt: "fix the cap" })
    const documents = [{ id: "doc-1", documentId: "doc-1", title: "Plan.md", format: "markdown", content: "hi", turnId: TURN }]
    const m = mountTimeline({ isDeveloper: true, turn: user, card: card([{ id: "n1", description: "read", status: "done", toolName: "read_file" }]), documents })
    const onOpenStrand = jest.fn()
    m.props.conversations = [...m.props.conversations, { ...m.props.conversations[0], id: "strand-2" }]
    m.rerender(<Timeline {...m.props} onOpenStrand={onOpenStrand} />)
    return { ...m, onOpenStrand }
  }

  it("task card: scrolls to it and highlights it; artifact: opens the lens; strand: the open-strand handler", () => {
    const scroll = jest.fn()
    ;(Element.prototype as any).scrollIntoView = scroll
    const { onOpenStrand, container } = mountWithRefs()
    const open = (addr: string) => {
      fireEvent.mouseEnter(wrapOf(screen.getByTestId("spine-knot")))
      fireEvent.click(within(screen.getByTestId("spine-knot-card")).getByText(new RegExp(addr)))
    }
    open("#card-1")
    expect(scroll).toHaveBeenCalledTimes(1)
    expect(scroll.mock.instances[0]).toBe(container.querySelector('[data-card-id="card-1"]'))
    expect(container.querySelector('[data-card-id="card-1"]')!.classList.contains("chip-highlight")).toBe(true)
    open("#doc-1")
    expect(getLens()).toEqual({ kind: "artifact", docId: "doc-1" })
    open("#strand-2")
    expect(onOpenStrand).toHaveBeenCalledWith("strand-2")
  })
})
