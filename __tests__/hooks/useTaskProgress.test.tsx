import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

describe("useTaskProgress", () => {
  it("starts on task:start and tracks steps", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "t1",
      description: "do",
      mode: "agentic",
      steps: [
        { id: "s1", description: "a", status: "pending" },
        { id: "s2", description: "b", status: "pending" },
      ],
      total_steps: 2,
    })
    expect(result.current.isWorking).toBe(true)
    expect(result.current.totalSteps).toBe(2)
    expect(result.current.steps.length).toBe(2)
    expect(result.current.mode).toBe("agentic")
  })

  it("marks step working then done and increments currentStep", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "s1", description: "a", status: "pending" },
        { id: "s2", description: "b", status: "pending" },
      ],
      total_steps: 2,
    })
    dispatch({ type: "tool:call", step_number: 1 })
    expect(result.current.steps[0].status).toBe("working")
    dispatch({ type: "tool:result", step_number: 1, result_summary: "ok" })
    expect(result.current.steps[0].status).toBe("done")
    expect(result.current.currentStep).toBe(1)
  })

  it("clears working flag on task:done", () => {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [{ id: "s1", description: "a", status: "pending" }],
      total_steps: 1,
    })
    dispatch({ type: "task:done", outcome: "success" })
    expect(result.current.isWorking).toBe(false)
  })

  it("bounds steps at 50", () => {
    const { result } = renderHook(() => useTaskProgress())
    const many = Array.from({ length: 60 }, (_, i) => ({
      id: `s${i}`,
      description: `d${i}`,
      status: "pending",
    }))
    dispatch({ type: "task:start", task_id: "t1", steps: many, total_steps: 60 })
    expect(result.current.steps.length).toBe(50)
  })
})