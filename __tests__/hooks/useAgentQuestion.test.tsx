import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useAgentQuestion } from "@/hooks/useAgentQuestion"

function ask() {
  act(() =>
    window.dispatchEvent(
      new CustomEvent("iris:question_ask", { detail: { questionId: "q1" } })
    )
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
})