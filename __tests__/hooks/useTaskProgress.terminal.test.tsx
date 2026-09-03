/**
 * A finished task must not still look like it is working.
 *
 * Live report, 2026-08-11: "the agent is stuck in the wrk phase after the search
 * ended". `task:done` cleared `isWorking` and stripped each step's activeDetail,
 * but left `status: "working"` untouched — and TaskListCard renders a working
 * step's Xur indicator indefinitely. A step whose completion event never matched
 * (the step_id mismatch in pin_517dfcbda150 is one way that happens) therefore
 * span forever after the run had finished.
 *
 * The resolution has to be HONEST, which is the real content of these tests:
 * the backend already sends `failed_steps` on the terminal event and the card
 * ignored it, so a failed step read as finished; and a step that never started
 * must not be marked done just to stop it spinning.
 */
import { act, renderHook } from "@testing-library/react"

import { useTaskProgress } from "@/hooks/useTaskProgress"

/**
 * One act() PER event. The hook reads its previous state from a ref that is
 * only refreshed on render, so several dispatches batched into a single act()
 * would all observe the initial (empty) state — every assertion would then pass
 * or fail for the wrong reason, and the "no working steps" check in particular
 * would pass vacuously against zero steps.
 */
function emit(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

function startTask(steps: Array<{ id: string; description: string }>) {
  emit({
    type: "task:start",
    task_id: "turn-1",
    plan_title: "Research party builds",
    steps: steps.map((s, i) => ({
      id: s.id,
      description: s.description,
      status: "pending",
      stepNumber: i + 1,
    })),
    total_steps: steps.length,
  })
}

const STEPS = [
  { id: "s1", description: "search the web" },
  { id: "s2", description: "summarize the findings" },
]

describe("useTaskProgress — terminal event resolves every step", () => {
  it("a step left working when the task succeeds completes, and stops spinning", () => {
    const { result } = renderHook(() => useTaskProgress())

    startTask(STEPS)
    // s1 goes to work and never reports completion — the lost-terminal-event
    // case that produced the live symptom.
    // `tool:call` is what actually moves a step to "working" (a bare
    // task:progress only carries live detail), so this is the real in-flight
    // state the terminal event has to resolve.
    emit({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
    emit({ type: "task:done", task_id: "turn-1", outcome: "success",
           steps_completed: 2, total_steps: 2 })

    // Non-vacuity: "no working steps" is trivially true of an empty list, and an
    // empty list is exactly what a mis-shaped task:start would produce.
    expect(result.current.steps).toHaveLength(2)
    expect(result.current.isWorking).toBe(false)
    const working = result.current.steps.filter((s) => s.status === "working")
    expect(working).toHaveLength(0)
  })

  it("a step the backend reported as FAILED is shown failed, not finished", () => {
    const { result } = renderHook(() => useTaskProgress())

    startTask(STEPS)
    // `tool:call` is what actually moves a step to "working" (a bare
    // task:progress only carries live detail), so this is the real in-flight
    // state the terminal event has to resolve.
    emit({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
    emit({
      type: "task:done",
      task_id: "turn-1",
      outcome: "success",
      failed_steps: [{ step_id: "s1", description: "search the web" }],
    })

    const s1 = result.current.steps.find((s) => s.id === "s1")
    expect(s1?.status).toBe("fail")
  })

  it("a step that never ran is skipped, never silently marked done", () => {
    const { result } = renderHook(() => useTaskProgress())

    startTask(STEPS)
    // s2 never starts.
    emit({ type: "task:progress", step_id: "s1", step_done: true, success: true })
    emit({ type: "task:done", task_id: "turn-1", outcome: "success" })

    const s2 = result.current.steps.find((s) => s.id === "s2")
    expect(s2?.status).toBe("skipped")
    expect(s2?.status).not.toBe("done")
  })

  it("on a FAILED task an unfinished step becomes an error, not a success", () => {
    const { result } = renderHook(() => useTaskProgress())

    startTask(STEPS)
    // `tool:call` is what actually moves a step to "working" (a bare
    // task:progress only carries live detail), so this is the real in-flight
    // state the terminal event has to resolve.
    emit({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
    emit({ type: "task:fail", task_id: "turn-1", outcome: "failed" })

    const s1 = result.current.steps.find((s) => s.id === "s1")
    expect(s1?.status).toBe("error")
    expect(s1?.status).not.toBe("done")
  })

  it("an already-completed step keeps its status and loses its live detail", () => {
    const { result } = renderHook(() => useTaskProgress())

    startTask(STEPS)
    emit({ type: "task:progress", step_id: "s1", step_done: true, success: true })
    emit({ type: "task:progress", step_id: "s2", detail: "example.com",
           detail_url: "https://example.com" })
    emit({ type: "task:done", task_id: "turn-1", outcome: "success" })

    const s1 = result.current.steps.find((s) => s.id === "s1")
    expect(s1?.status).toBe("done")
    // A finished card must not keep advertising a page it is no longer reading.
    for (const s of result.current.steps) {
      expect(s.activeDetail).toBeUndefined()
      expect(s.url).toBeUndefined()
    }
  })
})
