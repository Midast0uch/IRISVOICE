/**
 * Typed reads of the Memory surface API (backend/api/memory.py). Same style as lib/strands/api.ts: a relative
 * `/api/...` path (the app routes it to the backend), an AbortSignal timeout, JSON in and out. No React, no UI.
 * All of it is read-only: the backend opens data/memory.db read-only and never counts a read as a recall.
 */

/** The memory model the scene draws (the exporter's shape: meta, sessions, events, landmarks, …). */
export type MemoryModel = Record<string, unknown> & { meta?: { source?: string } }

export class MemoryResting extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = "MemoryResting"
  }
}

/** A cold store on the hard disk can take many seconds on the first read; the surface waits for it. */
const SNAPSHOT_TIMEOUT_MS = 180_000

export async function fetchMemorySnapshot(opts: { includeEval?: boolean; signal?: AbortSignal } = {}): Promise<MemoryModel> {
  const q = opts.includeEval ? "?include_eval=true" : ""
  const signal = opts.signal
    ? AbortSignal.any([opts.signal, AbortSignal.timeout(SNAPSHOT_TIMEOUT_MS)])
    : AbortSignal.timeout(SNAPSHOT_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(`/api/memory/snapshot${q}`, { signal })
  } catch (e) {
    if ((e as Error)?.name === "AbortError" && opts.signal?.aborted) throw e
    throw new MemoryResting(0, "IRIS's backend is not answering")
  }
  if (!res.ok) {
    // Plain words on the surface; the status stays in the console line of MemorySurface.
    const why = res.status === 404 ? "this backend has no memory reader yet - restart it after an update"
      : res.status === 503 ? "the memory store is not open yet"
      : "IRIS's backend is not answering"
    throw new MemoryResting(res.status, why)
  }
  return res.json()
}
