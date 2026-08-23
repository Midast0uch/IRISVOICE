/**
 * BEHAVIORAL — row ORDER and progress COHERENCE.
 *
 * specs/der-ground-truth/ REQ-17 / REQ-18 (BT-GT-10, BT-GT-11). T29/T30.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The session-247 reducer suite replays a real trace and asserts a great deal
 * about the card — but **not one of its assertions checks ORDER**. C2 uses
 * `toContain` on descriptions (order-independent), C3 counts nodes, C4 finds a
 * node, C5 checks `isWorking`. C6 does assert order and passes only because the
 * two rows it compares COLLIDE on key 1, so a tie resolves to insertion order.
 *
 * So the suite was green while the live card rendered out of sequence, and the
 * counter and the orb ring drifted from the list. Nothing was testing the thing
 * that was broken. These are the assertions that would have caught it.
 *
 * Every test here fails against the pre-T28/T29 code: phase nodes carried no
 * ordering key, so they collapsed to MAX_SAFE_INTEGER and sorted to the end of
 * the card no matter when they happened.
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

/**
 * A run where a crawl phase genuinely happens BETWEEN two planner steps.
 *
 * The fixture is built so CHRONOLOGICAL order and PLANNER order genuinely
 * DISAGREE — that is the only shape that can catch the bug. Planner rows carry
 * `stepNumber` 1 and 2 (the planner's own numbering, which the real backend
 * sends and which REQ-17 AC5 keeps as a display concern). The phase opens
 * between them, so its backend key is 2 and step two's is 3.
 *
 * Pre-T28/T29 the phase row had NO key, collapsed to MAX_SAFE_INTEGER, and
 * rendered LAST: p1, p2, phase. Post-fix it renders where it happened:
 * p1, phase, p2. A fixture without `stepNumber` would tie every row and pass
 * either way on insertion order — which is exactly the accident that makes the
 * session-247 C6 assertion green while the live card is wrong.
 */
function replayInterleaved() {
  switchTo("conv-ord")
  dispatch({
    type: "task:start",
    task_id: "t-ord",
    card_id: "card_ord",
    card_relation: "new",
    conversation_id: "conv-ord",
    steps: [
      { id: "p1", description: "Plan step one", status: "pending", stepNumber: 1, seq: 1 },
      { id: "p2", description: "Plan step two", status: "pending", stepNumber: 2, seq: 3 },
    ],
    total_steps: 2,
    origin: "initial",
  })
  dispatch({ type: "task:progress", card_id: "card_ord", conversation_id: "conv-ord", step_done: true, step_id: "p1", success: true })
  // a phase opens AFTER step one and BEFORE step two — key 2 sits between them
  dispatch({
    type: "task:progress",
    conversation_id: "conv-ord",
    description: "Searching for sources",
    action: "Searching for sources",
    phase: "searching",
    phase_sequence: 1,
    seq: 2,
  })
  dispatch({
    type: "task:progress",
    conversation_id: "conv-ord",
    description: "Extracting content",
    action: "Extracting content",
    phase: "extracting",
    phase_sequence: 3,
    seq: 4,
  })
}

describe("BT-GT-10 — rows render in the order the work happened", () => {
  it("a phase row sorts between the planner rows it occurred between", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayInterleaved()
    const ids = result.current.steps.map((s) => s.id)
    // The whole point: `phase-searching` happened BETWEEN the planner rows and
    // must render between them. Pre-fix it had no key, collapsed to
    // MAX_SAFE_INTEGER, and was banished to the end: [p1, p2, phase, phase].
    expect(ids).toEqual(["p1", "phase-searching", "p2", "phase-extracting"])
  })

  it("the rendered order is exactly ascending by the backend key", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayInterleaved()
    const keys = result.current.steps.map((s) => s.seq ?? s.stepNumber ?? Number.MAX_SAFE_INTEGER)
    expect(keys).toEqual([...keys].sort((a, b) => a - b))
    // and no row is unkeyed — an unkeyed row is a contract violation (REQ-17 AC6),
    // not a row that quietly sinks to the bottom.
    expect(keys.every((k) => k !== Number.MAX_SAFE_INTEGER)).toBe(true)
  })

  it("distinct rows never share a key", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayInterleaved()
    const keys = result.current.steps.map((s) => s.seq)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it("a revision cannot renumber rows that already exist", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayInterleaved()
    const before = result.current.steps.find((s) => s.id === "p1")!.seq
    // a graft revises the plan mid-run, re-emitting p1 with its ORIGINAL key
    dispatch({
      type: "task:start",
      task_id: "t-ord",
      card_id: "card_ord",
      card_relation: "continues",
      conversation_id: "conv-ord",
      origin: "sub_loop_split",
      steps: [
        { id: "p1", description: "Plan step one", status: "done", stepNumber: 1, seq: 1 },
        { id: "p1_child", description: "graft child", status: "working", stepNumber: 1, seq: 5 },
      ],
      total_steps: 3,
    })
    const after = result.current.steps.find((s) => s.id === "p1")!.seq
    expect(after).toBe(before)
    const ids = result.current.steps.map((s) => s.id)
    expect(ids.indexOf("p1")).toBeLessThan(ids.indexOf("p1_child"))
  })
})

describe("BT-GT-11 — counter and ring stay coherent with the list", () => {
  it("the numerator never exceeds the denominator, at any point in the run", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-ord2")
    dispatch({
      type: "task:start",
      task_id: "t2",
      card_id: "card_ord2",
      card_relation: "new",
      conversation_id: "conv-ord2",
      steps: [{ id: "a", description: "one", status: "pending", seq: 1 }],
      total_steps: 1,
      origin: "initial",
    })
    const seen: Array<[number, number]> = []
    const record = () => seen.push([result.current.currentStep, result.current.totalSteps])
    record()
    for (const [i, phase] of ["searching", "fetching", "extracting", "citing"].entries()) {
      dispatch({
        type: "task:progress",
        conversation_id: "conv-ord2",
        description: phase,
        action: phase,
        phase,
        phase_sequence: i + 1,
        seq: i + 2,
      })
      record()
    }
    // `cur <= total` alone is TOO WEAK to catch this: pre-T30 the numerator
    // went STALE, and a stale numerator is still <= a growing denominator. The
    // assertion that bites is COHERENCE — the numerator must track the row the
    // list is actually showing as working. Pre-T30 the denominator grew on
    // every phase while the numerator sat still, and because the same value
    // drives the orb ring, the ring drifted with it.
    const steps = result.current.steps
    const workingIdx = steps.findIndex((st) => st.status === "working")
    const expected = workingIdx >= 0 ? workingIdx + 1 : steps.filter((st) => st.status === "done").length
    expect(result.current.currentStep).toBe(expected)
    for (const [cur, total] of seen) {
      expect(cur).toBeLessThanOrEqual(total)
    }
    // and it must have MOVED as rows were appended — a numerator frozen at its
    // task:start value is the exact defect.
    expect(seen[seen.length - 1][0]).toBeGreaterThan(seen[0][0])
  })

  it("the denominator counts exactly the rows the list renders", () => {
    const { result } = renderHook(() => useTaskProgress())
    replayInterleaved()
    expect(result.current.totalSteps).toBe(result.current.steps.length)
  })

  it("the denominator never shrinks as work is discovered", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-ord3")
    dispatch({
      type: "task:start",
      task_id: "t3",
      card_id: "card_ord3",
      card_relation: "new",
      conversation_id: "conv-ord3",
      steps: [{ id: "z", description: "one", status: "pending", seq: 1 }],
      total_steps: 1,
      origin: "initial",
    })
    let high = result.current.totalSteps
    for (const [i, phase] of ["searching", "extracting"].entries()) {
      dispatch({
        type: "task:progress",
        conversation_id: "conv-ord3",
        description: phase,
        action: phase,
        phase,
        phase_sequence: i + 1,
        seq: i + 2,
      })
      expect(result.current.totalSteps).toBeGreaterThanOrEqual(high)
      high = result.current.totalSteps
    }
  })
})
