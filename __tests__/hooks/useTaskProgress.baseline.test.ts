/**
 * BASELINE — Wave 0, specs/task-card-v2-liquid-ink.
 * Original snapshot (2026-08-19) pinned the single-card model: one card,
 * wiped on `iris:new_conversation` / `iris:conversation_switched`, merged by
 * the `prev.turnId === d.task_id && prev.isWorking` heuristic, with no
 * `cards` collection and no `card_id` / `conversation_id` anywhere in the
 * returned shape.
 *
 * INVERTED BY T6 (landed 2026-08-19): `useTaskProgress` now holds a
 * `Map<card_id, Card>` SCOPED PER CONVERSATION. Tests 2a/2b and the final
 * test below are rewritten to assert the new behavior — restore-on-switch
 * instead of wipe-on-switch, and a `cards` collection driven by backend
 * `card_id` / `card_relation` / `conversation_id`. Tests 1, 3a and 3b are
 * UNCHANGED in substance: a payload with no `card_id` is the REQ-3 legacy
 * fallback, which is REQUIRED to keep reproducing exactly this merge/replace
 * heuristic — so what they assert is still true, only the assertion that
 * "there is no collection" is inverted into "the collection holds exactly
 * the one legacy card". This file remains the pin for both the legacy path
 * and the new multi-card path from here on.
 * Editing this file is sanctioned ONLY by T6, and that edit MUST be called
 * out in that task's report. This is that edit.
 * Inverted by: T6 (landed).
 */
import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

// Reuses the established harness from __tests__/hooks/useTaskProgress.test.tsx —
// renderHook + window.dispatchEvent of the CustomEvent.
function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

function fireWindowEvent(name: string, detail?: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(detail ? new CustomEvent(name, { detail }) : new Event(name))
  })
}

const EMPTY_PROGRESS = {
  isWorking: false,
  currentStep: 0,
  totalSteps: 0,
  steps: [],
  currentAction: undefined,
  planTitle: undefined,
  cards: [],
}

describe("useTaskProgress — BASELINE (legacy single-card fallback, unchanged)", () => {
  it("1. a legacy (no card_id) second task:start with a different task_id REPLACES, does not coexist — and the collection holds exactly that one card", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "A",
      steps: [{ id: "a1", description: "task A step", status: "pending" }],
      total_steps: 1,
    })
    expect(result.current.turnId).toBe("A")
    expect(result.current.steps.map((s) => s.id)).toEqual(["a1"])

    dispatch({
      type: "task:start",
      task_id: "B",
      steps: [{ id: "b1", description: "task B step", status: "pending" }],
      total_steps: 1,
    })

    // B replaced A entirely — no trace of A survives, in the derived
    // single-card fields OR the collection.
    expect(result.current.turnId).toBe("B")
    expect(result.current.steps.map((s) => s.id)).toEqual(["b1"])
    expect(result.current.steps.some((s) => s.id === "a1")).toBe(false)

    // T6: the collection exists and holds exactly the surviving legacy card.
    expect(result.current.cards).toHaveLength(1)
    expect(result.current.cards[0].turnId).toBe("B")
  })

  it("2a. switching away via iris:conversation_switched and back via iris:new_conversation RESTORES the in-flight card — the vanishing-card defect is fixed", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "A",
      steps: [{ id: "a1", description: "in flight", status: "pending" }],
      total_steps: 1,
    })
    expect(result.current.isWorking).toBe(true)

    // Move the view to a different conversation — the card is left behind
    // in its own conversation's map, not destroyed.
    fireWindowEvent("iris:conversation_switched", { conversation_id: "conv-other" })
    expect(result.current).toEqual(EMPTY_PROGRESS)

    // iris:new_conversation used to WIPE an in-flight task wholesale. It now
    // just returns the view to where the legacy card lives, RESTORING it.
    fireWindowEvent("iris:new_conversation")
    expect(result.current.isWorking).toBe(true)
    expect(result.current.cards).toHaveLength(1)
    expect(result.current.steps.map((s) => s.id)).toEqual(["a1"])
  })

  it("2b. iris:conversation_switched RESTORES a conversation's cards rather than wiping the newly-shown one — the vanishing-card defect is fixed", () => {
    const { result } = renderHook(() => useTaskProgress())
    // Establish conv-1 as the conversation being viewed BEFORE the task
    // starts — the realistic case (an existing conversation the user is
    // already looking at). A brand-new conversation's own race between
    // creation and its first task:start is a chat-view (T7) concern, not
    // this hook's.
    fireWindowEvent("iris:conversation_switched", { conversation_id: "conv-1" })
    dispatch({
      type: "task:start",
      task_id: "A",
      card_id: "card-A",
      conversation_id: "conv-1",
      card_relation: "new",
      steps: [{ id: "a1", description: "in flight", status: "pending" }],
      total_steps: 1,
    })
    expect(result.current.isWorking).toBe(true)

    // Switch away to a different conversation — conv-1's card must not
    // appear there (REQ-4 AC3).
    fireWindowEvent("iris:conversation_switched", { conversation_id: "conv-2" })
    expect(result.current.cards).toHaveLength(0)

    // Switch back — the card is RESTORED, not recreated from nothing.
    fireWindowEvent("iris:conversation_switched", { conversation_id: "conv-1" })
    expect(result.current.cards).toHaveLength(1)
    expect(result.current.cards[0].cardId).toBe("card-A")
    expect(result.current.isWorking).toBe(true)
  })

  it("3a. legacy MERGE branch — same task_id while isWorking && steps.length > 0: steps merge by id, live status preserved, description refreshed", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "A",
      steps: [
        { id: "s1", description: "original a", status: "pending" },
        { id: "s2", description: "original b", status: "pending" },
      ],
      total_steps: 2,
    })
    // Put a step in flight so prev.isWorking is true with steps present.
    dispatch({ type: "tool:call", step_number: 1, tool_name: "read_file" })
    expect(result.current.steps[0].status).toBe("working")

    // A revised plan snapshot arrives for the SAME task while it is working.
    dispatch({
      type: "task:start",
      task_id: "A",
      steps: [
        { id: "s1", description: "revised a", status: "pending" },
        { id: "s2", description: "revised b", status: "pending" },
        { id: "s3", description: "newly discovered", status: "pending" },
      ],
      total_steps: 3,
    })

    // Live status of s1 is PRESERVED (still "working"), not reset to "pending"
    // by the incoming snapshot.
    expect(result.current.steps.find((s) => s.id === "s1")?.status).toBe("working")
    // Description/toolName is REFRESHED from the new plan.
    expect(result.current.steps.find((s) => s.id === "s1")?.description).toBe("revised a")
    // The newly discovered step is present too.
    expect(result.current.steps.find((s) => s.id === "s3")).toBeDefined()
    // Still exactly one card — a merge never grows the collection.
    expect(result.current.cards).toHaveLength(1)
  })

  it("3b. legacy REPLACE branch — same task_id while NOT working: full replace, no merge", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "A",
      steps: [
        { id: "s1", description: "original a", status: "pending" },
        { id: "s2", description: "original b", status: "pending" },
      ],
      total_steps: 2,
    })
    dispatch({ type: "tool:call", step_number: 1, tool_name: "read_file" })
    expect(result.current.steps[0].status).toBe("working")

    // Task ends — isWorking becomes false.
    dispatch({ type: "task:done", outcome: "success" })
    expect(result.current.isWorking).toBe(false)

    // A second task:start for the SAME task_id arrives, but the previous run
    // is no longer "working" — this takes the full-replace path, not merge.
    dispatch({
      type: "task:start",
      task_id: "A",
      steps: [{ id: "s9", description: "unrelated fresh step", status: "pending" }],
      total_steps: 1,
    })

    // Observable difference from 3a: the old steps (s1, s2) are GONE, not
    // merged in — the replacement is total, and still exactly one card.
    expect(result.current.steps.map((s) => s.id)).toEqual(["s9"])
    expect(result.current.steps.some((s) => s.id === "s1")).toBe(false)
    expect(result.current.steps.some((s) => s.id === "s2")).toBe(false)
    expect(result.current.cards).toHaveLength(1)
  })

  it("T6: card_id / card_relation / conversation_id are now read, and drive the `cards` collection", () => {
    const { result } = renderHook(() => useTaskProgress())
    fireWindowEvent("iris:conversation_switched", { conversation_id: "conv-1" })
    dispatch({
      type: "task:start",
      task_id: "A",
      card_id: "card-1",
      card_relation: "new",
      conversation_id: "conv-1",
      steps: [{ id: "s1", description: "x", status: "pending" }],
      total_steps: 1,
    })

    expect(result.current).toHaveProperty("cards")
    expect(Object.keys(result.current)).toContain("cards")
    expect(result.current.cards).toHaveLength(1)
    expect(result.current.cards[0].cardId).toBe("card-1")
    expect(result.current.cards[0].conversationId).toBe("conv-1")
  })
})
