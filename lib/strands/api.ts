/**
 * Typed fetch helpers for threads and strands (backend/api/chat.py).
 *
 * A thread is the whole; each chat under it is a strand. The thread list is a
 * SUMMARY read - no message bodies - so opening the thread picker does not
 * download every message (the lag that GET /api/conversations caused).
 *
 * Same style as the conversation calls in components/chat-view.tsx: a relative
 * `/api/...` path (installApiOriginBridge routes it per surface), an
 * AbortSignal.timeout, JSON in and out. No React, no UI.
 */

export const PRESET_STRAND_TAGS = ["plan", "build", "research", "people", "swarm"] as const

export interface ThreadSummary {
  id: string
  title: string
  pinned: boolean
  updated_at: string
  strand_count: number
  message_count: number
  /** Newest message, whitespace-collapsed, at most 80 characters. */
  last_preview: string
}

export interface Strand {
  id: string
  title: string
  tags: string[]
  /** Id of the strand that started this helper strand; null for a normal strand. */
  reports_to: string | null
  updated_at: string
  message_count: number
}

export interface CreateStrandBody {
  name: string
  /** At most 8 tags, 24 characters each; the backend trims and lowercases. */
  tags?: string[]
  reports_to?: string
}

const TIMEOUT_MS = 8000

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  })
  if (!res.ok) throw new Error(`${method} ${path} returned ${res.status}`)
  return res.json()
}

const enc = encodeURIComponent

export function fetchThreads(): Promise<ThreadSummary[]> {
  return call("GET", "/api/threads")
}

export function fetchStrands(threadId: string): Promise<Strand[]> {
  return call("GET", `/api/threads/${enc(threadId)}/strands`)
}

export function createStrand(threadId: string, body: CreateStrandBody): Promise<Strand> {
  return call("POST", `/api/threads/${enc(threadId)}/strands`, body)
}

export function patchStrand(
  strandId: string,
  body: { name?: string; tags?: string[] },
): Promise<Strand> {
  return call("PATCH", `/api/strands/${enc(strandId)}`, body)
}

export function patchThread(
  threadId: string,
  body: { title?: string; pinned?: boolean },
): Promise<ThreadSummary> {
  return call("PATCH", `/api/threads/${enc(threadId)}`, body)
}
