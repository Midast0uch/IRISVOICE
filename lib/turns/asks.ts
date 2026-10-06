/**
 * Asks anchored in a turn: IRIS needs a permission or an answer while it works.
 *
 * Source: the turn's `interaction` parts (backend/agent/turn_protocol.py:
 * permission:request / granted / denied, question:ask / answered / timeout), folded by
 * request id. The backend's grant / deny / timeout events are the authority; the user's
 * own click also resolves the ask at once (local, optimistic: the same way the legacy
 * cards remove themselves on click) so the receipt shows without waiting for the round trip.
 *
 * The countdown is real only when the backend sent `timeout_seconds` in the ask's data.
 * Nothing here invents a timeout and nothing here sends a message: the caller sends the
 * existing responses (`notification_response`, `question_response`).
 */
import { useSyncExternalStore } from "react"
import type { TurnRecord } from "@/lib/turns/turnStore"

export type AskState = "waiting" | "allowed" | "denied" | "answered" | "expired"

export interface AskItem {
  id: string
  kind: "permission" | "question"
  turnId: string
  state: AskState
  // permission
  tool?: string
  tier?: "read_only" | "side_effect" | "destructive"
  params?: Record<string, unknown>
  description?: string
  requiresConfirmation?: boolean
  // question
  text?: string
  options?: string[]
  allowOther?: boolean
  multiSelect?: boolean
  header?: string
  /** What was answered (question) */
  answer?: string
  /** Backend timeout in seconds; absent = no countdown. */
  timeoutSeconds?: number
}

type Local = { state: AskState; answer?: string }

// ── the user's own click, filed at once ─────────────────────────────────────
let _local: Record<string, Local> = {}
const _subs = new Set<() => void>()
const MAX_LOCAL = 300

export function resolveAskLocally(id: string, state: AskState, answer?: string): void {
  const next = { ..._local }
  delete next[id]
  next[id] = { state, answer }
  const ids = Object.keys(next)
  if (ids.length > MAX_LOCAL) for (const old of ids.slice(0, ids.length - MAX_LOCAL)) delete next[old]
  _local = next
  _subs.forEach((fn) => {
    try {
      fn()
    } catch {
      /* a bad subscriber must not stop the others */
    }
  })
}

const NO_LOCAL: Record<string, Local> = {}

export function useLocalAsks(): Record<string, Local> {
  return useSyncExternalStore(
    (fn) => {
      _subs.add(fn)
      return () => {
        _subs.delete(fn)
      }
    },
    () => _local,
    () => NO_LOCAL,
  )
}

export function __resetAsksForTests(): void {
  _local = {}
}

// ── fold ────────────────────────────────────────────────────────────────────
function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : undefined
}
function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() ? v : undefined
}
function arr(v: unknown): string[] | undefined {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : undefined
}

/** The asks of one turn, in the order they were asked. */
export function asksOfTurn(turn: TurnRecord, local: Record<string, Local> = {}): AskItem[] {
  const byId = new Map<string, AskItem>()
  const order: string[] = []
  const put = (a: AskItem) => {
    if (!byId.has(a.id)) order.push(a.id)
    byId.set(a.id, a)
  }
  for (const { part } of turn.parts) {
    if (part.type !== "interaction") continue
    const d = (part.data || {}) as Record<string, unknown>
    switch (part.event) {
      case "permission:request": {
        const id = str(d.request_id)
        if (!id) break
        put({
          id,
          kind: "permission",
          turnId: turn.id,
          state: "waiting",
          tool: str(d.tool_name) || "tool",
          tier: (str(d.tier) as AskItem["tier"]) || "side_effect",
          params: (d.params as Record<string, unknown>) || {},
          description: str(d.description),
          requiresConfirmation: d.requires_confirmation === true,
          timeoutSeconds: num(d.timeout_seconds),
        })
        break
      }
      case "permission:granted":
      case "permission:denied": {
        const id = str(d.request_id)
        const a = id ? byId.get(id) : undefined
        if (!a) break
        const state: AskState =
          part.event === "permission:granted" ? "allowed" : d.reason === "timeout" ? "expired" : "denied"
        byId.set(a.id, { ...a, state })
        break
      }
      case "question:ask": {
        const qs = Array.isArray(d.questions) && d.questions.length ? (d.questions as Array<Record<string, unknown>>) : null
        const list = qs ?? [d]
        for (const q of list) {
          const id = str(q.question_id)
          const text = str(q.text)
          if (!id || !text) continue
          put({
            id,
            kind: "question",
            turnId: turn.id,
            state: q.status === "answered" ? "answered" : q.status === "timed_out" ? "expired" : "waiting",
            text,
            options: arr(q.options),
            allowOther: q.allow_other === true,
            multiSelect: q.multi_select === true,
            header: str(q.header),
            timeoutSeconds: num(q.timeout_seconds) ?? num(d.timeout_seconds),
          })
        }
        break
      }
      case "question:answered": {
        const id = str(d.question_id)
        const a = id ? byId.get(id) : undefined
        if (!a) break
        const ans = Array.isArray(d.answer) ? (d.answer as unknown[]).join(", ") : typeof d.answer === "string" ? d.answer : undefined
        byId.set(a.id, { ...a, state: "answered", answer: ans ?? a.answer })
        break
      }
      case "question:timeout": {
        const id = str(d.question_id)
        const a = id ? byId.get(id) : undefined
        if (a && a.state === "waiting") byId.set(a.id, { ...a, state: "expired" })
        break
      }
    }
  }
  return order.map((id) => {
    const a = byId.get(id)!
    const l = local[id]
    // The user's own answer wins while the backend has not spoken; a backend end state wins after.
    return l && a.state === "waiting" ? { ...a, state: l.state, answer: l.answer ?? a.answer } : a
  })
}

/** The plain-word line of what a permission is about: the command, the file, the page. */
export function permissionTarget(a: AskItem): string {
  const p = a.params || {}
  for (const k of ["command", "cmd", "path", "file_path", "url", "query", "name"]) {
    const v = p[k]
    if (typeof v === "string" && v.trim()) return v.trim()
  }
  for (const v of Object.values(p)) if (typeof v === "string" && v.trim()) return v.trim()
  return a.description || ""
}
