"use client"

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react"
import { useCrawl, type CrawlState } from "./useCrawl"

// sessionStorage key used by useCrawl (must match — single source of truth is
// the SESSION_KEY constant in useCrawl.ts; this provider only reads it).
const SESSION_KEY = "iris:crawl:session_id"

export interface CrawlContextValue {
  state: CrawlState
  reset: () => void
  sseConnected: boolean
}

const CrawlContext = createContext<CrawlContextValue | null>(null)

/**
 * CrawlProvider — hoists useCrawl ABOVE the browser panel's unmount boundary
 * (REQ-12 AC2). The panel can unmount and remount at will; crawl state, the
 * event listeners and the SSE fallback all live here and survive. On a FULL
 * provider remount (app reload / navigation) it restores the last run's state
 * from the server-side event log instead of re-crawling (REQ-12 AC3, T18).
 */
export function CrawlProvider({
  children,
  wsConnected = true,
}: {
  children: ReactNode
  /** Pass false when the primary WebSocket is down so the SSE fallback engages
   * (REQ-31 AC3). Defaults to true (matches useCrawl's default). */
  wsConnected?: boolean
}) {
  const { state, reset, restore, sseConnected } = useCrawl(wsConnected)

  // REQ-12 AC3 (T18): on remount, replay the event log for the last session.
  // afterSeq = 0 replays every buffered event (idempotent — handlers dedupe by
  // url / overwrite by field), which reconstructs the run without re-crawling.
  // If the log evicted events (snapshot.sync_required) restore() upgrades to a
  // full snapshot sync (REQ-12 AC6).
  useEffect(() => {
    let sid: string | null = null
    try {
      sid = sessionStorage.getItem(SESSION_KEY)
    } catch {
      /* storage unavailable — nothing to restore */
    }
    if (sid) restore(sid, 0)
  }, [restore])

  const value = useMemo(
    () => ({ state, reset, sseConnected }),
    [state, reset, sseConnected],
  )

  return <CrawlContext.Provider value={value}>{children}</CrawlContext.Provider>
}

export function useCrawlContext(): CrawlContextValue {
  const ctx = useContext(CrawlContext)
  if (!ctx) {
    throw new Error("useCrawlContext must be used within a <CrawlProvider>")
  }
  return ctx
}
