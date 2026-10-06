/**
 * Which artifacts a task card made, and under which step they hang. Pure.
 * A document joins its card by turn id (the same join the timeline uses); it hangs under
 * the step that ran the artifact tool (create_artifact / show), else it goes last.
 */
import type { MadeItem } from "@/components/chat/matrix/LiveMatrix"

interface DocLike {
  id: string
  format: string
  content: string
  title?: string
  turnId?: string
  createdAt?: number
  partial?: boolean
}

interface StepLike {
  id: string
  toolName?: string
}

export function madeItemsFor(docs: DocLike[] | undefined, turnIds: Array<string | undefined>, steps: StepLike[]): MadeItem[] {
  const ids = new Set(turnIds.filter((t): t is string => !!t))
  if (!docs || ids.size === 0) return []
  const maker = [...steps].reverse().find((s) => /artifact|^show$/i.test(s.toolName || ""))
  return docs
    .filter((d) => !!d.turnId && ids.has(d.turnId) && !d.partial)
    .map((d) => ({ id: d.id, doc: d, afterRowId: maker?.id }))
}
