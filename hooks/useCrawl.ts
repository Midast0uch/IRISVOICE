"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import type {
  CrawlerStartedMsg,
  CrawlerPageMsg,
  CrawlerProgressMsg,
  CrawlerPhaseMsg,
  CrawlerVisionActionMsg,
  CrawlerSourceParkedMsg,
  CrawlerErrorMsg,
  CrawlerCompleteMsg,
  OpenTabMsg,
} from "@/types/iris"
import { useReducedMotion } from "./useReducedMotion"
import { useCrawlSSE } from "./useCrawlSSE"

// sessionStorage keys — let the provider restore a run after a full app
// remount (REQ-12 AC3) without re-crawling.
const SESSION_KEY = "iris:crawl:session_id"

export interface CrawlPageProgress {
  url: string
  pageNumber: number
  total: number
  host: string
  /** REQ-11 (T13): capture provenance so the panel can replay the bytes the
   * agent actually read (jobId/capturePage -> /api/browser/capture/...). */
  jobId?: string
  /** Capture-store ADDRESS of this page's bytes. Distinct from pageNumber, which
   * is the progress counter — see CrawlerPageMsg.capture_page. */
  capturePage?: number
  /** False when the page was deliberately not persisted (challenge interstitial,
   * REQ-4 AC2): there is nothing to replay and the panel must say so. */
  captureAvailable?: boolean
  title?: string
}

export interface CrawlSnapshotEvent {
  seq: number
  type: string
  payload: Record<string, unknown>
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
  // ── T17 (REQ-11 AC4 / REQ-12 AC2): live run detail surfaced while the
  // panel is closed. Transport-agnostic: both the WS dispatch and the SSE
  // fallback emit the SAME CustomEvents for these.
  /** Latest in-flight stage message ("Narrowing search…"). */
  progress: string | null
  /** Structured pipeline phase (searching / extracting / citing…). */
  phase: string | null
  /** Monotonic phase sequence (disambiguates re-emission). */
  phaseSequence: number | null
  /** REQ-11 AC4: vision actions performed on pages (panel annotation). */
  visionActions: CrawlerVisionActionMsg[]
  /** REQ-13 AC4: sources parked behind a wall (non-blocking ask). */
  parkedSources: CrawlerSourceParkedMsg[]
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
  progress: null,
  phase: null,
  phaseSequence: null,
  visionActions: [],
  parkedSources: [],
}

function _persistSession(sid: string | null) {
  try {
    if (sid) sessionStorage.setItem(SESSION_KEY, sid)
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    /* storage unavailable — restore-on-remount degrades to live events only */
  }
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

  const reset = useCallback(() => {
    _persistSession(null)
    setState(IDLE)
  }, [])

  useEffect(() => {
    function onStarted(e: Event) {
      const msg = (e as CustomEvent<CrawlerStartedMsg>).detail
      activeRef.current = true
      sessionIdRef.current = msg.session_id ?? sessionIdRef.current
      if (msg.session_id) _persistSession(msg.session_id)
      setState(() => ({
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
            jobId: msg.job_id,
            // Fall back to the counter only when the backend sent no address —
            // the batch path, where the two coincide. Never invent one.
            capturePage: msg.capture_page ?? msg.page_number,
            // Absent means "not reported", which for older emitters meant the
            // bytes were there; only an explicit false is a blocked page.
            captureAvailable: msg.capture_available !== false,
            title: msg.title,
          },
        ],
      }))
    }
    function onOpenTab(e: Event) {
      const msg = (e as CustomEvent<OpenTabMsg>).detail
      setState((s) => ({ ...s, dashboard: msg.data }))
    }
    function onProgress(e: Event) {
      const msg = (e as CustomEvent<CrawlerProgressMsg>).detail
      setState((s) => ({ ...s, active: true, progress: msg.message ?? msg.stage ?? s.progress }))
    }
    function onPhase(e: Event) {
      const msg = (e as CustomEvent<CrawlerPhaseMsg>).detail
      setState((s) => ({
        ...s,
        active: true,
        phase: msg.phase ?? s.phase,
        phaseSequence: msg.phase_sequence ?? s.phaseSequence,
      }))
    }
    function onVisionAction(e: Event) {
      const msg = (e as CustomEvent<CrawlerVisionActionMsg>).detail
      setState((s) => ({
        ...s,
        active: true,
        visionActions: [...s.visionActions, msg],
      }))
    }
    function onSourceParked(e: Event) {
      const msg = (e as CustomEvent<CrawlerSourceParkedMsg>).detail
      setState((s) => ({
        ...s,
        active: true,
        parkedSources: [...s.parkedSources, msg],
      }))
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
    function onSyncRequired(e: Event) {
      // REQ-31 edge / T23: TTL eviction dropped events we never replayed, so
      // partial SSE replay is insufficient. Fetch the FULL snapshot and apply
      // every buffered event as a complete re-sync.
      const d = (e as CustomEvent<{ session_id?: string }>).detail
      if (d?.session_id) {
        sessionIdRef.current = d.session_id
        _persistSession(d.session_id)
      }
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
          for (const ev of snap.events as Array<CrawlSnapshotEvent>) {
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
    t.addEventListener("iris:crawler_progress", onProgress as EventListener)
    t.addEventListener("iris:crawler_phase", onPhase as EventListener)
    // The SSE transport maps CRAWLER_PHASE to msg_type `task:event`
    // (backend/crawler/ux_map.py) and useCrawlSSE re-dispatches `iris:task:event`.
    // Accept BOTH names so phase updates land regardless of transport (REQ-31
    // AC4: one event contract). The WS path may also deliver `crawler_phase`.
    t.addEventListener("iris:task:event", onPhase as EventListener)
    t.addEventListener("iris:crawler_vision_action", onVisionAction as EventListener)
    t.addEventListener("iris:crawler_source_parked", onSourceParked as EventListener)
    t.addEventListener("iris:crawler_error", onError as EventListener)
    t.addEventListener("iris:crawler_complete", onComplete as EventListener)
    t.addEventListener("iris:crawler_sync_required", onSyncRequired as EventListener)
    return () => {
      t.removeEventListener("iris:crawler_started", onStarted as EventListener)
      t.removeEventListener("iris:crawler_page_fetched", onPage as EventListener)
      t.removeEventListener("iris:open_tab", onOpenTab as EventListener)
      t.removeEventListener("iris:crawler_progress", onProgress as EventListener)
      t.removeEventListener("iris:crawler_phase", onPhase as EventListener)
      t.removeEventListener("iris:task:event", onPhase as EventListener)
      t.removeEventListener("iris:crawler_vision_action", onVisionAction as EventListener)
      t.removeEventListener("iris:crawler_source_parked", onSourceParked as EventListener)
      t.removeEventListener("iris:crawler_error", onError as EventListener)
      t.removeEventListener("iris:crawler_complete", onComplete as EventListener)
      t.removeEventListener("iris:crawler_sync_required", onSyncRequired as EventListener)
    }
  }, [])

  // REQ-12 AC3 (T18): restore a run's state from the server-side event log on
  // remount. Fetches GET /api/crawl/snapshot/{session_id}; if the log evicted
  // events the client never replayed (snapshot.sync_required / client flag set)
  // it re-dispatches EVERY buffered event as a full sync, otherwise only
  // events with seq > afterSeq. Re-dispatch is idempotent (handlers dedupe by
  // url / overwrite by field), so restore can run repeatedly without duplicating.
  const restore = useCallback((sessionId: string, afterSeq: number) => {
    if (!sessionId) return
    fetch(`/api/crawl/snapshot/${encodeURIComponent(sessionId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((snap) => {
        if (!snap || !snap.ok) return
        const fullSync = snap.sync_required === true
        const events = (snap.events ?? []) as Array<CrawlSnapshotEvent>
        for (const ev of events) {
          if (!fullSync && ev.seq <= afterSeq) continue
          window.dispatchEvent(new CustomEvent(`iris:${ev.type}`, { detail: ev.payload }))
        }
        // Mirror the authoritative server eviction flag into client state so a
        // subsequent partial replay knows a full sync already happened.
        setState((s) => ({ ...s, syncRequired: fullSync }))
      })
      .catch(() => {
        /* restore is best-effort; live events + SSE replay cover the gap */
      })
  }, [])

  // REQ-31 AC3/AC5: SSE fallback — activates only when the primary WS is down.
  // Uses the session id captured from crawler_started so it replays the same
  // event log the backend is writing. Both transports dispatch identical
  // CustomEvents, so the state above is transport-agnostic.
  const { sseConnected } = useCrawlSSE(sessionIdRef.current, wsConnected)

  return { state, reset, restore, reducedMotion, isActive: activeRef, sseConnected }
}
