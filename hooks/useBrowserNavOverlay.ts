"use client"

/**
 * useBrowserNavOverlay — REQ-16 AC6-AC9 (T45/T46) overlay state machine.
 *
 * Consumes the existing `iris:open_tab` / `iris:crawler_started` /
 * `iris:crawler_page_fetched` / `iris:crawler_complete` / `iris:crawler_error`
 * CustomEvents (wired in useIRISWebSocket.ts) and derives the overlay's
 * choreographed state: loading → dispersing → crawling → complete/error.
 *
 * State transitions are emitted on `iris:nav_overlay_state` (the REQ-18 trace
 * bridge, surface="in-app") so behavioral tests assert on structured state,
 * not pixels (AC9).
 */

import { useCallback, useEffect, useRef, useState } from "react"

export type NavOverlayState =
  | "idle"
  | "loading"
  | "dispersing"
  | "crawling"
  | "complete"
  | "error"

export interface NavOverlayStatus {
  state: NavOverlayState
  subGoal: string
  pagesDone: number
  pagesTotal: number
}

const IDLE: NavOverlayStatus = { state: "idle", subGoal: "", pagesDone: 0, pagesTotal: 0 }

export function useBrowserNavOverlay() {
  const [status, setStatus] = useState<NavOverlayStatus>(IDLE)

  const emitTrace = useCallback((st: NavOverlayState, detail: Record<string, unknown>) => {
    try {
      window.dispatchEvent(new CustomEvent("iris:nav_overlay_state", {
        detail: { state: st, ...detail, surface: "in-app" },
      }))
    } catch {
      // trace is optional — never break the overlay
    }
  }, [])

  // Emit the REQ-18 trace transition on every real state change (AC9).
  const prevStateRef = useRef<NavOverlayState>("idle")
  useEffect(() => {
    const prev = prevStateRef.current
    if (prev !== status.state) {
      prevStateRef.current = status.state
      emitTrace(status.state, {
        from: prev,
        sub_goal: status.subGoal,
        pages_done: status.pagesDone,
        pages_total: status.pagesTotal,
      })
    }
  }, [status, emitTrace])

  useEffect(() => {
    const onOpenTab = () => setStatus(p => ({ ...p, state: "loading", pagesDone: 0 }))
    const onCrawlerStarted = (e: Event) => {
      const d = (e as CustomEvent<{ query?: string; url_count?: number }>).detail ?? {}
      setStatus(p => ({
        state: "loading",
        subGoal: d.query ?? p.subGoal,
        pagesTotal: d.url_count ?? p.pagesTotal,
        pagesDone: 0,
      }))
    }
    const onPageFetched = (e: Event) => {
      const d = (e as CustomEvent<{ page_number?: number; total?: number }>).detail ?? {}
      setStatus(p => ({
        ...p,
        // First page found: the loading orb disperses outward ("touching"
        // the page); subsequent pages: the shutter-crawling state.
        state: p.state === "loading" ? "dispersing" : "crawling",
        pagesDone: d.page_number ?? p.pagesDone + 1,
        pagesTotal: d.total ?? p.pagesTotal,
      }))
    }
    const onCrawlerComplete = (e: Event) => {
      const d = (e as CustomEvent<{ summary?: string; page_count?: number }>).detail ?? {}
      setStatus(p => ({
        ...p,
        state: "complete",
        pagesDone: d.page_count ?? p.pagesDone,
        subGoal: d.summary ?? p.subGoal,
      }))
    }
    const onCrawlerError = () => setStatus(p => ({ ...p, state: "error" }))

    window.addEventListener("iris:open_tab", onOpenTab)
    window.addEventListener("iris:crawler_started", onCrawlerStarted)
    window.addEventListener("iris:crawler_page_fetched", onPageFetched)
    window.addEventListener("iris:crawler_complete", onCrawlerComplete)
    window.addEventListener("iris:crawler_error", onCrawlerError)

    return () => {
      window.removeEventListener("iris:open_tab", onOpenTab)
      window.removeEventListener("iris:crawler_started", onCrawlerStarted)
      window.removeEventListener("iris:crawler_page_fetched", onPageFetched)
      window.removeEventListener("iris:crawler_complete", onCrawlerComplete)
      window.removeEventListener("iris:crawler_error", onCrawlerError)
    }
  }, [])

  // Auto-dismiss: a terminal state holds briefly, then returns to idle.
  //
  // This MUST be keyed on entering complete/error. It previously lived in the
  // listener effect with `[]` deps, so the timer was armed once at MOUNT and
  // fired 3.2s later — long before any real crawl. In a live session the
  // overlay therefore never dismissed: it sat in `complete` indefinitely.
  useEffect(() => {
    if (status.state !== "complete" && status.state !== "error") return
    const hold = setTimeout(() => {
      setStatus(p =>
        p.state === "complete" || p.state === "error" ? { ...p, state: "idle" } : p,
      )
    }, 3200)
    return () => clearTimeout(hold)
  }, [status.state])

  return { status, emitTrace }
}
