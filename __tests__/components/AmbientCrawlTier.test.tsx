/**
 * REQ-16 / T18 — the tier that replaced OrbBadge.
 *
 * Two things are pinned here, both of which were rules the badge never had to
 * obey and which are therefore easy to lose:
 *
 *  1. AC5 unified counting. Steps and crawl pages are ONE reading. The badge
 *     only ever counted steps, so "what happens when a crawl runs inside a
 *     task" had no answer before. `[0/0]` is explicitly forbidden.
 *  2. The question surface is exclusive with ChatView. When ChatView is up,
 *     QuestionCard owns the question; two live answer surfaces for one
 *     question_id race each other and can double-submit.
 */
import React from "react"
import { render, screen, fireEvent } from "@testing-library/react"
import { unifiedProgress, AmbientCrawlTier } from "@/components/iris/AmbientCrawlTier"

// ── stubs ─────────────────────────────────────────────────────────────────
const mockCrawlState = {
  active: false,
  query: "",
  pages: [] as unknown[],
  total: null as number | null,
  visionActions: [] as unknown[],
}
let mockTaskState = { isWorking: false, currentStep: 0, totalSteps: 0 }
let mockQuestionState: Record<string, unknown> = { hasPendingQuestion: false }

jest.mock("@/hooks/CrawlProvider", () => ({
  useCrawlContext: () => ({ state: mockCrawlState }),
}))
jest.mock("@/hooks/useTaskProgress", () => ({
  useTaskProgress: () => mockTaskState,
}))
jest.mock("@/hooks/useAgentQuestion", () => ({
  useAgentQuestion: () => mockQuestionState,
}))
jest.mock("@/hooks/useReducedMotion", () => ({
  // Reduced motion ON: keeps OrbCanvas out of jsdom, which has no 2d context.
  useReducedMotion: () => true,
}))
jest.mock("@/components/iris/orb/OrbCanvas", () => ({
  OrbCanvas: () => null,
}))

beforeEach(() => {
  Object.assign(mockCrawlState, {
    active: false, query: "", pages: [], total: null, visionActions: [],
  })
  mockTaskState = { isWorking: false, currentStep: 0, totalSteps: 0 }
  mockQuestionState = { hasPendingQuestion: false }
})

// ── AC5: unified counting ────────────────────────────────────────────────
describe("unifiedProgress (REQ-16 AC5)", () => {
  test("sums task steps and crawl pages into ONE reading", () => {
    expect(unifiedProgress({ current: 2, total: 5 }, { done: 3, total: 4 }))
      .toEqual({ done: 5, total: 9 })
  })

  test("never returns [0/0] — nothing countable means total 0, not a zero well", () => {
    expect(unifiedProgress({ current: 0, total: 0 }, { done: 0, total: null }))
      .toEqual({ done: 0, total: 0 })
  })

  test("works with only steps, or only pages", () => {
    expect(unifiedProgress({ current: 1, total: 3 }, { done: 0, total: null }))
      .toEqual({ done: 1, total: 3 })
    expect(unifiedProgress({ current: 0, total: 0 }, { done: 2, total: 6 }))
      .toEqual({ done: 2, total: 6 })
  })

  test("a late page event cannot push the reading past 100%", () => {
    // Crawl page events genuinely can outrun the announced total, and a
    // counter reading [7/4] is worse than a stalled one.
    const r = unifiedProgress({ current: 9, total: 2 }, { done: 7, total: 4 })
    expect(r.done).toBeLessThanOrEqual(r.total)
    expect(r).toEqual({ done: 6, total: 6 })
  })
})

// ── rendering ────────────────────────────────────────────────────────────
describe("AmbientCrawlTier", () => {
  test("renders nothing when nothing is working (OPT GATE)", () => {
    const { container } = render(
      <AmbientCrawlTier glowColor="#0ff" panelVisible={false} />,
    )
    expect(container.firstChild).toBeNull()
  })

  test("shows the unified counter for a task with no crawl", () => {
    mockTaskState = { isWorking: true, currentStep: 1, totalSteps: 4 }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} />)
    expect(screen.getByTestId("tier-counter").textContent).toBe("[1/4]")
  })

  test("a working task with zero steps renders no counter, not [0/0]", () => {
    mockTaskState = { isWorking: true, currentStep: 0, totalSteps: 0 }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} />)
    expect(screen.queryByTestId("tier-counter")).toBeNull()
  })
})

// ── the question surface ─────────────────────────────────────────────────
describe("pending question (REQ-16, user-directed)", () => {
  const q = {
    hasPendingQuestion: true,
    questionId: "q-77",
    text: "Which branch should I use?",
    options: ["main", "develop"],
  }

  test("is answerable in the tier when ChatView is NOT visible", () => {
    mockQuestionState = { ...q }
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} sendMessage={send}
      />,
    )
    expect(screen.getByText("Which branch should I use?")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "develop" }))
    expect(send).toHaveBeenCalledWith("question_response", {
      question_id: "q-77",
      answer: "develop",
      source: "click",
    })
  })

  test("is NOT answerable in the tier when ChatView IS visible", () => {
    // QuestionCard owns it there. Two answer surfaces for one question_id is
    // how the same question gets submitted twice.
    mockQuestionState = { ...q }
    render(
      <AmbientCrawlTier glowColor="#0ff" panelVisible={false} chatVisible={true} />,
    )
    expect(screen.queryByTestId("tier-question")).toBeNull()
  })

  test("offers free text when the asker allows it", () => {
    mockQuestionState = { ...q, options: undefined, allowOther: true }
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} sendMessage={send}
      />,
    )
    const input = screen.getByLabelText("Answer the agent's question")
    fireEvent.change(input, { target: { value: "  rebase  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(send).toHaveBeenCalledWith("question_response", {
      question_id: "q-77",
      answer: "rebase", // trimmed
      source: "text",
    })
  })

  test("an empty answer is never submitted", () => {
    mockQuestionState = { ...q, options: undefined, allowOther: true }
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} sendMessage={send}
      />,
    )
    const input = screen.getByLabelText("Answer the agent's question")
    fireEvent.change(input, { target: { value: "   " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(send).not.toHaveBeenCalled()
  })
})
