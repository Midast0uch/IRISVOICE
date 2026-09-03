import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useAgentQuestion } from "@/hooks/useAgentQuestion"

/**
 * FIXTURE INPUT CHANGED — CALLED OUT EXPLICITLY (REQ-16/T18, 2026-08-25).
 * No original assertion is weakened; three cases are ADDED.
 *
 * `ask()` used to dispatch `{ questionId: "q1" }` — camelCase, and no `text`.
 * Production never sends that. The real payload is snake_case with text
 * (`{ question_id, text, options?, allow_other?, timeout_seconds? }`), which is
 * what the backend emits and what chat-view.tsx:1405 reads. The old fixture
 * matched the HOOK'S OWN BUG (it read `detail?.questionId`, so `questionId` was
 * always undefined against real traffic) rather than the wire format, so this
 * suite passed while the hook could not have worked in the app.
 *
 * The fixture now sends what production sends. The hook accepts BOTH spellings
 * so a rename on either side cannot silently reintroduce the mismatch, and
 * that tolerance is pinned below rather than left implicit.
 */
function ask(detail: Record<string, unknown> = { question_id: "q1", text: "Which one?" }) {
  act(() =>
    window.dispatchEvent(new CustomEvent("iris:question_ask", { detail }))
  )
}
function answered() {
  act(() =>
    window.dispatchEvent(new CustomEvent("iris:question_answered"))
  )
}
function timeout() {
  act(() =>
    window.dispatchEvent(new CustomEvent("iris:question_timeout"))
  )
}

describe("useAgentQuestion", () => {
  it("sets pending on ask", () => {
    const { result } = renderHook(() => useAgentQuestion())
    ask()
    expect(result.current.hasPendingQuestion).toBe(true)
    expect(result.current.questionId).toBe("q1")
  })

  it("clears on answered", () => {
    const { result } = renderHook(() => useAgentQuestion())
    ask()
    answered()
    expect(result.current.hasPendingQuestion).toBe(false)
  })

  it("clears on timeout", () => {
    const { result } = renderHook(() => useAgentQuestion())
    ask()
    timeout()
    expect(result.current.hasPendingQuestion).toBe(false)
  })

  // ── added with REQ-16: the hook now has to CARRY the question ───────────

  it("carries the text and options so the question can be answered outside ChatView", () => {
    const { result } = renderHook(() => useAgentQuestion())
    ask({
      question_id: "q9",
      text: "Which branch?",
      options: ["main", "develop"],
      allow_other: true,
    })
    expect(result.current.text).toBe("Which branch?")
    expect(result.current.options).toEqual(["main", "develop"])
    expect(result.current.allowOther).toBe(true)
  })

  it("accepts the camelCase spelling too", () => {
    // Tolerated on purpose: the snake_case/camelCase mismatch is exactly what
    // silently broke this hook once already.
    const { result } = renderHook(() => useAgentQuestion())
    ask({ questionId: "q2", text: "Either spelling" })
    expect(result.current.questionId).toBe("q2")
  })

  it("ignores an event with no id or no text", () => {
    // Nothing to answer without an id, nothing to show without text — the same
    // guard chat-view.tsx already applies. Rendering a dead prompt is worse
    // than rendering nothing.
    const { result } = renderHook(() => useAgentQuestion())
    ask({ question_id: "q3" })
    expect(result.current.hasPendingQuestion).toBe(false)
    ask({ text: "orphan question" })
    expect(result.current.hasPendingQuestion).toBe(false)
  })
})
