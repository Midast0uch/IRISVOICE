import { formatPlanEventMessage } from "@/components/chat/planEventMessage"

describe("formatPlanEventMessage", () => {
  it("formats plan:validation_failed with tool name", () => {
    expect(
      formatPlanEventMessage({
        type: "plan:validation_failed",
        tool_name: "web_search",
        error: "missing required param 'query'",
      }),
    ).toBe("⚠ Tool validation failed: missing required param 'query' (tool: web_search)")
  })

  it("formats plan:validation_failed without tool name", () => {
    expect(
      formatPlanEventMessage({
        type: "plan:validation_failed",
        error: "invalid parameters",
      }),
    ).toBe("⚠ Tool validation failed: invalid parameters")
  })

  it("formats plan:recovery_start with graft attempt", () => {
    expect(
      formatPlanEventMessage({
        type: "plan:recovery_start",
        failed_step: "step-3",
        num_grafted: 2,
        graft_attempts: 1,
      }),
    ).toBe("↻ Recovery started: grafting 2 step(s) after failure of step-3 (attempt 1)")
  })

  it("formats plan:recovery_start without attempt", () => {
    expect(
      formatPlanEventMessage({
        type: "plan:recovery_start",
        failed_step: "step-3",
        num_grafted: 1,
      }),
    ).toBe("↻ Recovery started: grafting 1 step(s) after failure of step-3")
  })

  it("formats plan:topology_recovery", () => {
    expect(formatPlanEventMessage({ type: "plan:topology_recovery" })).toBe(
      "↻ Topology recovery: re-running plan after a Caducean topological violation",
    )
  })

  it("formats plan:budget_exhausted", () => {
    expect(formatPlanEventMessage({ type: "plan:budget_exhausted" })).toBe(
      "⛔ Execution budget exhausted — switching to Voyager continue mode",
    )
  })

  it("returns null for unknown types", () => {
    expect(formatPlanEventMessage({ type: "something:else" })).toBeNull()
    expect(formatPlanEventMessage({})).toBeNull()
  })
})
