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
const SNAPSHOT_RETRY_MS = 5_000

export async function fetchMemorySnapshot(opts: { includeEval?: boolean; signal?: AbortSignal } = {}): Promise<MemoryModel> {
  const q = opts.includeEval ? "?include_eval=true" : ""
  const signal = opts.signal
    ? AbortSignal.any([opts.signal, AbortSignal.timeout(SNAPSHOT_TIMEOUT_MS)])
    : AbortSignal.timeout(SNAPSHOT_TIMEOUT_MS)
  // The app's proxy gives up on a request long before a cold first read ends (2026-10-24: "socket hang up" after
  // ~30 s, 500 to the page, while the backend went on and cached the snapshot - the next call took 0.03 s). So a 5xx
  // or a lost connection is asked again until the budget ends; the backend answers from its cache once it is done.
  const deadline = Date.now() + SNAPSHOT_TIMEOUT_MS
  let res: Response | null = null
  for (;;) {
    try {
      res = await fetch(`/api/memory/snapshot${q}`, { signal })
      if (res.ok || res.status < 500) break
    } catch (e) {
      if ((e as Error)?.name === "AbortError" || (e as Error)?.name === "TimeoutError") {
        if (opts.signal?.aborted) throw e
        throw new MemoryResting(0, "IRIS's backend is not answering")
      }
      res = null
    }
    if (Date.now() + SNAPSHOT_RETRY_MS >= deadline) break
    await new Promise<void>((ok, no) => {
      const t = setTimeout(ok, SNAPSHOT_RETRY_MS)
      signal.addEventListener("abort", () => { clearTimeout(t); no(signal.reason) }, { once: true })
    })
  }
  if (!res) throw new MemoryResting(0, "IRIS's backend is not answering")
  if (!res.ok) {
    // Plain words on the surface; the status stays in the console line of MemorySurface.
    const why = res.status === 404 ? "this backend has no memory reader yet - restart it after an update"
      : res.status === 503 ? "the memory store is not open yet"
      : "IRIS's backend is not answering"
    throw new MemoryResting(res.status, why)
  }
  return res.json()
}

/** The memory-native search (GET /api/memory/search): ranked by the memory's own law; a search is never a recall. */
export async function searchMemory(q: string, signal?: AbortSignal): Promise<any> {
  const s = signal ? AbortSignal.any([signal, AbortSignal.timeout(10_000)]) : AbortSignal.timeout(10_000)
  const res = await fetch(`/api/memory/search?q=${encodeURIComponent(q)}`, { signal: s })
  if (!res.ok) {
    let why = res.status === 404 ? "this backend has no memory search yet - restart it after an update" : "the memory did not answer"
    if (res.status === 400) why = (await res.json().catch(() => null))?.detail || "the memory did not understand that search"
    throw new MemoryResting(res.status, why)
  }
  return res.json()
}

/**
 * A deep link into the memory ("claim:<id>", "strand:<id>", "turn:<conv>:<turn>", "lens:<name>"). The card action
 * `open_memory` carries it as `detail.focus`; the dashboard may not be mounted yet, so the link waits here until the
 * surface's scene is ready, and a surface already on screen hears it at once (the "iris:memory_focus" event).
 */
let pendingFocus: string | null = null
export function requestMemoryFocus(ref: unknown): void {
  if (typeof ref !== "string" || !ref) return
  pendingFocus = ref
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("iris:memory_focus", { detail: ref }))
}
/** The waiting deep link, once: the surface takes it when its scene is ready. */
export function takeMemoryFocus(): string | null {
  const r = pendingFocus
  pendingFocus = null
  return r
}

/**
 * Memory -> chat (MEMORY-UX-PLAN 4.6): open a conversation, at a turn when one is named. The memory surface sends
 * `iris:open_conversation {conversationId, turnId?}`; the page opens the chat wing and leaves the request here, and
 * the chat view takes it once it is mounted (the chat wing may have been closed), or hears "iris:chat_request".
 */
export type ChatRequest = { conversationId: string; turnId?: string }
let pendingChat: ChatRequest | null = null
export function requestChatTurn(r: unknown): void {
  const d = r as Partial<ChatRequest> | null
  if (!d || typeof d.conversationId !== "string" || !d.conversationId) return
  pendingChat = { conversationId: d.conversationId, turnId: typeof d.turnId === "string" && d.turnId ? d.turnId : undefined }
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("iris:chat_request"))
}
export function takeChatTurn(): ChatRequest | null {
  const r = pendingChat
  pendingChat = null
  return r
}

/**
 * Corrections v1 (MEMORY-SURFACE-BUILD.md section 5): the backend writes each one as USER evidence and answers with the
 * claim's state before and after; the surface shows only what the backend answered (never optimistic). Undo within
 * 10 minutes. Claims only for now.
 */
export type CorrectionAction = "confirm" | "wrong" | "forget"
export type ClaimState = { tier: string; contradictions: number; absorbed: boolean; evidence_count: number }
export type Correction = { correction_id: string; action: CorrectionAction; target: string; landmark_id: string; before: ClaimState; after: ClaimState; undo_until: number }

async function postJson(path: string, body: unknown): Promise<any> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(15_000) })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new MemoryResting(res.status, (data && (data.detail || data.error)) || "the memory did not take the correction")
  return data
}

export function correctMemory(action: CorrectionAction, target: string, reason?: string): Promise<Correction> {
  return postJson("/api/memory/correct", { action, target, ...(reason ? { reason } : {}) })
}

export function undoCorrection(correctionId: string): Promise<{ undone: boolean; landmark_id: string; after: ClaimState }> {
  return postJson("/api/memory/correct/undo", { correction_id: correctionId })
}

export async function listCorrections(limit = 20): Promise<{ corrections: Array<{ correction_id: string; ts: number; action: CorrectionAction; target: string; landmark_id: string; claim: string; undone: boolean; undo_until: number }> }> {
  const res = await fetch(`/api/memory/corrections?limit=${limit}`, { signal: AbortSignal.timeout(10_000) })
  if (!res.ok) throw new MemoryResting(res.status, "your corrections could not be read")
  return res.json()
}
