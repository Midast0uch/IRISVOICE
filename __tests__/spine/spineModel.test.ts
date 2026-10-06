/**
 * The living spine — pure model (docs/design/chatview-2026-10-06/iris-strands.html).
 * DONE line: detour math, knot rules, chip highlight in view.
 */
import {
  DETOUR_EASE,
  SPINE_X0,
  brandColors,
  brandFrom,
  chipsInView,
  detourWeight,
  normKnotKind,
  parseHue,
  pickTarget,
  scrubTop,
  turnKnots,
  wobbleAt,
  xAt,
  type Detour,
} from "@/components/chat/spine/spineModel"

const card: Detour = { x: 60, y0: 400, y1: 700 }

describe("brand: one hue -> three neighbouring hues", () => {
  it("reads hex, rgb and hsl", () => {
    expect(parseHue("#00d4ff")).toBe(190)
    expect(parseHue("#f00")).toBe(0)
    expect(parseHue("rgb(0, 255, 0)")).toBe(120)
    expect(parseHue("hsl(25, 90%, 60%)")).toBe(25)
    expect(parseHue("not a colour")).toBeNull()
    expect(parseHue("#888888")).toBeNull() // grey has no hue: the default brand is used
  })
  it("derives three different hues from the brand hue", () => {
    const [c1, c2, c3] = brandColors(brandFrom("#00d4ff"))
    expect(new Set([c1, c2, c3]).size).toBe(3)
    expect(c1).toContain("hsla(190,")
  })
})

describe("detour: the spine bends into the personal task card's step line", () => {
  it("is on the spine away from a card and on the step line inside it", () => {
    expect(xAt(0, [card])).toBe(SPINE_X0)
    expect(xAt(card.y0 - DETOUR_EASE - 1, [card])).toBe(SPINE_X0)
    expect(xAt(500, [card])).toBeCloseTo(card.x, 6)
    expect(xAt(card.y1 + DETOUR_EASE + 1, [card])).toBe(SPINE_X0)
  })
  it("bends in smoothly and monotonically over the ease length", () => {
    const xs = [0, 0.25, 0.5, 0.75, 1].map((f) => xAt(card.y0 - DETOUR_EASE + f * DETOUR_EASE, [card]))
    for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThanOrEqual(xs[i - 1])
    expect(xs[0]).toBe(SPINE_X0)
    expect(xs[4]).toBeCloseTo(card.x, 6)
    // halfway through the ease the weight is the smoothstep midpoint
    expect(detourWeight(card, card.y0 - DETOUR_EASE / 2)).toBeCloseTo(0.5, 6)
  })
  it("bends out again below the card", () => {
    expect(detourWeight(card, card.y1 + DETOUR_EASE / 2)).toBeCloseTo(0.5, 6)
    expect(xAt(card.y1 + DETOUR_EASE / 2, [card])).toBeCloseTo(SPINE_X0 + (card.x - SPINE_X0) * 0.5, 6)
  })
  it("with several cards, each pulls only inside its own range", () => {
    const second: Detour = { x: 80, y0: 1000, y1: 1200 }
    expect(xAt(550, [card, second])).toBeCloseTo(card.x, 6)
    expect(xAt(1100, [card, second])).toBeCloseTo(second.x, 6)
    expect(xAt(850, [card, second])).toBe(SPINE_X0)
  })
  it("no detours: a straight spine at the gutter", () => {
    expect(xAt(123, [])).toBe(SPINE_X0)
  })
  it("the wobble is gone inside a card (the step line is straight) and full on the spine", () => {
    expect(wobbleAt(500, [card])).toBe(0)
    expect(wobbleAt(0, [card])).toBe(1)
  })
})

describe("where the agent Xur rides", () => {
  it("the mean of the running rows, else the streaming reply, else nowhere", () => {
    expect(pickTarget([100, 300], 900)).toBe(200)
    expect(pickTarget([], 900)).toBe(900)
    expect(pickTarget([], null)).toBeNull()
  })
})

describe("knots: only where something entered from outside the strand", () => {
  const base = { id: "t1", clientRef: "u1", author: "user", refs: [] as string[] }
  it("a plain turn by the user or IRIS has no knot", () => {
    expect(turnKnots([base, { ...base, id: "t2", author: "iris" }, { ...base, id: "t3", author: "" }])).toEqual([])
  })
  it("a turn with refs is a knot (the user's prompt first, the turn as fallback)", () => {
    expect(turnKnots([{ ...base, refs: ["#T-38"] }])).toEqual([{ ids: ["u1", "t1"], kind: "ref" }])
    expect(turnKnots([{ ...base, clientRef: undefined, refs: ["#T-38"] }])).toEqual([{ ids: ["t1"], kind: "ref" }])
  })
  it("a turn from another author is a knot", () => {
    expect(turnKnots([{ ...base, author: "ana" }])).toEqual([{ ids: ["u1", "t1"], kind: "author" }])
  })
  it("a mixed list keeps only the knots", () => {
    const out = turnKnots([base, { ...base, id: "t2", refs: ["#A-12"] }, { ...base, id: "t3" }])
    expect(out.map((k) => k.ids[1])).toEqual(["t2"])
  })
  it("the data-knot contract: unknown kinds fall back to ref; no kind ever means landmark", () => {
    expect(normKnotKind("author")).toBe("author")
    expect(normKnotKind("helper")).toBe("helper")
    expect(normKnotKind("ref")).toBe("ref")
    expect(normKnotKind("landmark")).toBe("ref")
    expect(normKnotKind(undefined)).toBe("ref")
  })
})

describe("chips: the turns in view", () => {
  const chips = [{ y: 50 }, { y: 150 }, { y: 250 }, { y: 600 }, {}]
  it("highlights the turns whose top is inside the visible range", () => {
    expect(chipsInView(chips, 100, 300)).toEqual([false, true, true, false, false])
  })
  it("follows the scroll", () => {
    expect(chipsInView(chips, 500, 300)).toEqual([false, false, false, true, false])
  })
  it("a turn that is not rendered (no y) is never highlighted", () => {
    expect(chipsInView([{}], 0, 1000)).toEqual([false])
  })
})

describe("drag on the gutter scrubs the scroll", () => {
  it("maps the fraction of the gutter to scrollTop and clamps", () => {
    expect(scrubTop(0, 2000, 500)).toBe(0)
    expect(scrubTop(0.5, 2000, 500)).toBe(750)
    expect(scrubTop(1, 2000, 500)).toBe(1500)
    expect(scrubTop(-1, 2000, 500)).toBe(0)
    expect(scrubTop(2, 2000, 500)).toBe(1500)
    expect(scrubTop(0.5, 300, 500)).toBe(0) // content shorter than the view
  })
})
