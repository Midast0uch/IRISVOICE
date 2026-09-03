
import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

// Replays a synthetic (but representative) two-step websearch trace:
// plan -> tool resolution -> page-by-page progress -> results -> done.
// This is the "replayed websearch trace" the design.md harness names.
function replayWebsearchTrace() {
  const { result } = renderHook(() => useTaskProgress())
  dispatch({
    type: "task:start",
    task_id: "harness-trace",
    steps: [
      { id: "s1", description: "Search for recent Python 3.13 release notes", status: "pending" },
      { id: "s2", description: "Summarize findings into a report", status: "pending" },
    ],
    total_steps: 2,
  })
  const plan = result.current.steps.map((s: any) => s.description)

  dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
  dispatch({
    type: "task:progress", update_step: true,
    description: "Reading example.com (1/2)", detail: "example.com", detail_progress: "1/2",
  })
  dispatch({
    type: "task:progress", update_step: true,
    description: "Reading example.org (2/2)", detail: "example.org", detail_progress: "2/2",
  })
  dispatch({ type: "tool:result", step_number: 1, result_summary: "Found relevant docs" })

  dispatch({ type: "tool:call", step_number: 2, tool_name: "summarize_tool" })
  dispatch({ type: "tool:result", step_number: 2, result_summary: "Report drafted" })

  dispatch({ type: "task:done", outcome: "success" })
  return { result, plan }
}

describe("validate_display_coherence harness replay", () => {
  it("assertion 3: step description byte-identical at start and end of a replayed trace", () => {
    const { result, plan } = replayWebsearchTrace()
    result.current.steps.forEach((s: any, i: number) => {
      expect(s.description).toBe(plan[i])
    })
  })

  it("assertion 4: every executed step shows a resolved tool name, never a placeholder or bare Step N", () => {
    const { result } = replayWebsearchTrace()
    const placeholders = new Set(["tool", "direct", "unknown", ""])
    result.current.steps.forEach((s: any) => {
      expect(s.toolName).toBeTruthy()
      expect(placeholders.has((s.toolName || "").toLowerCase())).toBe(false)
      expect(/^step\s*\d+$/i.test(s.description || "")).toBe(false)
    })
  })

  it("assertion 5: detail is empty on every non-working step", () => {
    const { result } = replayWebsearchTrace()
    result.current.steps.forEach((s: any) => {
      if (s.status !== "working") {
        expect(s.activeDetail == null || s.activeDetail === "").toBe(true)
      }
    })
  })
})
