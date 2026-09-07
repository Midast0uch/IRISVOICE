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
  /**
   * REQ-9 (specs/vision-browser-stage): the headless viewport's pixel size
   * for the CURRENT action — lets consumers aspect-correct the fractional
   * coordinates instead of naively stretching them onto the frame box.
   * Undefined when the action carried no viewport info.
   */
  visionViewportW?: number
  visionViewportH?: number
  /**
   * REQ-8 (specs/vision-browser-stage): true when the CURRENT action belongs
   * to a session that took over from a FAILED crawl — drives the one-shot
   * "notice" beat. False for raced sessions.
   */
  visionEscalated: boolean
  /**
   * REQ-3 AC3 (vision-goal-directed-search T19): saccadic acceleration flag.
   * True while vision actions arrive at ≥3/sec — signals the overlay to
   * compress the cursor glide from CURSOR_TRAVEL_MS (620ms) down to
   * SACCADIC_TRAVEL_MS (≤180ms) so the particle cursor stays locked to a
   * machine-speed agent's live action point instead of queueing behind it.
   * Set by counting action arrivals in a 1s trailing window; cleared when the
   * burst subsides or the run flips state.
   */
  visionSaccadic: boolean
  /**
   * REQ-10 AC10.1 (T19): a live browser_takeover request from
   * `ask_user_tool.ask_browser_takeover`. While set, the overlay renders the
   * takeover banner as the ONLY clickable element (pointer-events auto) and
   * the panel stays open for the user. Cleared the moment the matching
   * question resolves (answer OR timeout) — pointer-events re-arm to none
   * (AC10.3).
   */
  takeover: {
    questionId?: string
    url?: string
    reason?: string
  } | null
}

export interface NavOverlaySeed {
  /** Derived from CrawlProvider state so a panel mounted MID-RUN shows the
   * current state immediately (REQ-7) instead of idling until the next event. */
  active: boolean
  pagesDone: number
  pagesTotal: number
  subGoal?: string
}

const IDLE: NavOverlayStatus = {
  state: "idle", subGoal: "", pagesDone: 0, pagesTotal: 0,
  visionAction: "", visionStep: 0, visionTotal: 0,
  visionX: undefined, visionY: undefined,
  visionScrollY: undefined, visionScrollHeight: undefined, visionScrollSeq: 0,
  visionViewportW: undefined, visionViewportH: undefined,
  visionEscalated: false,
  visionSaccadic: false,
  takeover: null,
}

export function useBrowserNavOverlay(seed?: NavOverlaySeed) {
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

  // T19 (REQ-3 AC3): trailing 1s window of vision-action arrival times —
  // one ref per hook instance, bounded by the 1s filter on every event.
  const actionTimesRef = useRef<number[]>([])

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
        visionViewportW: undefined,
        visionViewportH: undefined,
        visionEscalated: false,
        // T19 (REQ-3 AC3): a burst from a PREVIOUS run must not bleed into
        // this one's cadence.
        visionSaccadic: false,
        takeover: null,
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
        viewport_w?: number; viewport_h?: number
        escalated?: boolean
      }>).detail ?? {}
      // T19 (REQ-3 AC3): saccadic burst detection — count arrivals in the
      // trailing 1s window; ≥3 actions/sec engages the compressed transit
      // (≤180ms) until the burst subsides (the next event re-counts).
      const now = Date.now()
      actionTimesRef.current = [...actionTimesRef.current.filter((t) => now - t <= 1000), now]
      const saccadic = actionTimesRef.current.length >= 3
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
          // REQ-9: source viewport dims ride along for aspect correction.
          visionViewportW: typeof d.viewport_w === "number" ? d.viewport_w : p.visionViewportW,
          visionViewportH: typeof d.viewport_h === "number" ? d.viewport_h : p.visionViewportH,
          // REQ-8: escalation provenance of THIS session.
          visionEscalated: d.escalated ?? p.visionEscalated,
          visionScrollY: d.scroll_y ?? p.visionScrollY,
          visionScrollHeight: d.scroll_height ?? p.visionScrollHeight,
          visionScrollSeq:
            typeof d.scroll_y === "number" ? p.visionScrollSeq + 1 : p.visionScrollSeq,
          // T19: the burst flag travels with the action cadence — the overlay
          // reads it once per transit instead of deriving its own timing.
          visionSaccadic: saccadic,
        }
      })
    }

    window.addEventListener("iris:open_tab", onOpenTab)
    window.addEventListener("iris:crawler_started", onCrawlerStarted)
    window.addEventListener("iris:crawler_page_fetched", onPageFetched)
    window.addEventListener("iris:crawler_complete", onCrawlerComplete)
    window.addEventListener("iris:crawler_error", onCrawlerError)
    window.addEventListener("iris:crawler_vision_action", onVisionAction)

    // T19 (REQ-10 AC10.1/AC10.3): takeover requested → the overlay's takeover
    // banner unlocks (its OWN pointer-events go auto — the overlay root stays
    // pointer-events:none so the panel below remains interactive); the
    // matching question_answered / question_timeout re-arms it to none. An
    // answered question with no takeover record is left alone entirely.
    const onTakeoverRequested = (e: Event) => {
      const d = (e as CustomEvent<{
        question_id?: string
        takeover_url?: string
        reason?: string
      }>).detail
      if (!d) return
      setStatus(p => ({
        ...p,
        takeover: { questionId: d.question_id, url: d.takeover_url, reason: d.reason },
      }))
    }
    const onQuestionResolved = (e: Event) => {
      const d = (e as CustomEvent<{ question_id?: string }>).detail
      if (!d) return
      setStatus(p => {
        if (!p.takeover) return p
        if (p.takeover.questionId && d.question_id && p.takeover.questionId !== d.question_id) return p
        return { ...p, takeover: null }
      })
    }
    window.addEventListener("iris:browser_takeover_requested", onTakeoverRequested)
    window.addEventListener("iris:question_answered", onQuestionResolved)
    window.addEventListener("iris:question_timeout", onQuestionResolved)

    return () => {
      window.removeEventListener("iris:open_tab", onOpenTab)
      window.removeEventListener("iris:crawler_started", onCrawlerStarted)
      window.removeEventListener("iris:crawler_page_fetched", onPageFetched)
      window.removeEventListener("iris:crawler_complete", onCrawlerComplete)
      window.removeEventListener("iris:crawler_error", onCrawlerError)
      window.removeEventListener("iris:crawler_vision_action", onVisionAction)
      window.removeEventListener("iris:browser_takeover_requested", onTakeoverRequested)
      window.removeEventListener("iris:question_answered", onQuestionResolved)
      window.removeEventListener("iris:question_timeout", onQuestionResolved)
    }
  }, [])

  // ── REQ-7 (specs/vision-browser-stage): mid-run mount backfill ──────────
  // A panel mounted after crawler_started used to idle at IDLE until the next
  // event arrived. The CrawlProvider already retains the run's state, so seed
  // from it ONCE per run — only while IDLE, so real events keep ownership the
  // moment they flow, and SSE snapshot replays cannot double-seed.
  const seededRunRef = useRef<string>("")
  useEffect(() => {
    if (!seed?.active) return
    const runKey = `${seed.subGoal ?? ""}|${seed.pagesTotal ?? 0}`
    if (seededRunRef.current === runKey) return
    seededRunRef.current = runKey
    setStatus(p => {
      if (p.state !== "idle") return p // live events own the surface already
      return {
        ...p,
        state: "loading",
        subGoal: seed.subGoal ?? p.subGoal,
        pagesDone: seed.pagesDone,
        pagesTotal: seed.pagesTotal || p.pagesTotal,
      }
    })
  }, [seed?.active, seed?.pagesDone, seed?.pagesTotal, seed?.subGoal])

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
