"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import type {
  CrawlerStartedMsg,
  CrawlerPageMsg,
  CrawlerErrorMsg,
  CrawlerCompleteMsg,
  OpenTabMsg,
} from "@/types/iris"
import { useReducedMotion } from "./useReducedMotion"
import { useCrawlSSE } from "./useCrawlSSE"

export interface CrawlPageProgress {
  url: string
  pageNumber: number
  total: number
  host: string
}

export interface CrawlState {
  active: boolean
  query: string
  pages: CrawlPageProgress[]
  total: number
  error: string | null
  complete: boolean
  summary: string | null
  citedMarkdown: string | null
  credibilityTopScore: number | null
  dashboard: OpenTabMsg["data"] | null
  // REQ-31 edge: when the event log TTL-evicted before we could replay, the
  // client must do a full sync instead of trusting partial replay.
  syncRequired: boolean
  // Session id the backend used for this crawl (enables SSE fallback replay).
  sessionId: string | null
}

const IDLE: CrawlState = {
  active: false,
  query: "",
  pages: [],
  total: 0,
  error: null,
  complete: false,
  summary: null,
  citedMarkdown: null,
  credibilityTopScore: null,
  dashboard: null,
  syncRequired: false,
  sessionId: null,
}

function _hostOf(url: string): string {
  try {
    return new URL(url).hostname || url
  } catch {
    return url
  }
}

/**
 * useCrawl — single hook that owns crawl research UI state (REQ-12/13/23/30).
 *
 * Consumes the unified crawler CustomEvents dispatched by useIRISWebSocket
 * (WS path) AND useCrawlSSE (SSE fallback path). Both transports emit the
 * SAME event names, so this hook is transport-agnostic — it never knows or
 * cares which channel delivered the event (REQ-31 AC4: one event contract).
 *
 * Audio/visual non-contradiction (REQ-30): when prefersReducedMotion is set we
 * suppress orb/pill animation churn and rely on the textual step feed only.
 */
export function useCrawl(wsConnected: boolean = true) {
  const [state, setState] = useState<CrawlState>(IDLE)
  const reducedMotion = useReducedMotion()
  const activeRef = useRef(false)
  const sessionIdRef = useRef<string | null>(null)

  const reset = useCallback(() => setState(IDLE), [])

  useEffect(() => {
    function onStarted(e: Event) {
      const msg = (e as CustomEvent<CrawlerStartedMsg>).detail
      activeRef.current = true
      sessionIdRef.current = msg.session_id ?? sessionIdRef.current
      setState((s) => ({
        ...IDLE,
        active: true,
        query: msg.query,
        total: msg.url_count,
        sessionId: sessionIdRef.current,
      }))
    }
    function onPage(e: Event) {
      const msg = (e as CustomEvent<CrawlerPageMsg>).detail
      setState((s) => ({
        ...s,
        active: true,
        total: msg.total || s.total,
        pages: [
          ...s.pages.filter((p) => p.url !== msg.url),
          {
            url: msg.url,
            pageNumber: msg.page_number,
            total: msg.total,
            host: msg.host || _hostOf(msg.url),
          },
        ],
      }))
    }
    function onOpenTab(e: Event) {
      const msg = (e as CustomEvent<OpenTabMsg>).detail
      setState((s) => ({ ...s, dashboard: msg.data }))
    }
    function onError(e: Event) {
      const msg = (e as CustomEvent<CrawlerErrorMsg>).detail
      activeRef.current = false
      setState((s) => ({ ...s, active: false, error: msg.message }))
    }
    function onComplete(e: Event) {
      const msg = (e as CustomEvent<CrawlerCompleteMsg>).detail
      activeRef.current = false
      setState((s) => ({
        ...s,
        active: false,
        complete: true,
        summary: msg.summary || s.summary,
        citedMarkdown: msg.cited_markdown ?? s.citedMarkdown,
        credibilityTopScore: msg.credibility_top_score ?? s.credibilityTopScore,
      }))
    }
    function onSyncRequired() {
      // REQ-31 edge / T23: TTL eviction dropped events we never replayed, so
      // partial SSE replay is insufficient. Fetch the FULL snapshot and apply
      // every buffered event as a complete re-sync.
      const sid = sessionIdRef.current
      if (!sid) {
        setState((s) => ({ ...s, syncRequired: true }))
        return
      }
      setState((s) => ({ ...s, syncRequired: true }))
      fetch(`/api/crawl/snapshot/${encodeURIComponent(sid)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((snap) => {
          if (!snap || !snap.ok) return
          // Re-apply every buffered event as a full sync (idempotent: handlers
          // dedupe by url / overwrite by field). This restores complete state.
          for (const ev of snap.events as Array<{ type: string; payload: any }>) {
            window.dispatchEvent(new CustomEvent(`iris:${ev.type}`, { detail: ev.payload }))
          }
        })
        .catch(() => {
          /* leave syncRequired set; next reconnect retries */
        })
    }

    const t: EventTarget = window
    t.addEventListener("iris:crawler_started", onStarted as EventListener)
    t.addEventListener("iris:crawler_page_fetched", onPage as EventListener)
    t.addEventListener("iris:open_tab", onOpenTab as EventListener)
    t.addEventListener("iris:crawler_error", onError as EventListener)
    t.addEventListener("iris:crawler_complete", onComplete as EventListener)
    t.addEventListener("iris:crawler_sync_required", onSyncRequired as EventListener)
    return () => {
      t.removeEventListener("iris:crawler_started", onStarted as EventListener)
      t.removeEventListener("iris:crawler_page_fetched", onPage as EventListener)
      t.removeEventListener("iris:open_tab", onOpenTab as EventListener)
      t.removeEventListener("iris:crawler_error", onError as EventListener)
      t.removeEventListener("iris:crawler_complete", onComplete as EventListener)
      t.removeEventListener("iris:crawler_sync_required", onSyncRequired as EventListener)
    }
  }, [])

  // REQ-31 AC3/AC5: SSE fallback — activates only when the primary WS is down.
  // Uses the session id captured from crawler_started so it replays the same
  // event log the backend is writing. Both transports dispatch identical
  // CustomEvents, so the state above is transport-agnostic.
  const { sseConnected } = useCrawlSSE(sessionIdRef.current, wsConnected)

  return { state, reset, reducedMotion, isActive: activeRef, sseConnected }
}
