/**
 * BEHAVIORAL — the card says what each row actually did.
 *
 * specs/der-ground-truth/ REQ-21 (T34/T35). BT-GT-14 / CT-GT-9.
 *
 * The user's report: the aesthetic is right, the information density is what
 * undersells it. `pin_587a3e612558` item 5 named the mechanism — "only TWO step
 * nodes had inline summary (activeDetail); others blank" — because per-page
 * detail targeted whichever row was newest-and-working, and a phase going done
 * had its detail cleared outright.
 *
 * REQ-21 AC6 is explicit that this is NOT a restyling: palette, chassis and the
 * Liquid Ink visual language are untouched. These tests are about WHAT is
 * surfaced, never how it looks.
 */
import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress, boundedSummary } from "@/hooks/useTaskProgress"

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

function replayPhases(conv: string) {
  switchTo(conv)
  dispatch({
    type: "task:start",
    task_id: "t-d",
    card_id: `card_${conv}`,
    card_relation: "new",
    conversation_id: conv,
    steps: [{ id: "s1", description: "Research the topic", status: "pending", stepNumber: 1, seq: 1 }],
    total_steps: 1,
    origin: "initial",
  })
  dispatch({
    type: "task:progress", conversation_id: conv,
    description: "Searching for sources", action: "Searching for sources",
    phase: "searching", phase_sequence: 1, seq: 2,
    update_step: true, detail: "3 queries issued",
  })
  dispatch({
    type: "task:progress", conversation_id: conv,
    description: "Reading pages", action: "Reading pages",
    phase: "fetching", phase_sequence: 2, seq: 3,
    update_step: true, detail: "Quantum journal", detail_url: "https://quantum-journal.org/", detail_progress: "1/4",
  })
  dispatch({
    type: "task:progress", conversation_id: conv,
    description: "Extracting content", action: "Extracting content",
    phase: "extracting", phase_sequence: 3, seq: 4,
    update_step: true, detail: "44 chunks",
  })
}

describe("BT-GT-14 — every row keeps a record of what it did", () => {
  it("a completed phase row retains its detail as a summary instead of going blank", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayPhases("conv-den1")
    const searching = result.current.steps.find((s) => s.id === "phase-searching")!
    expect(searching.status).toBe("done")
    // Pre-T34 this was cleared outright, leaving the row blank.
    expect(searching.resultPreview).toBe("3 queries issued")
  })

  it("more than two rows carry information — the reported symptom is gone", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayPhases("conv-den2")
    const informative = result.current.steps.filter(
      (s) => Boolean(s.activeDetail) || Boolean(s.resultPreview),
    )
    // Three phase rows all did something and all say so.
    expect(informative.length).toBeGreaterThanOrEqual(3)
  })

  it("a finished row stops advertising a page it is no longer reading", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayPhases("conv-den3")
    const fetching = result.current.steps.find((s) => s.id === "phase-fetching")!
    expect(fetching.status).toBe("done")
    // REQ-21 AC3: live fields clear even though the summary is retained.
    expect(fetching.activeDetail).toBeUndefined()
    expect(fetching.url).toBeUndefined()
    expect(fetching.resultPreview).toBe("Quantum journal")
  })

  it("detail lands on the row that OWNS it, not on whichever is newest", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayPhases("conv-den4")
    // A late per-page frame for the ALREADY-PAST fetching phase must attribute
    // to fetching — pre-T34 it would have landed on the newest working row.
    dispatch({
      type: "task:progress", conversation_id: "conv-den4",
      action: "Reading Physics World", phase: "fetching", phase_sequence: 2,
      update_step: true, detail: "Physics World", detail_progress: "2/4",
    })
    const fetching = result.current.steps.find((s) => s.id === "phase-fetching")!
    const extracting = result.current.steps.find((s) => s.id === "phase-extracting")!
    expect(fetching.activeDetail).toBe("Physics World")
    expect(extracting.activeDetail).not.toBe("Physics World")
  })
})

describe("REQ-21 AC4 — retained summary is bounded, and truncation is marked", () => {
  it("short text is kept verbatim", () => {
    expect(boundedSummary("hello")).toBe("hello")
  })
  it("empty stays undefined rather than becoming an empty placeholder", () => {
    expect(boundedSummary("")).toBeUndefined()
    expect(boundedSummary(undefined)).toBeUndefined()
  })
  it("long text is truncated WITH a marker — never silently", () => {
    const out = boundedSummary("x".repeat(500))!
    expect(out.length).toBeLessThanOrEqual(160)
    expect(out.endsWith("…")).toBe(true)
  })
})

describe("CT-GT-9 — phase verbs come from the phase, not from keyword guessing", () => {
  it("a phase row carries its phase for the whole of its life", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayPhases("conv-den5")
    // pin_587a3e612558 item 4 was FIXED before this spec (the verb derives from
    // PHASE_VERB[phase]). This pins it so it cannot silently regress to
    // matching keywords in the description — which is how "Fetching pages"
    // rendered a SEARCH verb on a READ row.
    for (const id of ["phase-searching", "phase-fetching", "phase-extracting"]) {
      const row = result.current.steps.find((s) => s.id === id)!
      expect(row.phase).toBe(id.replace("phase-", ""))
    }
  })

  it("the phase survives the row going done", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayPhases("conv-den6")
    const searching = result.current.steps.find((s) => s.id === "phase-searching")!
    expect(searching.status).toBe("done")
    expect(searching.phase).toBe("searching")
  })
})
