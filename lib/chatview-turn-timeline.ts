import { isConversationReplyCard, type TaskCard } from "@/hooks/useTaskProgress"

export interface ChatTimelineMessage {
  id: string
  timestamp?: Date
}

export type ChatTimelineEntry<TMessage extends ChatTimelineMessage = ChatTimelineMessage> =
  | { kind: "message"; ts: number; message: TMessage; index: number }
  | { kind: "card"; ts: number; card: TaskCard }

/**
 * Build the message/card render order used by ChatView.
 *
 * Cards with a responseTurnId join immediately after the matching message.
 * Legacy cards without a match are inserted by creation time, and only the
 * newest card for each turn survives. Settled tool-less cards are conversation
 * replies rather than artifacts and are omitted.
 */
export function buildChatTimeline<TMessage extends ChatTimelineMessage>(
  messages: TMessage[],
  cards: TaskCard[],
): ChatTimelineEntry<TMessage>[] {
  const base: ChatTimelineEntry<TMessage>[] = messages.map((message, index) => ({
    kind: "message" as const,
    ts: message.timestamp?.getTime?.() ?? 0,
    message,
    index,
  }))

  const latestPerTurn = new Map<string, TaskCard>()
  for (const card of cards) {
    if (isConversationReplyCard(card)) continue
    latestPerTurn.set(card.responseTurnId || `__orphan__:${card.cardId}`, card)
  }

  const out: ChatTimelineEntry<TMessage>[] = []
  const rendered = new Set<string>()
  for (const entry of base) {
    out.push(entry)
    if (entry.kind !== "message") continue
    const card = latestPerTurn.get(entry.message.id)
    if (!card || rendered.has(card.cardId)) continue
    rendered.add(card.cardId)
    out.push({ kind: "card", ts: entry.ts, card })
  }

  const unrendered = [...latestPerTurn.entries()]
    .filter(([, card]) => !rendered.has(card.cardId))
    .map(([, card]) => card)
    .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))

  for (const card of unrendered) {
    const cardTs = card.createdAt ?? Number.MAX_SAFE_INTEGER
    let insertAt = -1
    for (let i = out.length - 1; i >= 0; i--) {
      const entry = out[i]
      if (entry.kind === "message" && entry.ts <= cardTs) {
        insertAt = i + 1
        break
      }
    }
    const entry: ChatTimelineEntry<TMessage> = { kind: "card", ts: cardTs, card }
    if (insertAt >= 0) out.splice(insertAt, 0, entry)
    else out.push(entry)
  }

  return out
}
