/**
 * Undo state of edit diffs, one entry per diff_id (module-level store, read with
 * useSyncExternalStore: the lens, the ± mark and the dashboard card share one copy).
 *
 * A hunk is "undone" ONLY after the backend answered `diff_undo_result` with ok.
 * Sending the request marks it "pending"; a refusal keeps its reason. Nothing here
 * invents an outcome: the result message is the one writer of "undone".
 * Backend: backend/iris_gateway.py `_handle_diff_undo`; wire types: ./api.ts.
 */
import { useSyncExternalStore } from "react"
import type { DiffUndoResult } from "./api"

export type HunkPhase = "idle" | "pending" | "undone" | "refused"

export interface HunkUndoState {
  phase: HunkPhase
  /** Why the backend refused (phase "refused"). */
  reason?: string
  /** The user chose Keep for this hunk. */
  kept?: boolean
}

export interface DiffUndoState {
  hunks: Record<number, HunkUndoState>
  /** State of the whole-file request (hunk_index null). */
  whole: HunkUndoState
  /** The last ok undo told IRIS (backend `told_iris`). */
  toldIris?: boolean
}

const IDLE: HunkUndoState = { phase: "idle" }
const EMPTY: DiffUndoState = { hunks: {}, whole: IDLE }
const MAX_TRACKED = 400

let _state: Record<string, DiffUndoState> = {}
const _subs = new Set<() => void>()

function _set(next: Record<string, DiffUndoState>): void {
  const ids = Object.keys(next)
  if (ids.length > MAX_TRACKED) {
    // bounded: drop the oldest-inserted entries
    const keep = ids.slice(ids.length - MAX_TRACKED)
    const trimmed: Record<string, DiffUndoState> = {}
    for (const id of keep) trimmed[id] = next[id]
    next = trimmed
  }
  _state = next
  _subs.forEach((fn) => {
    try {
      fn()
    } catch {
      /* a bad subscriber must not stop the others */
    }
  })
}

function _patch(diffId: string, hunkIndex: number | null, slot: Partial<HunkUndoState>, extra: Partial<DiffUndoState> = {}): void {
  const cur = _state[diffId] || EMPTY
  const next: DiffUndoState =
    hunkIndex === null
      ? { ...cur, ...extra, whole: { ...cur.whole, ...slot } }
      : { ...cur, ...extra, hunks: { ...cur.hunks, [hunkIndex]: { ...(cur.hunks[hunkIndex] || IDLE), ...slot } } }
  const rest = { ..._state }
  delete rest[diffId] // re-insert last so eviction drops the stalest
  rest[diffId] = next
  _set(rest)
}

/** The user pressed Undo and the request left: wait for the result. */
export function markUndoPending(diffId: string, hunkIndex: number | null): void {
  _patch(diffId, hunkIndex, { phase: "pending", reason: undefined })
}

/** The request could not leave (socket closed): a refusal with a reason. */
export function markUndoRefused(diffId: string, hunkIndex: number | null, reason: string): void {
  _patch(diffId, hunkIndex, { phase: "refused", reason })
}

export function markKept(diffId: string, hunkIndex: number | null): void {
  _patch(diffId, hunkIndex, { kept: true })
}

/** The one writer of "undone": the backend's `diff_undo_result`. */
export function applyDiffUndoResult(r: DiffUndoResult | null | undefined): void {
  if (!r || typeof r.diff_id !== "string" || !r.diff_id) return
  const hunk = typeof r.hunk_index === "number" ? r.hunk_index : null
  if (r.ok) {
    _patch(r.diff_id, hunk, { phase: "undone", reason: undefined }, { toldIris: !!r.told_iris })
  } else {
    _patch(r.diff_id, hunk, { phase: "refused", reason: r.reason || "undo failed" })
  }
}

export function getUndoState(diffId: string): DiffUndoState {
  return _state[diffId] || EMPTY
}

/** Is hunk `i` undone, directly or because the whole file was? */
export function hunkPhase(s: DiffUndoState, i: number): HunkUndoState {
  if (s.whole.phase === "undone") return { ...(s.hunks[i] || IDLE), phase: "undone" }
  const h = s.hunks[i] || IDLE
  // a pending/refused whole-file request is shown on the file, not on every hunk
  return h
}

export function subscribeUndo(fn: () => void): () => void {
  _subs.add(fn)
  return () => {
    _subs.delete(fn)
  }
}

export function useUndoState(diffId: string): DiffUndoState {
  return useSyncExternalStore(
    subscribeUndo,
    () => getUndoState(diffId),
    () => EMPTY,
  )
}

/** Test-only seam. */
export function __resetUndoForTests(): void {
  _state = {}
}
