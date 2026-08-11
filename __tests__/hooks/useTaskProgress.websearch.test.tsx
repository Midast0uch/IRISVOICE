import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

describe("useTaskProgress â€” websearch live card updates (pin_517dfcbda150)", () => {
  it("F3: step_done matches plan steps by step_id (ids like r1)", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "r1", description: "Search the web", status: "pending", toolName: null },
      ],
      total_steps: 1,
    })

    // Plan steps carry planner ids (r1), NOT der-N â€” the old lookup never
    // matched, so the step stayed "working" for the whole task.
    dispatch({
      type: "task:progress",
      step_done: true,
      step_id: "r1",
      step_number: 1,
      description: "Search the web",
      success: true,
    })

    expect(result.current.steps[0].status).toBe("done")
  })

  it("F2: add_step with distinct step_ids appends BOTH split children", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "r1", description: "Search the web", status: "pending", toolName: null },
      ],
      total_steps: 1,
    })

    // A verify_failed split produces children that share the parent's
    // step_number but carry unique step_ids (parent_s{i}). The old der-N key
    // made them collide and silently dropped every child after the first.
    dispatch({
      type: "task:progress",
      add_step: true,
      step_id: "r1_s1",
      step_number: 1,
      description: "child a",
      tool_name: "crawler_query",
    })
    dispatch({
      type: "task:progress",
      add_step: true,
      step_id: "r1_s2",
      step_number: 1,
      description: "child b",
      tool_name: "crawler_query",
    })

    expect(result.current.steps).toHaveLength(3)
    const children = result.current.steps.slice(1).map((s) => s.description)
    expect(children).toEqual(["child a", "child b"])
  })

  it("F1: update_step surfaces detail_url on the working step", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "r1", description: "Search web", status: "pending", toolName: null },
      ],
      total_steps: 1,
    })
    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })

    // The crawler streams one page event per URL; detail_url is the saved URL.
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading Python 3.13 docs",
      detail: "Reading Python 3.13 docs",
      detail_url: "https://docs.python.org/3/whatsnew/3.13.html",
      detail_progress: "2/5",
    })

    const s = result.current.steps[0]
    expect(s.activeDetail).toBe("Reading Python 3.13 docs")
    expect(s.url).toBe("https://docs.python.org/3/whatsnew/3.13.html")
    expect(s.activeProgress).toBe("2/5")
    // The plan text is never destroyed by live detail.
    expect(s.description).toBe("Search web")
  })

  it("step_done clears the live url along with the detail", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        { id: "r1", description: "Search web", status: "pending", toolName: null },
      ],
      total_steps: 1,
    })
    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading A",
      detail: "Reading A",
      detail_url: "https://a.com",
    })
    expect(result.current.steps[0].url).toBe("https://a.com")

    dispatch({
      type: "task:progress",
      step_done: true,
      step_id: "r1",
      step_number: 1,
      success: true,
    })

    const s = result.current.steps[0]
    expect(s.status).toBe("done")
    expect(s.url).toBeUndefined()
    expect(s.activeDetail).toBeUndefined()
  })
})
