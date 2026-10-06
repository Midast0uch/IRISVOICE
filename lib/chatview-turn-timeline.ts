import { isConversationReplyCard, type TaskCard } from "@/hooks/useTaskProgress"
import type { ShellRun } from "@/lib/cli/shellRuns"

export interface ChatTimelineMessage {
  id: string
  timestamp?: Date
}

export type ChatTimelineEntry<TMessage extends ChatTimelineMessage = ChatTimelineMessage> =
  | { kind: "message"; ts: number; message: TMessage; index: number }
  | { kind: "card"; ts: number; card: TaskCard }
  // Phase 4: a developer-mode `>cmd` and its output (lib/cli/shellRuns).
  | { kind: "shell"; ts: number; run: ShellRun }

/**
 * Build the message/card render order used by ChatView.
 *
 * Cards with a responseTurnId join immediately after the matching message.
 * Legacy cards without a match are inserted by creation time, and only the
 * newest card for each turn survives. Settled tool-less cards are conversation
 * replies rather than artifacts and are omitted — in personal mode only.
 *
 * `developer`: every turn is drawn as its matrix, which folds to one line, so
 * tool-less cards stay; and the matrix sits BEFORE the answer it produced
 * (concept 2: prompt -> matrix -> answer), not after it as a personal card does.
 */
export function buildChatTimeline<TMessage extends ChatTimelineMessage>(
  messages: TMessage[],
  cards: TaskCard[],
  shells: ShellRun[] = [],
  developer = false,
): ChatTimelineEntry<TMessage>[] {
  const base: ChatTimelineEntry<TMessage>[] = messages.map((message, index) => ({
    kind: "message" as const,
    ts: message.timestamp?.getTime?.() ?? 0,
    message,
    index,
  }))

  const latestPerTurn = new Map<string, TaskCard>()
  for (const card of cards) {
    if (!developer && isConversationReplyCard(card)) continue
    latestPerTurn.set(card.responseTurnId || `__orphan__:${card.cardId}`, card)
  }

  const out: ChatTimelineEntry<TMessage>[] = []
  const rendered = new Set<string>()
  for (const entry of base) {
    const card = entry.kind === "message" ? latestPerTurn.get(entry.message.id) : undefined
    const joins = !!card && !rendered.has(card.cardId)
    if (joins) rendered.add(card!.cardId)
    if (joins && developer) out.push({ kind: "card", ts: entry.ts, card: card! })
    out.push(entry)
    if (joins && !developer) out.push({ kind: "card", ts: entry.ts, card: card! })
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

  // Phase 4: each shell run sits after the last entry not newer than it.
  for (const run of shells) {
    let insertAt = out.length
    for (let i = out.length - 1; i >= 0; i--) {
      if (out[i].ts <= run.ts) {
        insertAt = i + 1
        break
      }
      if (i === 0) insertAt = 0
    }
    out.splice(insertAt, 0, { kind: "shell", ts: run.ts, run })
  }

  return out
}
