/**
 * Place live turns into a conversation's message list (execution audit Phase 3).
 *
 * A turn that has streamed parts but whose final assistant message has not
 * landed yet (or never will — an error or cancelled turn) gets a placeholder
 * assistant entry, so it renders in its conversation, at its place, while it
 * runs. The placeholder's id IS the turn id: the same anchor rule live
 * messages already use (assistant message id === turn_id), so cards and
 * documents keyed by the turn join it exactly as they join a final message.
 *
 * Placement: right after the user message the turn answers (turn.clientRef
 * === that message's id); else after the last message older than the turn;
 * else at the end. Pure: no React, no store access.
 */
import type { TurnRecord } from "./turnStore"

export interface MergeableMessage {
  id: string
  text: string
  sender: string
  timestamp: Date
  turn_id?: string
}

export function mergeLiveTurns<M extends MergeableMessage>(
  messages: M[],
  turns: TurnRecord[],
  makePlaceholder: (turn: TurnRecord) => M,
): M[] {
  if (!turns.length) return messages
  const known = new Set<string>()
  for (const m of messages) {
    known.add(m.id)
    if (m.turn_id) known.add(m.turn_id)
  }
  const missing = turns.filter((t) => !known.has(t.id))
  if (!missing.length) return messages
  const out = [...messages]
  for (const turn of missing) {
    let at = -1
    if (turn.clientRef) {
      const i = out.findIndex((m) => m.id === turn.clientRef)
      if (i >= 0) at = i + 1
    }
    if (at < 0) {
      for (let i = out.length - 1; i >= 0; i--) {
        const ts = out[i].timestamp?.getTime?.() ?? 0
        if (ts <= turn.startedAt) {
          at = i + 1
          break
        }
      }
    }
    if (at < 0) at = out.length
    // Keep several turns answering one prompt in start order.
    while (at < out.length && out[at].sender !== "user" && (out[at].timestamp?.getTime?.() ?? 0) <= turn.startedAt) at++
    out.splice(at, 0, makePlaceholder(turn))
  }
  return out
}
