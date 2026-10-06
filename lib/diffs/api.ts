// Edit diffs: the payload the backend puts on a step's `tool:result` data (and so on
// the turn protocol's `tool_result` part) for every agent file edit, and the undo
// message. Backend: backend/agent/edit_diffs.py. No UI here.

export interface DiffHunk {
  /** Unified-diff range line, e.g. "@@ -3,7 +3,8 @@". */
  header: string
  /** Rows prefixed " " (context), "-" (removed) or "+" (added); no line endings. */
  lines: string[]
}

export interface EditDiff {
  diff_id: string
  path: string
  added: number
  removed: number
  /** Hunk i here is the `hunk_index` i of `sendDiffUndo`. May be a prefix when `truncated`. */
  hunks: DiffHunk[]
  /** Cut at 400 lines / 64 KB (or too large to diff at all: then `hunks` is empty). */
  truncated: boolean
  /** false when no copy was kept for undo (file over 2 MB) or the edit is no longer tracked. */
  undoable: boolean
  /** The edit created the file; whole-file undo deletes it. */
  new_file?: boolean
}

/** The diff fields of a `tool_result` part's `data` / a `tool:result` event. */
export interface ToolResultDiffData {
  /** The step's latest edit. */
  diff?: EditDiff
  /** Every edit of the step, present only when the step edited more than once. */
  diffs?: EditDiff[]
}

/** All diffs a tool result carries, oldest first. */
export function diffsOf(data: ToolResultDiffData | null | undefined): EditDiff[] {
  if (!data) return []
  if (Array.isArray(data.diffs) && data.diffs.length > 0) return data.diffs
  return data.diff ? [data.diff] : []
}

/** Reply to `diff_undo`. */
export interface DiffUndoResult {
  diff_id: string
  /** The hunk asked for; null for a whole-file undo. */
  hunk_index: number | null
  ok: boolean
  /** Why it was refused (file changed since the edit, lines no longer match, ...). Plain words. */
  reason?: string
  /** On success: true when IRIS was told the change was not wanted. */
  told_iris?: boolean
}

export const DIFF_UNDO = 'diff_undo'
export const DIFF_UNDO_RESULT = 'diff_undo_result'

export type SendMessageFn = (type: string, payload?: Record<string, unknown>) => boolean

/**
 * Ask the backend to undo an edit: one hunk (`hunkIndex`), or the whole file when
 * `hunkIndex` is left out. The answer arrives as a `diff_undo_result` message.
 * Returns what `sendMessage` returns (false = the socket was not open).
 */
export function sendDiffUndo(
  sendMessage: SendMessageFn | null | undefined,
  diffId: string,
  hunkIndex?: number,
): boolean {
  if (!sendMessage || !diffId) return false
  const payload: Record<string, unknown> = { diff_id: diffId }
  if (typeof hunkIndex === 'number') payload.hunk_index = hunkIndex
  return sendMessage(DIFF_UNDO, payload)
}
