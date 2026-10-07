/**
 * The turn protocol is the ONE courier (execution audit Phase 3, retired
 * couriers 2026-10-06). The backend no longer sends a legacy frame for an event
 * it filed into a turn; this maps each filed part, and the turn's end, back to
 * the message the views already read, so every consumer (task cards in both
 * modes, the matrix, the orb badge, artifacts, asks, notices, the reply bubble
 * and its TTS highlight) is fed from the turn - nothing reads two couriers.
 *
 * Pure: no React, no window. The WS hook replays the result through its own
 * message switch.
 */
import type { TurnMessage } from "./protocol"

export type LegacyMessage = { type: string; payload: Record<string, unknown> }

type AnyPart = { type?: string; event?: string; data?: unknown; ok?: boolean; message?: string }

/** The legacy message one filed part replaces, or null for a part the turn
 *  views render themselves (text / reasoning / error). */
export function legacyMessageForPart(part: AnyPart | undefined): LegacyMessage | null {
  if (!part || typeof part !== "object") return null
  const data = (part.data && typeof part.data === "object" ? part.data : {}) as Record<string, unknown>
  switch (part.type) {
    case "todo":
    case "interaction":
    case "notice":
      return typeof part.event === "string" ? { type: part.event, payload: data } : null
    case "tool_call":
      return { type: "tool:call", payload: data }
    case "tool_result":
      // route_bus_event files tool:result AND tool:error as tool_result; a
      // tool:error payload carries `error` and no `result_summary`.
      return {
        type: part.ok === false && "error" in data && !("result_summary" in data) ? "tool:error" : "tool:result",
        payload: data,
      }
    case "card":
      return { type: "document:render", payload: data }
    default:
      return null
  }
}

/** The reply message a finished turn replaces (the old `chat_message`), or null
 *  when the turn ended without a reply (error / cancelled: the turn shows those). */
export function legacyReplyForEnd(
  end: Extract<TurnMessage, { type: "turn.end" }>["payload"],
  reasoning?: string,
): LegacyMessage | null {
  const text = typeof end.text === "string" ? end.text : ""
  if (end.status !== "ok" || !text.trim()) return null
  return {
    type: "chat_message",
    payload: {
      role: "assistant",
      content: text,
      spoken: typeof end.speak === "string" && end.speak ? end.speak : undefined,
      thinking: reasoning || undefined,
      turn_id: end.turn_id,
    },
  }
}
