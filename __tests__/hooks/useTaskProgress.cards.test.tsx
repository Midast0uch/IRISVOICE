/**
 * T6 (REQ-3, REQ-4): the `Map<card_id, Card>` collection model.
 * Complements useTaskProgress.baseline.test.ts (which pins the legacy,
 * no-card_id fallback and the restore-on-switch behavior). This file covers
 * the backend-declared identity path: concurrent cards, continue-vs-new,
 * cross-conversation isolation, and the per-conversation bound.
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

describe("useTaskProgress — card collection (T6)", () => {
  it("two concurrent cards in the same conversation coexist — a 'new' relation never displaces the prior card (REQ-3 AC4)", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-1")

    dispatch({
      type: "task:start",
      task_id: "t1",
      card_id: "card-1",
      card_relation: "new",
      conversation_id: "conv-1",
      steps: [{ id: "a1", description: "first task", status: "pending" }],
      total_steps: 1,
    })
    dispatch({
      type: "task:start",
      task_id: "t2",
      card_id: "card-2",
      card_relation: "new",
      conversation_id: "conv-1",
      steps: [{ id: "b1", description: "second, unrelated task", status: "pending" }],
      total_steps: 1,
    })

    expect(result.current.cards).toHaveLength(2)
    expect(result.current.cards.map((c) => c.cardId)).toEqual(["card-1", "card-2"])
    expect(result.current.cards[0].steps.map((s) => s.id)).toEqual(["a1"])
    expect(result.current.cards[1].steps.map((s) => s.id)).toEqual(["b1"])
  })

  it("'continues' extends the existing card by card_id instead of adding a second one (REQ-3 AC3)", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-1")

    dispatch({
      type: "task:start",
      task_id: "t1",
      card_id: "card-1",
      card_relation: "new",
      conversation_id: "conv-1",
      steps: [{ id: "a1", description: "step one", status: "pending" }],
      total_steps: 1,
    })
    dispatch({ type: "tool:call", card_id: "card-1", conversation_id: "conv-1", step_number: 1, tool_name: "read_file" })

    // Revised plan for the SAME card_id, relation "continues" — a sub-loop
    // split or a refined plan, not a new intent.
    dispatch({
      type: "task:start",
      task_id: "t1-revised",
      card_id: "card-1",
      card_relation: "continues",
      conversation_id: "conv-1",
      steps: [
        { id: "a1", description: "step one (revised)", status: "pending" },
        { id: "a2", description: "newly discovered step", status: "pending" },
      ],
      total_steps: 2,
    })

    expect(result.current.cards).toHaveLength(1)
    const card = result.current.cards[0]
    expect(card.cardId).toBe("card-1")
    // Live status preserved through the merge, exactly like the legacy path.
    expect(card.steps.find((s) => s.id === "a1")?.status).toBe("working")
    expect(card.steps.find((s) => s.id === "a1")?.description).toBe("step one (revised)")
    expect(card.steps.find((s) => s.id === "a2")).toBeDefined()
  })

  it("a card from conversation A never shows in conversation B (REQ-4 AC3)", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-A")
    dispatch({
      type: "task:start",
      task_id: "t1",
      card_id: "card-A1",
      card_relation: "new",
      conversation_id: "conv-A",
      steps: [{ id: "a1", description: "only in A", status: "pending" }],
      total_steps: 1,
    })
    expect(result.current.cards).toHaveLength(1)

    switchTo("conv-B")
    expect(result.current.cards).toHaveLength(0)
    expect(result.current.cards.some((c) => c.cardId === "card-A1")).toBe(false)

    // A background event for A arriving while B is being viewed must not
    // leak into B's view either (REQ-4 edge case).
    dispatch({
      type: "tool:call",
      card_id: "card-A1",
      conversation_id: "conv-A",
      step_number: 1,
      tool_name: "read_file",
    })
    expect(result.current.cards).toHaveLength(0)

    switchTo("conv-A")
    expect(result.current.cards).toHaveLength(1)
    expect(result.current.cards[0].steps[0].status).toBe("working")
  })

  it("switching away mid-execution and back restores the card with live progress intact (REQ-4 AC2/AC5 edge case)", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-1")
    dispatch({
      type: "task:start",
      task_id: "t1",
      card_id: "card-1",
      card_relation: "new",
      conversation_id: "conv-1",
      steps: [{ id: "a1", description: "step", status: "pending" }],
      total_steps: 1,
    })
    dispatch({ type: "tool:call", card_id: "card-1", conversation_id: "conv-1", step_number: 1, tool_name: "crawler_query" })

    switchTo("conv-2")
    expect(result.current.cards).toHaveLength(0)

    switchTo("conv-1")
    expect(result.current.cards).toHaveLength(1)
    expect(result.current.isWorking).toBe(true)
    expect(result.current.steps[0].status).toBe("working")
  })

  it("the per-conversation card bound evicts the OLDEST card whole, never a partial one", () => {
    const { result } = renderHook(() => useTaskProgress())
    switchTo("conv-1")

    // The cap is internal; drive it well past any reasonable size to prove
    // eviction happens and stays whole-card (a partial/malformed card would
    // show a truthy `steps` on an id that should be gone entirely).
    const CARDS_TO_CREATE = 40
    for (let i = 0; i < CARDS_TO_CREATE; i++) {
      dispatch({
        type: "task:start",
        task_id: `t${i}`,
        card_id: `card-${i}`,
        card_relation: "new",
        conversation_id: "conv-1",
        steps: [{ id: `s${i}`, description: `task ${i}`, status: "pending" }],
        total_steps: 1,
      })
    }

    // Bounded: fewer cards are kept than were created.
    expect(result.current.cards.length).toBeLessThan(CARDS_TO_CREATE)
    expect(result.current.cards.length).toBeGreaterThan(0)

    // The oldest card is gone WHOLE — no trace of its id or its step.
    expect(result.current.cards.some((c) => c.cardId === "card-0")).toBe(false)
    // The newest card survives intact.
    const last = result.current.cards[result.current.cards.length - 1]
    expect(last.cardId).toBe(`card-${CARDS_TO_CREATE - 1}`)
    expect(last.steps).toHaveLength(1)
  })
})
