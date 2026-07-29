import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

describe("useTaskProgress — detail cleared on all terminal transitions (REQ-2 AC3)", () => {
  // Shared setup: start a task, mark step working, set live progress.
  function setupWorkingStep() {
    const { result } = renderHook(() => useTaskProgress())
    dispatch({
      type: "task:start",
      task_id: "t",
      steps: [
        // step_done path searches for `der-{step_number}` id
        { id: "der-1", description: "Search web", status: "pending" },
      ],
      total_steps: 1,
    })
    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading example.com (1/5)",
      detail: "example.com",
      detail_progress: "1/5",
    })
    // Confirm detail is set before terminal.
    expect(result.current.steps[0].activeDetail).toBe("example.com")
    return result
  }

  it.each([
    ["tool:result", { type: "tool:result", step_number: 1, result_summary: "done" }],
    ["tool:error", { type: "tool:error", step_number: 1, error: "failed" }],
    ["step_done (via task:progress)", { type: "task:progress", step_done: true, step_number: 1, success: true }],
    ["task:done", { type: "task:done", outcome: "success" }],
  ])("%s clears activeDetail and activeProgress", (_label, event) => {
    const result = setupWorkingStep()

    dispatch(event)

    expect(result.current.steps[0].activeDetail).toBeUndefined()
    expect(result.current.steps[0].activeProgress).toBeUndefined()
  })
})
