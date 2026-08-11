"use client"

/**
 * BrowserNavigationOverlay — REQ-16 AC6-AC9 (T45/T46) particle-shutter overlay.
 *
 * The agent's in-app browser navigation is made VISIBLE by lighting the browser
 * card ITSELF, using the same 3-shell epitrochoid particle engine as
 * XurOrb/OrbCanvas (components/iris/orb/OrbCanvas.tsx).
 *
 * DESIGN INVARIANT — THE CARD IS ONE OBJECT.
 * The overlay is NOT a rectangle drawn on top of the browser. It traces the
 * panel's OWN rounded-2xl border (RADIUS below must equal the panel's border
 * radius) and washes inward from that border, so the chrome (tab bar + address
 * bar) and the viewport are lit as a single surface. An earlier revision was
 * anchored to the wrong ancestor and drew a sharp-cornered rectangle across the
 * header — visually a separate thing sitting on top. Two rules keep that fixed:
 *
 *   1. The mount site MUST be `position: relative` (dark-glass-dashboard.tsx
 *      browser panel). `absolute inset-0` otherwise escapes to the content
 *      column and the geometry silently belongs to a different element.
 *   2. Geometry is MEASURED (ResizeObserver), never assumed. Every size below
 *      derives from the measured W/H — particle radius, trail length, wash
 *      depth and speed all scale with the panel so the effect reads the same
 *      on a narrow widget and a maximised window.
 *
 * One canvas, one rAF, one draw call. State drives an eased INTENSITY envelope
 * rather than swapping distinct visuals, so loading → dispersing → crawling →
 * complete is one continuous gesture on one surface:
 *
 *   LOADING     one dim stream + the orb materialising at the viewport centre
 *   DISPERSING  three streams bloom outward; the orb "reaches out" (C-opening)
 *   CRAWLING    three streams at full cadence — the shutter running the border
 *   COMPLETE    the border settles to an even ring, then fades
 *   ERROR       the same settle in amber
 *
 * Every state transition is written to the REQ-18 per-task trace (T31's
 * der_trace) so behavioral tests assert on structured state, not pixels (AC9).
 * All animation is off the critical path, rAF-driven, useReducedMotion-aware.
 */

import React, { useEffect, useRef, useCallback, useState } from "react"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { OrbCanvas } from "@/components/iris/orb/OrbCanvas"

// ── engine constants (mirror OrbCanvas.tsx so the cadence is identical) ───
const SHELLS = [
  { scale: 1.05, speed: 1.0, count: 80, alpha: 0.55, size: 1.0 },
  { scale: 0.70, speed: 1.45, count: 56, alpha: 0.40, size: 0.8 },
  { scale: 0.42, speed: 0.62, count: 32, alpha: 0.85, size: 0.7 },
]
const PULSE_DURATION = 4200

/**
 * Overlay orb size. OrbCanvas now takes this as a prop, so this single number
 * drives the canvas, the particle radii and the CSS box together.
 *
 * Smaller than the main orb's 120: here it sits INSIDE the page frame with the
 * border comet running around it, and at 120 it dominated the viewport and
 * read as the subject rather than as a progress indicator.
 */
const ORB_SIZE = 76

/**
 * Cursor size — the orb's size once it has become the vision cursor.
 *
 * 40, not smaller. OrbCanvas maps its particle coords to SIZE/2, so the three
 * shells scale proportionally: below roughly 34 the 168 particles congeal into
 * a featureless dot and the shell structure — the thing that makes it read as
 * OUR orb rather than a generic cursor — is lost. 40 keeps all three shells
 * legible while still reading as a pointer beside a full-size 76 orb.
 */
const CURSOR_SIZE = 40

/**
 * Travel time from the orb's resting centre to an action point.
 *
 * Long enough to read as a deliberate movement rather than a jump-cut, short
 * enough that a fast action sequence does not queue up behind it.
 */
const CURSOR_TRAVEL_MS = 620

/** How many decaying afterimages trail the cursor. */
const CURSOR_TRAIL_LEN = 5

/** Panel border radius. MUST equal the mount container's rounded-2xl (1rem). */
const RADIUS = 16

/** Fraction of the perimeter one comet trail occupies. */
const TRAIL_FRAC = 0.18

/** Settle/fade window for the terminal states. */
const SETTLE_MS = 1200

/**
 * Ring pacing. `lapMs` is how long one trip around the card takes; it is
 * derived from the live gap between page_fetched events (see the effect on
 * `pagesDone`), so the border moves at the speed of the actual crawl.
 *
 * LAP_PER_PAGE stretches one lap across ~1.8 page intervals — at 1.0 the ring
 * tracks the crawl exactly but reads as frantic, so it is deliberately geared
 * DOWN. These three constants are the tuning surface for "too fast / too slow";
 * nothing else needs to change.
 */
const LAP_PER_PAGE = 1.8
const LAP_MIN_MS = 1600
const LAP_MAX_MS = 7000
const LAP_DEFAULT_MS = 5200

/** Forward kick applied to the ring while a page-fetch impulse is decaying. */
const SHUTTER_SPEED_BOOST = 0.9

const ERROR_COLOR = "#fbbf24"

/** Per-state target intensity — the envelope the draw loop eases toward. */
const INTENSITY: Record<string, number> = {
  idle: 0,
  loading: 0.34,
  dispersing: 0.72,
  crawling: 1,
  complete: 0.85,
  error: 0.85,
}

/**
 * Uniform dark scrim per state.
 *
 * The overlay sits on top of ARBITRARY page content — and the real web is
 * mostly white. A cyan glow at 0.1 alpha is invisible over a white page, which
 * is how the first revision ended up illegible in practice: it was designed
 * against the dark panel and never checked over a live site.
 *
 * So the overlay carries its own substrate. It is heaviest while the agent is
 * still ORIENTING (loading/dispersing — there is nothing to read yet and the
 * orb needs contrast) and drops away once CRAWLING starts, because the whole
 * point is watching the page get scrolled and scraped. The edge vignette in
 * drawEdgeWash stays regardless, so the shutter always has something to burn
 * against without covering the content.
 */
const SCRIM: Record<string, number> = {
  idle: 0,
  loading: 0.55,
  dispersing: 0.42,
  crawling: 0.14,
  complete: 0.14,
  error: 0.14,
}

/**
 * Safe alpha tint: glowColor may be HEX ("#7dd3fc") or HSL ("hsl(190,100%,50%)")
 * from the brand context. Appending an alpha suffix to either produces an
 * invalid color string ("hsl(...)22") that crashes canvas/CSS rendering.
 * HEX gets an alpha suffix; HSL gets wrapped in hsla() with the alpha fraction.
 */
function tint(color: string, alphaHex: string): string {
  const a = parseInt(alphaHex, 16) / 255
  if (color.startsWith("#")) return `${color}${alphaHex}`
  const hsl = color.match(/hsl\(([^)]+)\)/)
  if (hsl) return `hsla(${hsl[1]}, ${a})`
  return color
}

export type OverlayState = "idle" | "loading" | "dispersing" | "crawling" | "complete" | "error"

export interface BrowserNavigationOverlayProps {
  /** live crawl/sub-goal text to narrate during the loading orb moment */
  subGoal?: string
  pagesDone?: number
  pagesTotal?: number
  glowColor?: string
  /**
   * Height in px of the panel's own chrome (tab bar + address bar) stacked
   * above the viewport. The orb centres on the VIEWPORT, not on the panel box,
   * and the top wash deepens to exactly cover the chrome so the header is lit
   * as part of the same surface. The mount site knows this — it renders it.
   */
  chromeInset?: number
  /** externally-driven state (from iris:crawler_* / iris:open_tab events) */
  state: OverlayState
  /** called on every state transition for REQ-18 trace (AC9) */
  onStateChange?: (state: OverlayState, detail: Record<string, unknown>) => void
  /**
   * REQ-11 AC4 — the vision agent's current action ("click" / "type" /
   * "scroll"), "" when none is in flight.
   *
   * When this is set the CENTRE ORB BECOMES THE CURSOR: the same OrbCanvas
   * instance travels to the action point and tightens. It is deliberately not
   * a second particle system — a morph between two engines could never be
   * mathematically continuous, whereas moving and resizing one instance is
   * exact. OrbCanvas integrates shell phase per frame, so both the travel and
   * the period change happen WITHOUT snapping any particle (see its
   * `orbitPeriodMs` note).
   */
  visionAction?: string
  /**
   * Action point as fractions of the VIEWPORT (0..1), from the backend's
   * Playwright bounding-box centre. Fractions rather than pixels because the
   * panel scales the captured frame — pixels would misplace the cursor at any
   * other size. Undefined for actions with no point (scroll), in which case
   * the cursor holds its last position rather than teleporting to a corner.
   */
  visionX?: number
  visionY?: number
  /** Monotonic action index; a change is what triggers a fresh travel + wake. */
  visionStep?: number
}

/** Walk a rounded rectangle's perimeter. Returns the point at arc-length `d`. */
function makeRoundedPath(W: number, H: number, r0: number) {
  const r = Math.max(0, Math.min(r0, W / 2, H / 2))
  const hSeg = Math.max(0, W - 2 * r)
  const vSeg = Math.max(0, H - 2 * r)
  const arc = (Math.PI / 2) * r
  const perim = 2 * hSeg + 2 * vSeg + 4 * arc

  // Cumulative segment boundaries, clockwise from the top-left corner end.
  const b = [hSeg, hSeg + arc, hSeg + arc + vSeg, hSeg + 2 * arc + vSeg,
             2 * hSeg + 2 * arc + vSeg, 2 * hSeg + 3 * arc + vSeg,
             2 * hSeg + 3 * arc + 2 * vSeg, perim]

  function at(dRaw: number) {
    const d = ((dRaw % perim) + perim) % perim
    if (d < b[0]) return { x: r + d, y: 0 }
    if (d < b[1]) { const t = (d - b[0]) / arc * (Math.PI / 2) - Math.PI / 2
                    return { x: W - r + r * Math.cos(t), y: r + r * Math.sin(t) } }
    if (d < b[2]) return { x: W, y: r + (d - b[1]) }
    if (d < b[3]) { const t = (d - b[2]) / arc * (Math.PI / 2)
                    return { x: W - r + r * Math.cos(t), y: H - r + r * Math.sin(t) } }
    if (d < b[4]) return { x: W - r - (d - b[3]), y: H }
    if (d < b[5]) { const t = (d - b[4]) / arc * (Math.PI / 2) + Math.PI / 2
                    return { x: r + r * Math.cos(t), y: H - r + r * Math.sin(t) } }
    if (d < b[6]) return { x: 0, y: H - r - (d - b[5]) }
    const t = (d - b[6]) / arc * (Math.PI / 2) + Math.PI
    return { x: r + r * Math.cos(t), y: r + r * Math.sin(t) }
  }

  return { at, perim, r }
}

export const BrowserNavigationOverlay = React.memo(function BrowserNavigationOverlay({
  subGoal = "",
  pagesDone = 0,
  pagesTotal = 0,
  glowColor = "#7dd3fc",
  chromeInset = 0,
  state,
  onStateChange,
  visionAction = "",
  visionX,
  visionY,
  visionStep = 0,
}: BrowserNavigationOverlayProps) {
  const prefersReducedMotion = useReducedMotion()
  const rootRef = useRef<HTMLDivElement>(null)
  const borderRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)

  // Live values the rAF loop reads without re-subscribing (avoids restarting
  // the animation — and therefore the eased envelope — on every prop change).
  const stateRef = useRef<OverlayState>(state)
  const colorRef = useRef<string>(glowColor)
  const chromeRef = useRef<number>(chromeInset)
  const intensityRef = useRef<number>(0)
  const scrimRef = useRef<number>(0)
  const enteredRef = useRef<number>(0)

  // ── Crawl-driven motion ─────────────────────────────────────────────────
  // The shutter runs at the speed of the ACTUAL crawl, not a fixed clock.
  // `lapMs` is the time for one trip around the card, derived from the live
  // interval between page_fetched events; `shutter` is a per-page impulse that
  // snaps the inward shadow closed and kicks the particles forward.
  //
  // Phase is INTEGRATED per frame (phase += dt / lapMs) rather than computed
  // from absolute elapsed time. Recomputing position from elapsed whenever the
  // speed changes teleports every particle; integrating keeps the ring
  // continuous while its speed varies.
  // ── Vision cursor (REQ-11 AC4) ──────────────────────────────────────────
  // `null` = the orb is at its resting centre; a point = it has travelled and
  // become the cursor. Held in state (not a ref) because position drives CSS,
  // not the canvas draw loop.
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [trail, setTrail] = useState<{ x: number; y: number; k: number }[]>([])
  const lastStepRef = useRef<number>(0)

  // A NEW action (step changed) moves the cursor and pushes the old point onto
  // the trail. Gated on the step rather than on the coordinates so a repeated
  // action at the same spot still registers as a fresh beat, and so an action
  // WITHOUT a point (scroll) holds position instead of teleporting to 0,0.
  useEffect(() => {
    if (!visionStep || visionStep === lastStepRef.current) return
    lastStepRef.current = visionStep
    if (typeof visionX !== "number" || typeof visionY !== "number") return
    setCursor((prev) => {
      if (prev) {
        setTrail((t) => [{ ...prev, k: 1 }, ...t].slice(0, CURSOR_TRAIL_LEN))
      }
      return { x: visionX, y: visionY }
    })
  }, [visionStep, visionX, visionY])

  // Trail decay. One interval for the whole trail rather than a timer per
  // afterimage, and it stops itself the moment the trail empties so an idle
  // overlay holds no timers.
  useEffect(() => {
    if (trail.length === 0) return
    const id = setInterval(() => {
      setTrail((t) =>
        t.map((p) => ({ ...p, k: p.k - 0.14 })).filter((p) => p.k > 0.02),
      )
    }, 60)
    return () => clearInterval(id)
  }, [trail.length])

  // The run ended (or restarted): the cursor dissolves and the orb returns to
  // centre for the next one.
  useEffect(() => {
    if (state === "idle" || state === "complete" || state === "error") {
      setCursor(null)
      setTrail([])
      lastStepRef.current = 0
    }
  }, [state])

  const phaseRef = useRef<number>(0)
  const lapMsRef = useRef<number>(LAP_DEFAULT_MS)
  // React-visible mirror of lapMsRef, consumed only by the orb (see below).
  const [orbPeriodMs, setOrbPeriodMs] = useState<number>(LAP_DEFAULT_MS)
  const shutterRef = useRef<number>(0)
  const lastFrameRef = useRef<number>(0)
  const lastFetchRef = useRef<number>(0)
  const intervalsRef = useRef<number[]>([])

  stateRef.current = state
  colorRef.current = glowColor
  chromeRef.current = chromeInset

  // Each newly fetched page fires the shutter and re-times the ring.
  useEffect(() => {
    if (pagesDone <= 0) return
    const now = Date.now()
    shutterRef.current = 1
    if (lastFetchRef.current > 0) {
      const gap = now - lastFetchRef.current
      // Ignore absurd gaps (tab backgrounded, agent paused) — they would
      // otherwise pin the ring at its slowest for the rest of the crawl.
      if (gap > 80 && gap < 30000) {
        const buf = intervalsRef.current
        buf.push(gap)
        if (buf.length > 5) buf.shift()
        const sorted = [...buf].sort((a, b) => a - b)
        const median = sorted[Math.floor(sorted.length / 2)]
        // Geared down from the raw page cadence — see LAP_PER_PAGE.
        lapMsRef.current = Math.min(Math.max(median * LAP_PER_PAGE, LAP_MIN_MS), LAP_MAX_MS)
        // Mirror into state purely so the ORB (a React child) re-renders with
        // the new cadence. The canvas ring keeps reading the ref every frame —
        // it must not depend on React's render clock.
        setOrbPeriodMs(lapMsRef.current)
      }
    }
    lastFetchRef.current = now
  }, [pagesDone])

  // Prev-state tracking for AC9 transition logging (only on real changes).
  const prevStateRef = useRef<OverlayState | null>(null)
  useEffect(() => {
    if (prevStateRef.current !== state) {
      const prev = prevStateRef.current
      prevStateRef.current = state
      enteredRef.current = Date.now()
      onStateChange?.(state, {
        from: prev ?? "idle",
        sub_goal: subGoal,
        pages_done: pagesDone,
        pages_total: pagesTotal,
      })
    }
  }, [state, subGoal, pagesDone, pagesTotal, onStateChange])

  // ── The card-border shutter ─────────────────────────────────────────────
  // Runs for every non-idle state; `state` is read through a ref so the loop
  // is never torn down mid-choreography. Geometry is MEASURED, so every size
  // below is proportional to the panel the overlay actually occupies.
  const startLoop = useCallback(() => {
    const canvas = borderRef.current
    const root = rootRef.current
    if (!canvas || !root) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let W = 0
    let H = 0
    let path = makeRoundedPath(0, 0, RADIUS)

    const measure = () => {
      // LAYOUT box, not getBoundingClientRect().
      //
      // The wing renders this panel under rotateY(-15deg)/rotateX(2deg) with
      // perspective:800px, and getBoundingClientRect() returns the PROJECTED
      // box — already foreshortened. The canvas sits INSIDE that same
      // transformed subtree, so sizing it from the projected width applies the
      // foreshortening twice: the canvas came out narrower than the card it is
      // supposed to trace (measured: 605px canvas inside a 679px card), and
      // the whole overlay sat visibly offset from the browser. Flat views were
      // unaffected because there the projected box equals the layout box —
      // which is exactly why this looked like "it depends on which view".
      //
      // offsetWidth/offsetHeight are pre-transform, so the canvas always
      // matches the element it overlays and the CSS transform does the
      // perspective exactly once.
      const dpr = window.devicePixelRatio || 1
      W = Math.max(1, root.offsetWidth)
      H = Math.max(1, root.offsetHeight)
      canvas.width = Math.round(W * dpr)
      canvas.height = Math.round(H * dpr)
      canvas.style.width = `${W}px`
      canvas.style.height = `${H}px`
      // Setting canvas.width resets the transform — re-apply DPR scaling.
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      path = makeRoundedPath(W, H, RADIUS)
    }
    measure()

    const ro = new ResizeObserver(measure)
    ro.observe(root)

    const t0 = Date.now()

    /**
     * Edge geometry shared by the dark vignette and the coloured wash.
     * `reach` > 1 pushes each gradient further inward — that travel is what
     * makes the shutter read as closing rather than merely brightening.
     */
    function edgeGradients(reach: number) {
      const base = Math.min(Math.max(Math.min(W, H) * 0.12, 20), 72) * reach
      // The top reaches at least to the bottom of the chrome, so the tab bar
      // and address bar sit INSIDE the glow rather than beside it.
      const depths = [Math.max(base, chromeRef.current), base, base, base]
      return [
        [0, 0, 0, depths[0]],           // top    ↓
        [W, 0, W - depths[1], 0],       // right  ←
        [0, H, 0, H - depths[2]],       // bottom ↑
        [0, 0, depths[3], 0],           // left   →
      ] as Array<[number, number, number, number]>
    }

    function paintEdges(color: string, alpha: number, blend: GlobalCompositeOperation, reach = 1) {
      if (alpha <= 0.002) return
      ctx.save()
      ctx.globalCompositeOperation = blend
      for (const [x0, y0, x1, y1] of edgeGradients(reach)) {
        const g = ctx.createLinearGradient(x0, y0, x1, y1)
        g.addColorStop(0, color)
        g.addColorStop(1, "transparent")
        ctx.globalAlpha = alpha
        ctx.fillStyle = g
        ctx.fillRect(0, 0, W, H)
      }
      ctx.restore()
    }

    /**
     * Inward wash from each edge — this is what makes the card ONE surface.
     * Two passes: a DARK vignette first so the colour has something to burn
     * against over a white page, then the brand colour on top in `lighter`.
     *
     * The dark pass is THE SHUTTER. It rides `shutterRef`, which snaps to 1 on
     * every page_fetched and decays — so each page the crawler lands closes the
     * aperture inward and lets it fall open again. Between pages it only
     * breathes. The motion is the crawl, not a decorative loop.
     */
    function drawEdgeWash(color: string, k: number, elapsed: number) {
      const breath = 0.5 + 0.5 * Math.sin((elapsed / PULSE_DURATION) * Math.PI * 2)
      // Ease the impulse so the close is fast and the re-open is soft.
      const snap = shutterRef.current * shutterRef.current
      paintEdges("#04080c", (0.5 + 0.42 * snap) * k, "source-over", 1 + 1.1 * snap)
      paintEdges(color, (0.16 + 0.10 * breath + 0.30 * snap) * k, "lighter", 1 + 0.5 * snap)
    }

    /** The travelling comet streams on the card border. */
    function drawStreams(color: string, k: number, elapsed: number, streams: number) {
      const perim = path.perim
      // Scale with the panel: a maximised window gets bigger, better-spaced
      // particles instead of the same 1px dots spread thinner.
      const sizeScale = Math.min(Math.max(perim / 1600, 1), 2.2)

      ctx.save()
      ctx.globalCompositeOperation = "lighter"
      ctx.fillStyle = color

      for (let sh = 0; sh < streams; sh++) {
        const shell = SHELLS[sh]
        // Position comes from the INTEGRATED phase, so the ring speeds up and
        // slows down with the crawl without the particles ever jumping.
        const head = (phaseRef.current * shell.speed + sh / streams) * perim
        for (let i = 0; i < shell.count; i++) {
          const fade = 1 - i / shell.count
          // Mode-D cadence ripple (the exact OrbCanvas breathing expression).
          const wave = Math.sin((i / shell.count) * Math.PI * 4 - elapsed * 0.004) * 2.5
          const alphaMult = Math.max(0.05, 1 + wave)
          // Trail is a COMPACT arc behind the head, not the whole perimeter —
          // that is what reads as a shutter rather than a static dotted ring.
          const pt = path.at(head - (i / shell.count) * TRAIL_FRAC * perim)
          ctx.globalAlpha = Math.min(1, fade * 0.5 * shell.alpha * alphaMult * k)
          ctx.beginPath()
          ctx.arc(pt.x, pt.y, (0.55 + fade * 1.15) * sizeScale * shell.size, 0, Math.PI * 2)
          ctx.fill()
        }
        // Head bloom — the bright point leading each stream.
        const hp = path.at(head)
        const hr = 5 * sizeScale
        const hg = ctx.createRadialGradient(hp.x, hp.y, 0, hp.x, hp.y, hr)
        hg.addColorStop(0, color)
        hg.addColorStop(1, "transparent")
        ctx.globalAlpha = 0.5 * k * shell.alpha
        ctx.fillStyle = hg
        ctx.beginPath()
        ctx.arc(hp.x, hp.y, hr, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = color
      }
      ctx.restore()
    }

    /** Terminal settle: an even ring on the border, fading out. */
    function drawSettle(color: string, k: number) {
      ctx.save()
      ctx.globalCompositeOperation = "lighter"
      ctx.strokeStyle = color
      ctx.globalAlpha = 0.5 * k
      ctx.lineWidth = 1.25
      const r = path.r
      ctx.beginPath()
      ctx.moveTo(r, 0.6)
      ctx.arcTo(W - 0.6, 0.6, W - 0.6, H - 0.6, r)
      ctx.arcTo(W - 0.6, H - 0.6, 0.6, H - 0.6, r)
      ctx.arcTo(0.6, H - 0.6, 0.6, 0.6, r)
      ctx.arcTo(0.6, 0.6, W - 0.6, 0.6, r)
      ctx.closePath()
      ctx.stroke()
      ctx.restore()
    }

    function draw() {
      const now = Date.now()
      const elapsed = now - t0
      // Clamp dt so a backgrounded tab resuming does not fling the ring.
      const dt = Math.min(64, now - (lastFrameRef.current || now))
      lastFrameRef.current = now
      const st = stateRef.current
      const terminal = st === "complete" || st === "error"
      const color = st === "error" ? ERROR_COLOR : colorRef.current

      // Terminal states fade their envelope to zero over SETTLE_MS so the card
      // returns to rest smoothly instead of snapping (and never leaves a
      // frozen frame behind — see the cleanup below).
      let target = INTENSITY[st] ?? 0
      if (terminal) {
        const held = now - (enteredRef.current || now)
        target *= Math.max(0, 1 - held / SETTLE_MS)
      }
      // Ease toward the target — this continuity is what makes the four
      // states read as one gesture rather than four separate effects.
      intensityRef.current += (target - intensityRef.current) * 0.08
      const k = intensityRef.current

      // The scrim eases on its own curve so the page fades back IN as soon as
      // crawling starts, independent of the shutter's brightness envelope.
      let scrimTarget = SCRIM[st] ?? 0
      if (terminal) {
        const held = now - (enteredRef.current || now)
        scrimTarget *= Math.max(0, 1 - held / SETTLE_MS)
      }
      scrimRef.current += (scrimTarget - scrimRef.current) * 0.08

      // Shutter impulse decays over ~620ms; while it is high the ring is
      // kicked forward, so each page lands as a visible surge around the card.
      shutterRef.current = Math.max(0, shutterRef.current - dt / 620)
      phaseRef.current =
        (phaseRef.current +
          (dt / lapMsRef.current) * (1 + shutterRef.current * SHUTTER_SPEED_BOOST)) % 1

      ctx.clearRect(0, 0, W, H)
      if (scrimRef.current > 0.004) {
        ctx.save()
        ctx.globalAlpha = scrimRef.current
        ctx.fillStyle = "#04080c"
        ctx.fillRect(0, 0, W, H)
        ctx.restore()
      }
      if (k > 0.004) {
        drawEdgeWash(color, k, elapsed)
        if (terminal) drawSettle(color, k)
        else drawStreams(color, k, elapsed, st === "loading" ? 1 : SHELLS.length)
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(rafRef.current)
      ro.disconnect()
      // Clear on teardown. Without this the last painted frame stays on the
      // card until unmount — a frozen shutter over a finished page.
      if (W > 0 && H > 0) ctx.clearRect(0, 0, W, H)
    }
  }, [])

  useEffect(() => {
    if (prefersReducedMotion) return
    if (state === "idle") return
    return startLoop()
    // Deliberately NOT keyed on `state`/`glowColor` beyond the idle gate —
    // those are read through refs so the envelope survives transitions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefersReducedMotion, state === "idle", startLoop])

  // The orb stays on screen while vision is driving — that IS the cursor. Its
  // absence during escalation was the dead air the user reported: the panel
  // froze between the last page and completion, which is exactly when the
  // agent was doing its most interesting work.
  const isCursor = cursor !== null
  const showOrb = state === "loading" || state === "dispersing" || isCursor

  // Surface speed, not angular speed. Holding the period constant while the
  // orb shrinks to CURSOR_SIZE makes it read as SLOWING DOWN, because the same
  // revolution now covers a much shorter circumference. Scaling the period by
  // the size ratio keeps the particles moving at the same apparent rate, so
  // shrinking reads as the same object tightening rather than a different,
  // lazier one. Safe mid-flight: OrbCanvas integrates phase.
  const orbSize = isCursor ? CURSOR_SIZE : ORB_SIZE
  const orbPeriodEffective = isCursor
    ? Math.max(400, orbPeriodMs * (CURSOR_SIZE / ORB_SIZE))
    : orbPeriodMs

  // NOTE on centring the orb: plain `left-1/2` is correct and needs NO
  // perspective compensation. The overlay root is `absolute inset-0` on the
  // card, so 50% of the root IS the card's centre, and the shared CSS
  // transform projects orb and card together. An earlier revision added a
  // measured per-frame nudge here after observing the orb sitting 45px left of
  // the border canvas — but that gap was the canvas being sized from the
  // PROJECTED box (see `measure` above), not a perspective error in the orb.
  // The nudge therefore centred the orb on a too-small canvas and pushed it
  // 36px off the real centre. Fixing the measurement removed the symptom; do
  // not reintroduce a correction here without first checking that the canvas
  // box equals the card's layout box.

  // EVERY HOOK MUST BE ABOVE THIS LINE. The idle early-return is conditional,
  // so a hook placed after it is skipped on idle renders and React throws
  // "Rendered more hooks than during the previous render" the moment the
  // overlay wakes up. (tsc does not catch this — it is a runtime rule.)
  if (state === "idle") return null

  // Only show the counter once a page has actually landed — "0/5" while the
  // crawl is still starting reads as a stall.
  const counter = pagesDone > 0 && pagesTotal > 0 ? `${pagesDone}/${pagesTotal}` : ""
  const subGoalLine = [subGoal, counter].filter(Boolean).join(" · ")

  return (
    <div
      ref={rootRef}
      className="absolute inset-0 pointer-events-none z-30 overflow-hidden"
      style={{ borderRadius: RADIUS }}
    >
      {/* Border shutter + inward wash — the card lit as one surface. */}
      <canvas
        ref={borderRef}
        className="absolute inset-0"
        style={{ pointerEvents: "none" }}
        aria-hidden="true"
      />

      {/* Centre orb — reuses the exact OrbCanvas engine (loading / dispersing).
          Centred on the VIEWPORT (panel minus its chrome), not the panel box. */}
      {/* Cursor wake — the orb's own afterimages, drawn with the same glow so
          the trail reads as the orb's motion blur rather than a separate
          decoration. Skipped entirely under reduced motion. */}
      {isCursor && !prefersReducedMotion && trail.map((p, i) => (
        <div
          key={`${p.x}-${p.y}-${i}`}
          className="absolute rounded-full"
          style={{
            left: `${p.x * 100}%`,
            top: `calc(${p.y * 100}% + ${chromeInset}px)`,
            transform: "translate(-50%, -50%)",
            width: CURSOR_SIZE * 0.34 * p.k,
            height: CURSOR_SIZE * 0.34 * p.k,
            background: `radial-gradient(circle, ${glowColor} 0%, transparent 70%)`,
            opacity: p.k * 0.42,
            transition: "opacity 60ms linear",
          }}
          aria-hidden="true"
        />
      ))}

      {showOrb && !prefersReducedMotion && (
        <div
          className={isCursor ? "absolute" : "absolute left-1/2"}
          style={{
            // Cursor: positioned at the action point, offset by the panel
            // chrome so the fractions map to the VIEWPORT the screenshot was
            // taken of — not to the panel box, which includes the tab and
            // address bars. Resting: unchanged from the original centring.
            ...(isCursor
              ? {
                  left: `${cursor!.x * 100}%`,
                  top: `calc(${cursor!.y * 100}% + ${chromeInset}px)`,
                }
              : { top: `calc(50% + ${chromeInset / 2}px)` }),
            transform: "translate(-50%, -50%)",
            width: orbSize,
            // The travel itself. Eased, not linear: it leaves quickly and
            // settles into the target, which is what makes it read as the orb
            // ARRIVING somewhere rather than sliding on rails. Width is on the
            // same curve so the shrink and the journey are one gesture.
            transition: `left ${CURSOR_TRAVEL_MS}ms cubic-bezier(0.22, 1, 0.36, 1), `
              + `top ${CURSOR_TRAVEL_MS}ms cubic-bezier(0.22, 1, 0.36, 1), `
              + `width ${CURSOR_TRAVEL_MS}ms cubic-bezier(0.22, 1, 0.36, 1)`,
          }}
          aria-hidden="true"
        >
          <OrbCanvas
            glowColor={glowColor}
            // As the cursor, mode D — the magnetic-pull/spiral expression. It
            // draws the shells INWARD, which is what makes a small orb read as
            // a directed pointer instead of a shrunken ball.
            breathMode={isCursor ? "D" : state === "dispersing" ? "C" : "D"}
            breathLevel={isCursor ? 0.7 : state === "dispersing" ? 0.5 : 0.3}
            isBreathing
            glowActive={isCursor || state === "loading"}
            animationMode={isCursor ? "D" : state === "dispersing" ? "C" : null}
            animActive={isCursor || state === "dispersing"}
            glowScale={isCursor ? 1.15 : 1}
            size={orbSize}
            // Same cadence as the border comet: the ring completes one lap of
            // the card in lapMs, so the outer shell completes one revolution
            // in lapMs too. The default 28 s made the orb drift while the
            // border raced, reading as two unrelated animations. lapMs is the
            // live crawl-derived value, and OrbCanvas integrates phase, so it
            // can move without snapping the particles.
            orbitPeriodMs={orbPeriodEffective}
          />

          {/* Dispersion ring — the orb reaching out to touch the page.
              CSS-animated on purpose: the previous revision decayed a useRef
              inside setInterval, which never re-renders, so this never drew. */}
          {state === "dispersing" && (
            <span
              className="absolute left-1/2 top-1/2 rounded-full iris-nav-touch"
              style={{
                width: ORB_SIZE,
                height: ORB_SIZE,
                border: `1px solid ${tint(glowColor, "44")}`,
                background: `radial-gradient(circle, ${tint(glowColor, "22")} 0%, transparent 70%)`,
              }}
            />
          )}
        </div>
      )}

      {/* ONE micro line, under the orb — the only text the overlay shows. */}
      {showOrb && subGoalLine && (
        <div
          className="absolute left-1/2 whitespace-nowrap text-[10px] font-mono tracking-wide text-white/80 max-w-[80%] truncate rounded-full px-2.5 py-1"
          style={{
            top: `calc(50% + ${chromeInset / 2 + ORB_SIZE / 2 + 10}px)`,
            transform: "translateX(-50%)",
            // Its own backdrop — the line sits over arbitrary page content and
            // white-on-white is unreadable without it.
            background: "rgba(4,8,12,0.55)",
            border: `1px solid ${tint(glowColor, "22")}`,
            textShadow: `0 0 8px ${tint(glowColor, "66")}`,
          }}
          role="status"
          aria-live="polite"
        >
          {subGoalLine}
        </div>
      )}

      <style>{`
        @keyframes iris-nav-touch-ring {
          0%   { transform: translate(-50%, -50%) scale(0.85); opacity: 0.85; }
          100% { transform: translate(-50%, -50%) scale(3.2);  opacity: 0; }
        }
        .iris-nav-touch {
          transform: translate(-50%, -50%);
          animation: iris-nav-touch-ring 1400ms cubic-bezier(0.16, 1, 0.3, 1) infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          .iris-nav-touch { animation: none; opacity: 0.25; }
        }
      `}</style>
    </div>
  )
})
