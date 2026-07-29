import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

describe("useTaskProgress — tool name resolution (REQ-3 AC1)", () => {
  it("tool:call overwrites a pre-resolution toolName with the resolved value", () => {
    const { result } = renderHook(() => useTaskProgress())

    // Start a task where the planner guessed a generic tool name.
    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "s1", description: "Search for Python 3.13 features", status: "pending", toolName: "search" },
        { id: "s2", description: "Summarize findings", status: "pending", toolName: "draft" },
      ],
      total_steps: 2,
    })

    // Pre-resolution toolName is visible.
    expect(result.current.steps[0].toolName).toBe("search")

    // DER resolves the actual tool and emits tool:call with the real name.
    dispatch({
      type: "tool:call",
      step_number: 1,
      tool_name: "crawler_query",
    })

    // The card now shows the resolved tool.
    expect(result.current.steps[0].toolName).toBe("crawler_query")
  })

  it("missing tool_name does NOT clear an already-resolved toolName", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t2",
      steps: [
        { id: "s1", description: "Search web", status: "pending" },
      ],
      total_steps: 1,
    })

    // Resolve the tool.
    dispatch({
      type: "tool:call",
      step_number: 1,
      tool_name: "crawler_query",
    })
    expect(result.current.steps[0].toolName).toBe("crawler_query")

    // A second tool:call WITHOUT tool_name — must NOT clear the existing one.
    dispatch({
      type: "tool:call",
      step_number: 1,
      // no tool_name
    })
    expect(result.current.steps[0].toolName).toBe("crawler_query")
  })

  it("tool:call marks the step as working and sets planTitle", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t3",
      steps: [
        { id: "s1", description: "Research topic", status: "pending" },
      ],
      total_steps: 1,
    })

    dispatch({
      type: "tool:call",
      step_number: 1,
      tool_name: "crawler_query",
    })

    expect(result.current.steps[0].status).toBe("working")
    // planTitle is set from the TOOL_TITLES map.
    expect(result.current.planTitle).toBe("WebCrawl")
  })
})
