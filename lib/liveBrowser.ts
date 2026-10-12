/**
 * The agent's live browser: the latest screencast frame and who holds the page,
 * per run.
 *
 * Module state, fed by the WebSocket hook (always mounted), so a browser panel
 * opened AFTER the agent started still shows the current page at once. Before
 * this the panel learned about the live session only from frames it saw while
 * mounted - opened late, it showed the default page and nothing else
 * (live 2026-10-12).
 *
 * Two conversations can each hold a session, so runs are kept apart (a panel
 * follows ONE run, never flips between them) and a close that never arrives
 * cannot leave a dead run behind for good. Bounded: one frame per run, and at
 * most MAX_RUNS runs - the least recently active is dropped.
 */

import { useSyncExternalStore } from "react"

export interface LiveFrame {
  run_id?: string
  question_id?: string
  seq?: number
  frame_seq?: number
  viewport_w?: number
  viewport_h?: number
  format?: string
  bytes?: string
  control?: boolean
}

export interface LiveRun {
  runId: string
  /** The user holds the page (an open grant); the agent's browser actions wait. */
  control: boolean
  frame: LiveFrame | null
}

const MAX_RUNS = 4

interface RunEntry {
  control: boolean
  frame: LiveFrame | null
  /** Last activity (a frame arrived) - strictly increasing, so the oldest is unambiguous. */
  at: number
  /** The object handed to readers; rebuilt only when this run changes, so
   * useSyncExternalStore sees a stable snapshot between changes. */
  view: LiveRun
}

const runs = new Map<string, RunEntry>()
let latestRunId: string | null = null
let lastAt = 0
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach(l => l())
}

function put(runId: string, control: boolean, frame: LiveFrame | null, at: number) {
  runs.set(runId, { control, frame, at, view: { runId, control, frame } })
}

function newestRunId(): string | null {
  let best: string | null = null
  let bestAt = -1
  for (const [id, r] of runs) {
    if (r.at > bestAt) { best = id; bestAt = r.at }
  }
  return best
}

export function recordFrame(frame: LiveFrame): void {
  if (!frame?.run_id) return
  lastAt = Math.max(Date.now(), lastAt + 1)
  put(frame.run_id, !!frame.control, frame, lastAt)
  latestRunId = frame.run_id
  while (runs.size > MAX_RUNS) {
    let oldest: string | null = null
    let oldestAt = Infinity
    for (const [id, r] of runs) {
      if (r.at < oldestAt) { oldest = id; oldestAt = r.at }
    }
    if (oldest === null) break
    runs.delete(oldest)
  }
  emit()
}

export function setControl(runId: string, control: boolean): void {
  const r = runs.get(runId)
  if (r && r.control !== control) {
    put(runId, control, r.frame, r.at)
    emit()
  }
}

/** The session closed: the stream is gone, panels fall back to the captures. */
export function clearRun(runId: string): void {
  if (!runs.delete(runId)) return
  if (latestRunId === runId) latestRunId = newestRunId()
  emit()
}

/** The socket (re)connected - possibly to a NEW backend whose sessions are
 * gone. Every run is dropped; the backend sends the latest frame of each run
 * that is still live, which brings it straight back. */
export function clearAllRuns(): void {
  if (runs.size === 0) return
  runs.clear()
  latestRunId = null
  emit()
}

/** One run by id, or (no id) the most recently active one. */
export function getLiveRun(runId?: string): LiveRun | null {
  const id = runId ?? latestRunId
  return (id && runs.get(id)?.view) || null
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function useLiveBrowser(runId?: string): LiveRun | null {
  return useSyncExternalStore(subscribe, () => getLiveRun(runId), () => null)
}
