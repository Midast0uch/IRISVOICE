/**
 * Owner fix 3 (2026-10-06): the model's live reasoning shows in ONE place per turn.
 *   developer + matrix: the matrix THK line shows the latest sentence of the turn's reasoning
 *     (the card's current action only when the turn has none); no second "THK :" line under the turn.
 *   developer, no matrix (a direct reply): the reasoning line under the turn stays.
 *   personal + card: ONE italic line under the running step ("thinking · <latest sentence>");
 *     no "Thinking:" line under the reply, no action-based THK strip next to it.
 *   personal, no card: the existing "Thinking: ..." line stays.
 *   after the turn ends the line is gone (the "Show thinking" collapsible keeps the full text).
 */
import React from "react"
import { screen } from "@testing-library/react"
import "@testing-library/jest-dom"
import { card, mountTimeline, msg, part, reduce, startMsg, TURN } from "../turnui/harness"

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

const FIRST = "I will read the router first."
const LATEST = "The cap subtracts max_tokens but not the reserve."

function runningTurn(mode: "personal" | "developer", reasoning: string | null = `${FIRST} ${LATEST}`) {
  const msgs = [startMsg(mode)]
  if (reasoning) msgs.push(part({ type: "reasoning", delta: reasoning }))
  return reduce(msgs).byId[TURN]
}
const working = () => [{ id: "n1", description: "read router.py", status: "working", toolName: "read_file" }]
const aCard = () => card(working(), { currentAction: "reading router.py" })

describe("developer: one place, the matrix THK line", () => {
  it("shows the latest sentence of the turn's reasoning and no second THK line under the turn", () => {
    const { container } = mountTimeline({ isDeveloper: true, turn: runningTurn("developer"), card: aCard() })
    const thk = container.querySelector("[data-matrix-thk]") as HTMLElement
    expect(thk).toHaveTextContent(LATEST)
    expect(thk).not.toHaveTextContent(FIRST)
    expect(thk).not.toHaveTextContent("reading router.py") // reasoning wins over the action
    expect(container.querySelectorAll('[data-part="reasoning"]')).toHaveLength(0)
    expect(screen.queryByText("THK :")).toBeNull()
    expect(screen.getAllByText("THK")).toHaveLength(1)
  })

  it("falls back to the card's current action when the turn has no reasoning", () => {
    const { container } = mountTimeline({ isDeveloper: true, turn: runningTurn("developer", null), card: aCard() })
    expect(container.querySelector("[data-matrix-thk]")).toHaveTextContent("reading router.py")
    expect(container.querySelectorAll('[data-part="reasoning"]')).toHaveLength(0)
  })

  it("keeps the reasoning line under the turn when there is no matrix (a direct reply)", () => {
    const { container } = mountTimeline({ isDeveloper: true, turn: runningTurn("developer") })
    expect(container.querySelector("[data-matrix-thk]")).toBeNull()
    const line = container.querySelector('[data-part="reasoning"]') as HTMLElement
    expect(line).toHaveTextContent("THK :")
    expect(line).toHaveTextContent(LATEST)
  })
})

describe("personal: one italic line in the card, under the running step", () => {
  it("shows 'thinking · <latest sentence>' once, with no 'Thinking:' under the reply and no THK strip", () => {
    const { container } = mountTimeline({ isDeveloper: false, turn: runningTurn("personal"), card: aCard() })
    const lines = container.querySelectorAll("[data-thinking-line]")
    expect(lines).toHaveLength(1)
    expect(lines[0]).toHaveTextContent(`thinking · ${LATEST}`)
    expect(lines[0].textContent).not.toContain(FIRST)
    expect((lines[0] as HTMLElement).className).toMatch(/italic/)
    expect((lines[0] as HTMLElement).className).toMatch(/truncate/)
    // it sits inside the running step's row group
    expect(lines[0].closest('[data-task-step="working"]')).not.toBeNull()
    expect(container.querySelectorAll('[data-part="reasoning"]')).toHaveLength(0)
    expect(screen.queryByText(/Thinking:/)).toBeNull()
    expect(screen.queryByText("THK")).toBeNull()
    expect(screen.getAllByText(/thinking/i)).toHaveLength(1)
  })

  it("keeps the existing one-line 'Thinking: ...' under the reply when the turn has no card", () => {
    const { container } = mountTimeline({ isDeveloper: false, turn: runningTurn("personal") })
    expect(container.querySelectorAll("[data-thinking-line]")).toHaveLength(0)
    expect(screen.getByText(`Thinking: ${LATEST}`)).toBeInTheDocument()
  })

  it("the line is gone after the turn ends", () => {
    const ended = reduce([startMsg("personal"), part({ type: "reasoning", delta: `${FIRST} ${LATEST}` }), msg("turn.end", { status: "ok", text: "Done.", speak: "", parts: 1 })]).byId[TURN]
    expect(ended.status).toBe("ok")
    const { container } = mountTimeline({ isDeveloper: false, turn: ended, card: aCard() })
    expect(container.querySelectorAll("[data-thinking-line]")).toHaveLength(0)
    expect(screen.queryByText(/Thinking:/)).toBeNull()
  })

  it("a card with no reasoning keeps its own action-based THK strip and shows no thinking line", () => {
    const { container } = mountTimeline({ isDeveloper: false, turn: runningTurn("personal", null), card: aCard() })
    expect(container.querySelectorAll("[data-thinking-line]")).toHaveLength(0)
    expect(screen.getByText("THK")).toBeInTheDocument()
  })
})
