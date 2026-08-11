import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

/**
 * T24 (specs/long-horizon-der-execution REQ-14 AC3): pin the invariant that
 * live progress (update_step) writes ONLY activeDetail / activeProgress / url
 * and NEVER the plan `description` text (hooks/useTaskProgress.ts:377-398).
 *
 * Before this test the invariant held only by convention (comment at :377-381)
 * — a future edit that shoved `description: action` into the update_step
 * branch would destroy the visible plan text while every existing test stayed
 * green. This suite asserts the EXACT write-set: the step's other fields
 * (description, toolName, status, ...) must be value-identical across the
 * update.
 */
describe("useTaskProgress — update_step write-set (REQ-14 AC3 / T24)", () => {
  it("update_step mutates ONLY activeDetail/activeProgress/url — never description or any other step field", () => {
    const { result } = renderHook(() => useTaskProgress())

    // Start a plan whose step carries description + toolName + pending status.
    dispatch({
      type: "task:start",
      task_id: "t1",
      steps: [
        {
          id: "s1",
          description: "Search for recent Python 3.13 features",
          toolName: "crawler_query",
          status: "pending",
        },
      ],
      total_steps: 1,
    })
    // Mark it working so the update_step branch finds a working step.
    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })

    const before = result.current.steps[0]
    const beforeKeys = Object.keys(before).sort()

    // Live progress with the full structured payload.
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading example.com (1/5)",
      detail: "example.com",
      detail_progress: "1/5",
      detail_url: "https://example.com/page",
    })

    const step = result.current.steps[0]

    // The write-set: exactly these three fields are written...
    expect(step.activeDetail).toBe("example.com")
    expect(step.activeProgress).toBe("1/5")
    expect(step.url).toBe("https://example.com/page")

    // ...and NOTHING else changes value — description in particular stays
    // byte-identical (REQ-14 AC3).
    expect(step.description).toBe(before.description)
    expect(step.description).toBe("Search for recent Python 3.13 features")

    const mutated = new Set<string>()
    for (const key of new Set([...beforeKeys, ...Object.keys(step)])) {
      if (Object.is(step[key as keyof typeof step], before[key as keyof typeof before])) {
        continue
      }
      mutated.add(key)
    }
    expect([...mutated].sort()).toEqual(["activeDetail", "activeProgress", "url"])
    expect(step.status).toBe("working")
    expect(step.toolName).toBe("crawler_query")
  })

  it("update_step without detail falls back to the sentence — still never into description", () => {
    const { result } = renderHook(() => useTaskProgress())

    dispatch({
      type: "task:start",
      task_id: "t2",
      steps: [{ id: "s1", description: "Summarize the findings", status: "pending" }],
      total_steps: 1,
    })
    dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })

    const before = result.current.steps[0]

    // Emitters that predate the `detail` field send only the sentence; it must
    // land in activeDetail, never in description.
    dispatch({
      type: "task:progress",
      update_step: true,
      description: "Reading example.com (1/5)",
    })

    const step = result.current.steps[0]
    expect(step.activeDetail).toBe("Reading example.com (1/5)")
    expect(step.description).toBe(before.description)
    expect(step.description).toBe("Summarize the findings")
  })
})
