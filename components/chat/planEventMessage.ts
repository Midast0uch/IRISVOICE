// Format an execution-hardening plan event (Phase 4.1) into a chat system
// message. Returns null for unknown event types so the listener can skip them.
// Pure module so it is unit-testable without rendering the chat component.

export interface PlanEventDetail {
  type?: string
  tool_name?: string
  error?: string
  step_id?: string
  failed_step?: string
  num_grafted?: number
  graft_attempts?: number
  critical?: boolean
}

export function formatPlanEventMessage(detail: PlanEventDetail): string | null {
  switch (detail.type) {
    case "plan:validation_failed":
      return `⚠ Tool validation failed: ${detail.error ?? "invalid parameters"}${detail.tool_name ? ` (tool: ${detail.tool_name})` : ""}`
    case "plan:recovery_start":
      return `↻ Recovery started: grafting ${detail.num_grafted ?? 0} step(s) after failure of ${detail.failed_step ?? "unknown step"}${detail.graft_attempts ? ` (attempt ${detail.graft_attempts})` : ""}`
    case "plan:topology_recovery":
      return `↻ Topology recovery: re-running plan after a Caducean topological violation`
    case "plan:budget_exhausted":
      return `⛔ Execution budget exhausted — switching to Voyager continue mode`
    default:
      return null
  }
}
