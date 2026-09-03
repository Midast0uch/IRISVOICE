/**
 * lib/logger.ts — cli-workspace-unification T11 (REQ-8).
 *
 * Structured observability for CLI command dispatches, Blueprint Matrix
 * transitions and multi-agent card events. Every entry carries an ISO-8601
 * timestamp and the active conversation ID (passed by the caller).
 *
 * NON-BLOCKING (REQ-8 AC2): fire-and-forget POST with `keepalive`; the call
 * site never awaits and never fails the user path — network errors are
 * swallowed by design. The server route appends to `.iris-logs/`.
 */

export function logStructured(channel: string, data: Record<string, unknown> = {}): void {
  if (typeof window === "undefined") return
  const entry = { ts: new Date().toISOString(), channel, ...data }
  try {
    void fetch("/api/logs/structured", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
      keepalive: true,
    }).catch(() => {
      /* observability must never break the path it instruments */
    })
  } catch {
    /* same — swallow */
  }
}
