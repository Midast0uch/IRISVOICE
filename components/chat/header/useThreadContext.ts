"use client"

/**
 * Which thread and strand is on screen. A strand IS a conversation id, so the
 * active conversation is either a thread root or one of a root's strands.
 * GET /api/threads lists roots only; a strand's root is found by looking in the
 * strand lists of the threads that have more than one strand. The answer is
 * kept: while the active id stays inside the known strand list, no call is made.
 *
 * Summary reads only (lib/strands/api) - never fetchConversations.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { fetchStrands, fetchThreads, patchThread, type Strand, type ThreadSummary } from "@/lib/strands/api"

/** The root strand has the thread's own title (same row), so it is shown as "main". */
export const ROOT_STRAND_LABEL = "main"
export const strandLabel = (s: Strand, rootId: string | null) => (s.id === rootId ? ROOT_STRAND_LABEL : s.title)

const MAX_SCAN = 40 // bound: threads whose strand lists are read to find a strand's root

export interface ThreadContext {
  /** The thread (root) that holds the active conversation; null while unknown or for a new thread. */
  root: ThreadSummary | null
  strands: Strand[]
  /** The active conversation as a strand; null while unknown. */
  current: Strand | null
  reloadStrands: () => Promise<Strand[]>
  rename: (title: string) => Promise<void>
}

export function useThreadContext(activeId: string | null): ThreadContext {
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [rootId, setRootId] = useState<string | null>(null)
  const [strands, setStrands] = useState<Strand[]>([])
  const loaded = useRef(false) // a fetch was started
  const ready = useRef(false) // a fetch finished
  const retriedFor = useRef<string | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  // Thread list: once, and once more when the active id is in none of them
  // (a conversation made after the list was read).
  useEffect(() => {
    const unknown = !!activeId && ready.current && !threads.some((t) => t.id === activeId) && !strands.some((s) => s.id === activeId)
    if (loaded.current && !(unknown && retriedFor.current !== activeId)) return
    if (unknown) retriedFor.current = activeId
    loaded.current = true
    fetchThreads()
      .then((list) => { if (!mounted.current) return; ready.current = true; setThreads(Array.isArray(list) ? list : []) })
      .catch((e) => console.warn("[ChatHeader] fetchThreads failed:", e))
  }, [activeId, threads, strands])

  // Root of the active conversation.
  useEffect(() => {
    if (!activeId) { setRootId(null); setStrands((prev) => (prev.length ? [] : prev)); return } // same array when already empty: no render loop
    if (threads.some((t) => t.id === activeId)) { setRootId(activeId); return }
    if (rootId && strands.some((s) => s.id === activeId)) return
    let cancelled = false
    ;(async () => {
      for (const t of threads.filter((x) => x.strand_count > 1).slice(0, MAX_SCAN)) {
        try {
          const list = await fetchStrands(t.id)
          if (cancelled) return
          if (list.some((s) => s.id === activeId)) { setStrands(list); setRootId(t.id); return }
        } catch (e) {
          console.warn("[ChatHeader] fetchStrands failed while resolving the thread:", t.id, e)
        }
      }
      if (!cancelled) setRootId(null)
    })()
    return () => { cancelled = true }
  }, [activeId, threads, rootId, strands])

  const reloadStrands = useCallback(async (): Promise<Strand[]> => {
    if (!rootId) return []
    try {
      const list = await fetchStrands(rootId)
      setStrands(list)
      return list
    } catch (e) {
      console.warn("[ChatHeader] fetchStrands failed:", rootId, e)
      return []
    }
  }, [rootId])

  // Strand list of the root, when the root changes.
  useEffect(() => {
    if (!rootId) return
    let cancelled = false
    fetchStrands(rootId)
      .then((list) => { if (!cancelled) setStrands(Array.isArray(list) ? list : []) })
      .catch((e) => console.warn("[ChatHeader] fetchStrands failed:", rootId, e))
    return () => { cancelled = true }
  }, [rootId])

  const rename = useCallback(async (title: string) => {
    if (!rootId) return
    const updated = await patchThread(rootId, { title })
    setThreads((prev) => prev.map((t) => (t.id === rootId ? { ...t, ...updated } : t)))
    setStrands((prev) => prev.map((s) => (s.id === rootId ? { ...s, title: updated.title ?? title } : s)))
  }, [rootId])

  const root = rootId ? threads.find((t) => t.id === rootId) ?? null : null
  const current = activeId ? strands.find((s) => s.id === activeId) ?? null : null
  return { root, strands, current, reloadStrands, rename }
}
