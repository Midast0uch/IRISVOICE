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
  /**
   * REQ-11 AC4 — what the vision session is doing right now ("scroll",
   * "click", …), "" when no vision action is in flight.
   *
   * Vision escalation can hold a URL for 45s+ while it settles a bot-challenge
   * page. Without this the overlay sat frozen between `crawler_page_fetched`
   * and `crawler_complete` for the whole escalation, so the interactive
   * feedback died exactly when the agent was doing its most interesting work.
   * SEPARATE from pagesDone on purpose: a vision action is not a page, and
   * folding it into the page counter would misreport progress.
   */
  visionAction: string
  visionStep: number
  visionTotal: number
  /**
   * REQ-16 AC7 — best-effort cursor coordinates for the particle-trail cursor,
   * normalised 0..1 fractions of the viewport from the backend's Playwright
   * bounding-box read.
   *
   * `undefined` — NOT 0 — when the action carried no point. Consumers MUST
   * treat undefined as "keep the cursor where it was", never as "move to
   * (0,0)": a missing coordinate must not teleport the cursor.
   */
  visionX?: number
  visionY?: number
  /**
   * Absolute scroll offset (px) of the page the vision session is reading, and
   * that page's full scroll height. The panel mirrors this into the iframe so
   * the user WATCHES the page move as the model reads it — the whole point of
   * the reading surface. Absolute rather than the delta the session also emits:
   * the iframe and the headless page do not share a starting offset, and one
   * dropped event would desynchronise a delta mirror permanently.
   *
   * `undefined` when the action was not a scroll — the iframe then holds its
   * position, exactly as the cursor holds its point.
   */
  visionScrollY?: number
  visionScrollHeight?: number
  /** Monotonic counter — bumped on every scroll action so a repeated scroll to
   * the SAME offset still registers as a new instruction to mirror. Without it
   * a value-equality effect would skip it. */
  visionScrollSeq: number
}

const IDLE: NavOverlayStatus = {
  state: "idle", subGoal: "", pagesDone: 0, pagesTotal: 0,
  visionAction: "", visionStep: 0, visionTotal: 0,
  visionX: undefined, visionY: undefined,
  visionScrollY: undefined, visionScrollHeight: undefined, visionScrollSeq: 0,
}

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
        // Fresh run — a stale cursor point from a PREVIOUS run must not
        // survive into this one.
        visionAction: "",
        visionStep: 0,
        visionTotal: 0,
        visionX: undefined,
        visionY: undefined,
        // A new run starts from an unknown scroll position; carrying the last
        // run's offset would jump the iframe on the first page of the next one.
        visionScrollY: undefined,
        visionScrollHeight: undefined,
        visionScrollSeq: 0,
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

    // REQ-11 AC4: a vision action keeps the SAME animation surface alive and
    // progressing — it introduces no new visual state (REQ-11 AC3: the panel's
    // design and timing are unchanged; this is additive signal only).
    const onVisionAction = (e: Event) => {
      const d = (e as CustomEvent<{
        kind?: string; action_index?: number; total?: number
        x?: number; y?: number
        scroll_y?: number; scroll_height?: number
      }>).detail ?? {}
      setStatus(p => {
        // Never revive a finished run: a late action arriving after complete
        // or error must not restart the animation.
        if (p.state === "complete" || p.state === "error") return p
        return {
          ...p,
          // First signal of life disperses, exactly as a first page does; any
          // action after that is the crawling/shutter state.
          state: p.state === "loading" ? "dispersing" : "crawling",
          visionAction: d.kind ?? p.visionAction,
          visionStep: d.action_index ?? p.visionStep + 1,
          visionTotal: d.total ?? p.visionTotal,
          // Coordinates are best-effort per action. A missing coordinate must
          // KEEP the previous point rather than dropping the cursor to (0,0).
          visionX: d.x ?? p.visionX,
          visionY: d.y ?? p.visionY,
          visionScrollY: d.scroll_y ?? p.visionScrollY,
          visionScrollHeight: d.scroll_height ?? p.visionScrollHeight,
          visionScrollSeq:
            typeof d.scroll_y === "number" ? p.visionScrollSeq + 1 : p.visionScrollSeq,
        }
      })
    }

    window.addEventListener("iris:open_tab", onOpenTab)
    window.addEventListener("iris:crawler_started", onCrawlerStarted)
    window.addEventListener("iris:crawler_page_fetched", onPageFetched)
    window.addEventListener("iris:crawler_complete", onCrawlerComplete)
    window.addEventListener("iris:crawler_error", onCrawlerError)
    window.addEventListener("iris:crawler_vision_action", onVisionAction)

    return () => {
      window.removeEventListener("iris:open_tab", onOpenTab)
      window.removeEventListener("iris:crawler_started", onCrawlerStarted)
      window.removeEventListener("iris:crawler_page_fetched", onPageFetched)
      window.removeEventListener("iris:crawler_complete", onCrawlerComplete)
      window.removeEventListener("iris:crawler_error", onCrawlerError)
      window.removeEventListener("iris:crawler_vision_action", onVisionAction)
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
