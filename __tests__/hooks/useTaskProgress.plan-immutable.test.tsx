import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

describe("useTaskProgress — plan immutability (REQ-2 AC1)", () => {
  it("task:progress with update_step preserves description byte-identical and writes activeDetail", () => {
    const { result } = renderHook(() => useTaskProgress())

    // Start a task with a plan step.
    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "s1", description: "Search for recent Python 3.13 features", status: "pending" },
      ],
      total_steps: 1,
    })

    // Mark it working so the update_step branch finds a working step.
    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })

    const planText = result.current.steps[0].description

    // Emit live progress — this must NOT overwrite description.
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading example.com (1/5)",
      detail: "example.com",
      detail_progress: "1/5",
    })

    // description is byte-identical.
    expect(result.current.steps[0].description).toBe(planText)
    expect(result.current.steps[0].description).toBe("Search for recent Python 3.13 features")

    // activeDetail is written with the structured detail field.
    expect(result.current.steps[0].activeDetail).toBe("example.com")
    expect(result.current.steps[0].activeProgress).toBe("1/5")

    // A second progress update rotates activeDetail without touching description.
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading example.org (2/5)",
      detail: "example.org",
      detail_progress: "2/5",
    })

    expect(result.current.steps[0].description).toBe("Search for recent Python 3.13 features")
    expect(result.current.steps[0].activeDetail).toBe("example.org")
    expect(result.current.steps[0].activeProgress).toBe("2/5")
  })

  it("tool:result clears activeDetail (REQ-2 AC3)", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t2",
      steps: [
        { id: "s1", description: "Search web for results", status: "pending" },
      ],
      total_steps: 1,
    })

    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })

    // Set live progress.
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading example.com (1/5)",
      detail: "example.com",
      detail_progress: "1/5",
    })

    expect(result.current.steps[0].activeDetail).toBe("example.com")

    // Terminal transition clears it.
    dispatch({ type: "tool:result", step_number: 1, result_summary: "found 3 pages" })

    expect(result.current.steps[0].activeDetail).toBeUndefined()
    expect(result.current.steps[0].activeProgress).toBeUndefined()
    expect(result.current.steps[0].description).toBe("Search web for results")
  })

  it("task:done clears all activeDetail from any step still carrying it (REQ-2 AC3)", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t3",
      steps: [
        { id: "s1", description: "Step one", status: "pending" },
        { id: "s2", description: "Step two", status: "pending" },
      ],
      total_steps: 2,
    })

    dispatch({ type: "tool:call", step_number: 1, tool_name: "search" })
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Searching...",
      detail: "query-results",
      detail_progress: "1/1",
    })

    // task:done must strip live detail from all steps.
    dispatch({ type: "task:done", outcome: "success" })

    for (const step of result.current.steps) {
      expect(step.activeDetail).toBeUndefined()
      expect(step.activeProgress).toBeUndefined()
    }
  })
})
