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
import { render, screen, fireEvent, act } from "@testing-library/react"
import { unifiedProgress, AmbientCrawlTier } from "@/components/iris/AmbientCrawlTier"

// ── stubs ─────────────────────────────────────────────────────────────────
const mockCrawlState = {
  active: false,
  query: "",
  pages: [] as unknown[],
  total: null as number | null,
  visionActions: [] as unknown[],
}
// `steps` is required by the real TaskProgress interface and the tier now
// reads it to decide whether a LIVE TaskListCard already owns the step
// display. Fixture updated 2026-08-25 (called out per the test rule); no
// assertion changed. Default [] = "no card is driving progress".
let mockTaskState: Record<string, unknown> =
  { isWorking: false, currentStep: 0, totalSteps: 0, steps: [] as unknown[] }
let mockQuestionState: Record<string, unknown> = { hasPendingQuestion: false, questions: [] }

/**
 * FIXTURE UPDATED 2026-08-25 — called out per the test rule. No assertion in
 * this file changed; the HOOK's contract did.
 *
 * useAgentQuestion now mirrors what the AskUserQuestion tool actually emits: a
 * question SET (`questions[]`), because the tool only includes the legacy
 * top-level question_id/text/options keys when the set holds exactly one
 * question. A mock returning just the flat keys pins a shape the real hook can
 * no longer produce. This helper builds BOTH representations from one spec so
 * they cannot drift apart inside the fixtures.
 */
function mkQuestion(over: Record<string, unknown> = {}) {
  const base = {
    questionId: "q-77",
    text: "Which branch should I use?",
    options: ["main", "develop"] as string[] | undefined,
    allowOther: false,
    multiSelect: false,
    ...over,
  }
  return { hasPendingQuestion: true, ...base, questions: [base] }
}

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
  mockTaskState = { isWorking: false, currentStep: 0, totalSteps: 0, steps: [] }
  mockQuestionState = { hasPendingQuestion: false, questions: [] }
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
    mockTaskState = { isWorking: true, currentStep: 1, totalSteps: 4 , steps: [] }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} />)
    expect(screen.getByTestId("tier-counter").textContent).toBe("[1/4]")
  })

  test("a working task with zero steps renders no counter, not [0/0]", () => {
    mockTaskState = { isWorking: true, currentStep: 0, totalSteps: 0 , steps: [] }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} />)
    expect(screen.queryByTestId("tier-counter")).toBeNull()
  })
})

// ── who owns the progress display (REQ-16, the anti-duplication rule) ────
//
// Retiring OrbBadge removed one duplicate indicator. These pin that the tier
// does not quietly introduce another: it shows only what no VISIBLE surface is
// already showing. Every case below was reachable before the rule existed.
describe("progress ownership", () => {
  const workingStep = [{ status: "working" }]

  test("ChatView with a LIVE task card owns the steps — tier does not repeat them", () => {
    mockTaskState = { isWorking: true, currentStep: 3, totalSteps: 7, steps: workingStep }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} chatVisible={true} />)
    // The card is showing [3/7]; a second [3/7] beside the orb is the debt.
    expect(screen.queryByTestId("tier-counter")).toBeNull()
  })

  test("ChatView open but the card is STATIC — tier speaks again", () => {
    // Every step resolved: chat-view's own note records the card going static
    // and the UI falling silent for the synthesis phase (measured at 79s).
    mockTaskState = {
      isWorking: true, currentStep: 7, totalSteps: 7,
      steps: [{ status: "done" }, { status: "done" }],
    }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} chatVisible={true} />)
    expect(screen.getByTestId("tier-counter").textContent).toBe("[7/7]")
  })

  test("ChatView CLOSED — the tier is the only indicator, so it shows the steps", () => {
    mockTaskState = { isWorking: true, currentStep: 3, totalSteps: 7, steps: workingStep }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={false} chatVisible={false} />)
    expect(screen.getByTestId("tier-counter").textContent).toBe("[3/7]")
  })

  test("browser panel owns the crawl pages — tier counts only the steps", () => {
    Object.assign(mockCrawlState, { active: true, pages: [1, 2, 3], total: 4 })
    mockTaskState = { isWorking: true, currentStep: 1, totalSteps: 2, steps: workingStep }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={true} chatVisible={false} />)
    // 1/2 from steps only — NOT 4/6 with the panel's own pages folded in.
    expect(screen.getByTestId("tier-counter").textContent).toBe("[1/2]")
  })

  test("both surfaces own their halves — tier degrades to the presence dot", () => {
    Object.assign(mockCrawlState, { active: true, pages: [1, 2], total: 4 })
    mockTaskState = { isWorking: true, currentStep: 1, totalSteps: 3, steps: workingStep }
    render(<AmbientCrawlTier glowColor="#0ff" panelVisible={true} chatVisible={true} />)
    expect(screen.queryByTestId("tier-counter")).toBeNull()
    expect(screen.getByText("READING")).toBeTruthy()
  })

  test("nothing to add and no panel dot — renders nothing, not an empty pill", () => {
    mockTaskState = { isWorking: true, currentStep: 2, totalSteps: 5, steps: workingStep }
    const { container } = render(
      <AmbientCrawlTier glowColor="#0ff" panelVisible={false} chatVisible={true} />,
    )
    expect(container.innerHTML).toBe("")
  })
})

// ── the question surface ─────────────────────────────────────────────────
describe("pending question (REQ-16, user-directed)", () => {
  const q = mkQuestion()

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
    mockQuestionState = mkQuestion({ options: undefined, allowOther: true })
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} sendMessage={send}
      />,
    )
    // SELECTOR UPDATED 2026-08-25 (called out per the test rule; the two
    // assertions below are unchanged). The input's aria-label was a generic
    // "Answer the agent's question"; it is now the QUESTION TEXT, because a
    // question SET renders one input per question and N identical labels are
    // ambiguous to a screen reader. Labelling each input by its own question
    // is the correct a11y, so the test queries by that instead.
    const input = screen.getByLabelText("Which branch should I use?")
    fireEvent.change(input, { target: { value: "  rebase  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(send).toHaveBeenCalledWith("question_response", {
      question_id: "q-77",
      answer: "rebase", // trimmed
      source: "text",
    })
  })

  test("an empty answer is never submitted", () => {
    mockQuestionState = mkQuestion({ options: undefined, allowOther: true })
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} sendMessage={send}
      />,
    )
    // SELECTOR UPDATED 2026-08-25 (called out per the test rule; the two
    // assertions below are unchanged). The input's aria-label was a generic
    // "Answer the agent's question"; it is now the QUESTION TEXT, because a
    // question SET renders one input per question and N identical labels are
    // ambiguous to a screen reader. Labelling each input by its own question
    // is the correct a11y, so the test queries by that instead.
    const input = screen.getByLabelText("Which branch should I use?")
    fireEvent.change(input, { target: { value: "   " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(send).not.toHaveBeenCalled()
  })
})

// ── T20: the inline ask, and the thread-identity landmine it sits on ──────
//
// REQ-16 AC4 requires a contract test that the submitted payload carries the
// id of the thread active AT SUBMIT TIME. The history behind that requirement:
// useIRISWebSocket.ts:1758 records four kernels constructed for ONE question
// as the id drifted, and chat-view.tsx:1828 records every new conversation
// collapsing into a single session-keyed thread. `text_message` is therefore
// deliberately excluded from the socket's SUPPLY_IF_MISSING set — a missing id
// is a visible fallback, a wrong one silently corrupts thread history.
describe("inline ask (REQ-16 AC4 / T20)", () => {
  beforeEach(() => {
    mockTaskState = { isWorking: true, currentStep: 1, totalSteps: 3, steps: [] }
  })

  test("sends text_message with the socket's authoritative conversation_id", () => {
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false}
        sendMessage={send} conversationId="conv_authoritative_1"
      />,
    )
    fireEvent.click(screen.getByTestId("tier-counter-form"))
    const input = screen.getByTestId("tier-ask-input")
    fireEvent.change(input, { target: { value: "  what is the status  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(send).toHaveBeenCalledWith("text_message", {
      text: "what is the status",
      conversation_id: "conv_authoritative_1",
    })
  })

  test("REFUSES to send when there is no authoritative id — never guesses", () => {
    // The dangerous version of this feature falls back to a stored/stale id
    // here. That is precisely the conv-merge incident. No id -> no ask at all.
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false}
        sendMessage={send} conversationId={undefined}
      />,
    )
    fireEvent.click(screen.getByTestId("tier-counter-form"))
    expect(screen.queryByTestId("tier-ask-input")).toBeNull()
    expect(send).not.toHaveBeenCalled()
  })

  test("an empty ask is never sent", () => {
    const send = jest.fn()
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false}
        sendMessage={send} conversationId="conv_x"
      />,
    )
    fireEvent.click(screen.getByTestId("tier-counter-form"))
    const input = screen.getByTestId("tier-ask-input")
    fireEvent.change(input, { target: { value: "   " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(send).not.toHaveBeenCalled()
  })
})

// ── the two forms: which one shows depends on whether XurOrb is on screen ──
//
// User-directed 2026-08-25. The mini orb is the APPLICATION'S LOGO, so the
// question is not decoration — it is whether the app has a brand mark on
// screen at all.
//
//   wing open  -> XurOrb hidden, tier stands in for it -> MINI ORB REQUIRED
//   no wings   -> XurOrb visible, tier sits at the old badge spot -> omitted
//
// The no-wings case is also the ONLY state where orb and tier are both
// visible, and that is the point: XurOrb is a movable desktop widget, so the
// pair must let the user watch progress and talk to the agent without opening
// the full interface.
describe("the two forms (mini orb / branding)", () => {
  beforeEach(() => {
    mockTaskState = { isWorking: true, currentStep: 2, totalSteps: 6, steps: [] }
  })

  test("swallowed: ONE ring, orb inside it, counter out on the pill", () => {
    // The redundancy this replaced: a 40px logo parked next to a 44px ring —
    // the same shape twice, neither belonging to the other. The ring is now
    // the orb's own halo, so the reading has to move out of its centre.
    // Exactly one counter node must exist; getByTestId throws on duplicates,
    // which is the assertion that catches a stale centred copy left behind.
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={true}
      />,
    )
    const orb = screen.getByTestId("tier-mini-orb")
    const counter = screen.getByTestId("tier-counter")
    expect(counter.textContent).toBe("[2/6]")
    // The counter is a SIBLING on the pill, not stacked over the logo.
    expect(orb.contains(counter)).toBe(false)
  })

  test("swallowed: counter and status are ONE stacked block, not loose items", () => {
    // User feedback 2026-08-25: a counter floating between the orb and the
    // status text had nothing to align to. They now share a parent so the
    // count sits directly above the text and both stay tight to the mark.
    Object.assign(mockCrawlState, { active: true, query: "mechanical keyboards", pages: [], total: 4 })
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={true}
      />,
    )
    const counter = screen.getByTestId("tier-counter")
    const status = screen.getByText(/mechanical keyboards/)
    expect(counter.parentElement).toBe(status.parentElement)
    // Stacked, not inline — the block is a column.
    expect(counter.parentElement?.className).toContain("flex-col")
  })

  test("the mini orb and the particle field are ALTERNATIVES, never both", () => {
    // User-directed 2026-08-25. Each form carries the orb identity exactly
    // once: swallowed it is the mark inside the ring, beside it is the field
    // across the card. Running both would double the canvases and clutter the
    // very mark the field is standing in for.
    // (Reduced motion is ON in this suite, so the field is asserted through
    // the swallowed branch only — see the reduced-motion test below.)
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={true}
      />,
    )
    expect(screen.getByTestId("tier-mini-orb")).toBeTruthy()
    expect(screen.queryByTestId("tier-particle-field")).toBeNull()
  })

  test("swallowed: no progress ring — it drowns out the logo", () => {
    // A 2px arc at 44px sits right on the mark's edge and competes with it for
    // the same silhouette. The reading is stacked on the pill instead, so the
    // arc has nothing left to say there.
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={true}
      />,
    )
    const svg = screen.getByTestId("ambient-crawl-tier").querySelector("svg")
    expect(svg?.querySelectorAll("circle").length ?? 0).toBe(0)
  })

  test("beside: the ring IS drawn — it circles the counter, not the logo", () => {
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={false}
      />,
    )
    const svg = screen.getByTestId("ambient-crawl-tier").querySelector("svg")
    expect((svg?.querySelectorAll("circle").length ?? 0)).toBeGreaterThan(0)
  })

  test("wing open: the tier carries the mini orb, because XurOrb is hidden", () => {
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={true}
      />,
    )
    expect(screen.getByTestId("tier-mini-orb")).toBeTruthy()
  })

  test("no wings: no mini orb — the real orb is right there", () => {
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={false}
      />,
    )
    expect(screen.queryByTestId("tier-mini-orb")).toBeNull()
    // ...but the counter is still shown, at the retired badge's position.
    expect(screen.getByTestId("tier-counter").textContent).toBe("[2/6]")
  })

  test("swallowed with nothing to count STILL renders — the logo must persist", () => {
    // Everything owned elsewhere. The beside form would render nothing here;
    // the swallowed form must not, or the app loses its brand mark entirely
    // for as long as the wing is open.
    mockTaskState = {
      isWorking: true, currentStep: 3, totalSteps: 7, steps: [{ status: "working" }],
    }
    render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={true} chatVisible={true} wingOpen={true}
      />,
    )
    expect(screen.getByTestId("tier-mini-orb")).toBeTruthy()
    expect(screen.queryByTestId("tier-counter")).toBeNull()
  })
})

// ── Rules of Hooks: the idle -> active transition ─────────────────────────
//
// Caught at runtime, NOT by this suite, and the gap is instructive: every
// other test here renders the tier once in a single state. The tier has three
// early returns, so declaring a hook below them makes the hook COUNT depend on
// whether there is anything to show — 5 idle, 7 active — and React throws
// "Rendered more hooks than during the previous render" the moment work starts.
// A component that renders in one state forever never performs that
// transition, so a mount-only test cannot see it. This one rerenders.
describe("hook order across the idle -> active transition", () => {
  test("going from nothing-to-show to working does not change hook count", () => {
    mockTaskState = { isWorking: false, currentStep: 0, totalSteps: 0, steps: [] }
    const { rerender, container } = render(
      <AmbientCrawlTier
        glowColor="#0ff" panelVisible={false} chatVisible={false}
        sendMessage={jest.fn()} conversationId="conv_1"
      />,
    )
    expect(container.innerHTML).toBe("") // idle: the tier returns null

    // Work starts — the same instance now renders its full body.
    mockTaskState = { isWorking: true, currentStep: 1, totalSteps: 4, steps: [] }
    expect(() =>
      act(() => {
        rerender(
          <AmbientCrawlTier
            glowColor="#0ff" panelVisible={false} chatVisible={false}
            sendMessage={jest.fn()} conversationId="conv_1"
          />,
        )
      }),
    ).not.toThrow()
    expect(screen.getByTestId("tier-counter").textContent).toBe("[1/4]")

    // ...and back to idle, which is the reverse transition.
    mockTaskState = { isWorking: false, currentStep: 0, totalSteps: 0, steps: [] }
    expect(() =>
      act(() => {
        rerender(
          <AmbientCrawlTier
            glowColor="#0ff" panelVisible={false} chatVisible={false}
            sendMessage={jest.fn()} conversationId="conv_1"
          />,
        )
      }),
    ).not.toThrow()
  })
})

// ── the swallow target (T19) ──────────────────────────────────────────────
//
// The orb and the tier live in different subtrees and neither can know the
// other's geometry: the logo slot's x depends on the card's width, which
// depends on the status text. Without a shared measured point the orb can only
// shrink and fade WHERE IT STANDS, which is what read as snapping out of
// existence rather than being absorbed.
describe("swallow target publication", () => {
  const { setSwallowTarget } = jest.requireActual("@/components/iris/swallowTarget")

  beforeEach(() => {
    setSwallowTarget(null)
    mockTaskState = { isWorking: true, currentStep: 2, totalSteps: 6, steps: [] }
  })

  test("publishes the logo slot while swallowed, and clears it on release", () => {
    const { useSwallowTarget } = jest.requireActual("@/components/iris/swallowTarget")
    function Probe() {
      const t = useSwallowTarget()
      return <span data-testid="probe">{t ? "has-target" : "none"}</span>
    }

    const { rerender } = render(
      <>
        <AmbientCrawlTier
          glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={true}
        />
        <Probe />
      </>,
    )
    // jsdom reports zeros for getBoundingClientRect, but a point IS published —
    // which is the contract the orb depends on: target present <=> swallowed.
    expect(screen.getByTestId("probe").textContent).toBe("has-target")

    // Wing closes -> the tier stops standing in for the orb -> target cleared,
    // so a stale point can never drag the orb somewhere meaningless.
    rerender(
      <>
        <AmbientCrawlTier
          glowColor="#0ff" panelVisible={false} chatVisible={false} wingOpen={false}
        />
        <Probe />
      </>,
    )
    expect(screen.getByTestId("probe").textContent).toBe("none")
  })
})
