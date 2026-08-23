/**
 * BEHAVIORAL CONTRACT — task card replay of a REAL websearch trace.
 *
 * Source: live conv-44 / conv-51 WS captures (session 247, via a WebSocket
 * frame tap). Every dispatch below is a frame that actually arrived, in the
 * actual order. The contract assertions encode what the card MUST exhibit:
 *
 *   C1  task:start establishes ONE card with the backend's card_id — never a
 *       fabricated legacy_unknown card.
 *   C2  crawl phase transitions append PROGRESSIVE step nodes
 *       (SEARCH → READ/FETCH → EXTRACT → CITE), each marked done when the
 *       next arrives — not one node whose verb silently swaps.
 *   C3  per-page frames update the newest working node's detail (THK stream)
 *       without creating duplicate nodes.
 *   C4  late "Synthesizing answer" progress attaches to the SAME card (no
 *       phantom second card) even though it arrives after the plan step
 *       completed.
 *   C5  terminal task:done flips isWorking off on that same card.
 *
 * Regression target: session-247 live findings — LEGACY_UNKNOWN phantom
 * card, frozen THK verb, verbs swapping in place, done-before-synthesis.
 */
import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

function switchTo(conversationId: string) {
  act(() => {
    window.dispatchEvent(
      new CustomEvent("iris:conversation_switched", { detail: { conversation_id: conversationId } }),
    )
  })
}

/** The real conv-44/conv-51 wire sequence, condensed to one crawl round. */
function replayLiveTrace() {
  switchTo("conv-49")
  // identity established
  dispatch({
    type: "task:start",
    task_id: "fb24d28d-f98",
    card_id: "card_fb24d28d-f98",
    card_relation: "new",
    conversation_id: "conv-49",
    steps: [
      { id: "r1", description: "Search web for latest breakthroughs", status: "pending", toolName: null },
    ],
    total_steps: 1,
    origin: "initial",
  })
  // runtime resolver picked the tool
  dispatch({ type: "tool:call", card_id: "card_fb24d28d-f98", conversation_id: "conv-49", step_number: 1, tool_name: "crawler_query" })
  // crawler phases arrive CARD-LESS (tool_bridge forwards conversation_id only)
  dispatch({ type: "task:progress", conversation_id: "conv-49", description: "Searching for sources", action: "Searching for sources", phase: "searching", phase_sequence: 1 })
  dispatch({ type: "task:progress", conversation_id: "conv-49", description: "Reading Quantum journal paper", action: "Reading Quantum journal paper (1/4)", update_step: true, detail: "Quantum journal", detail_url: "https://quantum-journal.org/", detail_progress: "1/4", phase: "fetching", phase_sequence: 2 })
  dispatch({ type: "task:progress", conversation_id: "conv-49", description: "Reading Physics World", action: "Reading Physics World (2/4)", update_step: true, detail: "Physics World", detail_url: "https://physicsworld.com/", detail_progress: "2/4", phase: "fetching", phase_sequence: 2 })
  dispatch({ type: "task:progress", conversation_id: "conv-49", description: "Extracting content", action: "Extracting content", phase: "extracting", phase_sequence: 3 })
  dispatch({ type: "task:progress", conversation_id: "conv-49", description: "Citing sources", action: "Citing sources", phase: "citing", phase_sequence: 5 })
  // step completes
  dispatch({ type: "tool:result", card_id: "card_fb24d28d-f98", conversation_id: "conv-49", step_number: 1 })
  dispatch({ type: "task:progress", card_id: "card_fb24d28d-f98", conversation_id: "conv-49", step_done: true, step_id: "r1", step_number: 1, success: true })
  // LATE synthesis progress — arrives AFTER the step completed, CARD-LESS
  dispatch({ type: "task:progress", conversation_id: "conv-49", description: "Synthesizing answer", action: "Synthesizing answer", update_step: true, phase: "synthesizing", phase_sequence: 90 })
  // terminal
  dispatch({ type: "task:done", card_id: "card_fb24d28d-f98", conversation_id: "conv-49", outcome: "success", steps_completed: 1, total_steps: 1 })
}

describe("BEHAVIORAL CONTRACT — task card replays a real websearch trace", () => {
  it("C1: no legacy_unknown card is ever fabricated; exactly ONE card exists", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-49")
    replayLiveTrace()
    const cards = result.current.cards ?? []
    expect(cards.length).toBe(1)
    expect(cards[0].cardId).toBe("card_fb24d28d-f98")
    expect(cards.some((c) => String(c.cardId).startsWith("legacy"))).toBe(false)
  })

  it("C2: phase transitions append progressive nodes; previous phase done", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-49")
    replayLiveTrace()
    const steps = result.current.steps
    const descs = steps.map((s) => s.description)
    expect(descs).toContain("Searching for sources")
    expect(descs.some((d) => d.startsWith("Reading"))).toBe(true)
    expect(descs).toContain("Extracting content")
    expect(descs).toContain("Citing sources")

    const byDesc = (d: string) => steps.find((s) => s.description === d)!
    // earlier phases resolved when later ones arrived
    expect(byDesc("Searching for sources").status).toBe("done")
    expect(byDesc("Extracting content").status).toBe("done")
    // the LAST phase stays working until the terminal event resolves it
    expect(byDesc("Citing sources").status === "working" || byDesc("Citing sources").status === "done").toBe(true)
  })

  it("C3: per-page frames update detail without duplicating nodes", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-49")
    replayLiveTrace()
    const readNodes = result.current.steps.filter((s) => s.description.startsWith("Reading"))
    // both page frames landed on ONE progressive node, not two
    expect(readNodes.length).toBe(1)
  })

  it("C4: late synthesis progress attaches to the SAME card — no phantom", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-49")
    replayLiveTrace()
    const cards = result.current.cards ?? []
    expect(cards.length).toBe(1)
    const synthNode = cards[0].steps.find((s) => s.id.startsWith("phase-synthesizing"))
    expect(synthNode).toBeDefined()
  })

  it("C5: task:done terminates the card", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-49")
    replayLiveTrace()
    const cards = result.current.cards ?? []
    expect(cards[0].isWorking).toBe(false)
  })

  it("C6: split-graft children appear in semantic order after a revision start", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-49")
    replayLiveTrace()
    // a verify_failed graft revises the plan mid-run (real payload shape)
    dispatch({
      type: "task:start",
      task_id: "fb24d28d-f98",
      card_id: "card_fb24d28d-f98",
      card_relation: "continues",
      conversation_id: "conv-49",
      origin: "sub_loop_split",
      steps: [
        { id: "r1", description: "Search web for latest breakthroughs", status: "done", toolName: "crawler_query", stepNumber: 1 },
        { id: "r1_s1", description: "child extract", status: "working", toolName: "crawler_query", stepNumber: 1 },
      ],
      total_steps: 2,
    })
    const steps = result.current.steps
    // original anchor first, then children — insertion accidents cannot
    // reorder numbered rows ahead of unnumbered anchors
    expect(steps[0].id).toBe("r1")
    expect(steps.some((s) => s.id === "r1_s1")).toBe(true)
  })

  it("UNIVERSALITY: a code-task trace (no crawl phases) grows NO phase nodes — only the terminal SYNTH", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-code")
    // DER implement task: two run_command/write steps, no crawler involvement.
    dispatch({
      type: "task:start",
      task_id: "t-code",
      card_id: "card_code-1",
      card_relation: "new",
      conversation_id: "conv-code",
      steps: [
        { id: "c1", description: "Run the test suite", status: "pending", toolName: null },
        { id: "c2", description: "Summarize results and commit fix", status: "pending", toolName: null },
      ],
      total_steps: 2,
    })
    dispatch({ type: "tool:call", card_id: "card_code-1", conversation_id: "conv-code", step_number: 1, tool_name: "run_command" })
    dispatch({ type: "tool:result", card_id: "card_code-1", conversation_id: "conv-code", step_number: 1 })
    dispatch({ type: "task:progress", card_id: "card_code-1", conversation_id: "conv-code", step_done: true, step_id: "c1", success: true })
    dispatch({ type: "tool:call", card_id: "card_code-1", conversation_id: "conv-code", step_number: 2, tool_name: "write_file" })
    dispatch({ type: "tool:result", card_id: "card_code-1", conversation_id: "conv-code", step_number: 2 })
    dispatch({ type: "task:progress", card_id: "card_code-1", conversation_id: "conv-code", step_done: true, step_id: "c2", success: true })
    // terminal synthesis (ALL DER tasks emit this)
    dispatch({ type: "task:progress", conversation_id: "conv-code", description: "Synthesizing answer", action: "Synthesizing answer", update_step: true, phase: "synthesizing", phase_sequence: 90 })
    dispatch({ type: "task:done", card_id: "card_code-1", conversation_id: "conv-code", outcome: "success" })

    const cards = result.current.cards ?? []
    expect(cards.length).toBe(1)
    const steps = cards[0].steps
    // no crawl-phase nodes fabricated for a non-crawl task
    expect(steps.some((s) => s.id.startsWith("phase-searching"))).toBe(false)
    expect(steps.some((s) => s.id.startsWith("phase-fetching"))).toBe(false)
    // exactly one synthesis node, attached to the same card
    expect(steps.filter((s) => s.id === "phase-synthesizing")).toHaveLength(1)
    expect(cards[0].isWorking).toBe(false)
  })
})
