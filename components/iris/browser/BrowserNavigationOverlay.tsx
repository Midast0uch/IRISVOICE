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
/**
 * REQ-8 AC3 (REVISED — user feedback round 1): the escalation "notice" beat
 * no longer shifts violet. The eye goes BLACK↔WHITE: canvas wash/streams lift
 * to soft white, hexes run a grayscale gradient around the border (bright
 * fading to dark by arc position), and the DOM notice ring wears a
 * white→black linear gradient. Violet was rejected at sign-off.
 */
const NOTICE_SOFT_WHITE = "#e8e8e8"
/**
 * REQ-8 AC3 (REVISED — user feedback round 10): the notice beat holds ~1s
 * longer than the original 1600ms so the black↔white treatment gets read
 * before the regular crawl grammar resumes.
 */
const NOTICE_DURATION_MS = 2600

/**
 * Hex-lattice palette (user sign-off feedback round 1, REVISED round 2):
 * cells alternate across FOUR color sets — white, a light glow blend, the
 * glow color itself, and a deep glow shade — so the band reads as a woven
 * pattern rather than one flat hue. The traveling-head treatment was
 * rejected: hexes must NOT orbit the border like the comet streams.
 */
const HEX_WHITE = "#ffffff"

/**
 * Kick-pulse lifetime in ms — deliberately EQUAL to the shutter impulse decay
 * (both clocks are the same page-landing event). Used by drawHexScan (wavefront
 * sweep) and the draw loop (stream suppression window), so the two never
 * disagree about whether a pulse is alive.
 */
const HEX_PULSE_MS = 620

/**
 * Mesh-film preference (user-directed 2026-08-24). Exported so the simulator
 * toggles the SAME key the overlay reads — one source of truth, no dev-only
 * code path. The event is a preference-changed notification within the tab
 * (localStorage's native `storage` event only fires in OTHER tabs).
 */
export const MESH_PREF_KEY = "iris-hex-mesh-v1"
export const MESH_PREF_EVENT = "iris:hex_mesh_pref"

/**
 * Per-ring delay inside a mesh patch, as a fraction of the cell's life cycle.
 * This is what makes a comb BRANCH: the seed cell lights, one grid step out
 * follows, then the next. At 0 every cell in a patch shares a phase and the
 * whole comb snaps in and out as a block.
 */
const MESH_RING_STAGGER = 0.035

/**
 * How far ahead a cell at the border sits versus one at the centre, as a
 * fraction of the cycle. Makes growth read as pushed inward from the border
 * band on each kick. Small on purpose: this is a fixed offset baked into each
 * cell, NOT an animated wavefront — an animated one over the same quantity is
 * what made the film funnel toward the centre.
 */
const MESH_DEPTH_LEAD = 0.1

/**
 * Mesh wave shape (user revision 8). Each kick-pulse shutter launches ONE wave
 * that travels from the boundary inward; several are in flight at once, so
 * waves visibly follow one another in and fill the surface.
 *
 * All widths are in WAVE UNITS — the same 0..1 scale the front sweeps, where
 * 0 is the boundary and 1 the centre. A wall's `arrival` is its position on
 * that scale; `u = front - arrival` is how long the wave has been past it.
 */
// BAND vs SPACING is the governing relationship (user revision 9 REVERSED the
// target). Consecutive fronts sit MESH_WAVE_MIN_GAP_MS / MESH_WAVE_MS apart in
// wave units. A band NARROWER than that leaves visible dark gaps and reads as
// distinct marching rings — which was the previous tuning and is what "too many
// waves, I shouldn't see the spacing" rejects. The band is now deliberately
// WIDER than the spacing so consecutive waves overlap into continuous comb.
//
// Saturation is held off by throttling the LAUNCH RATE instead: fewer waves,
// each wider. Note the earlier 100%-lit failure came from a band twice the
// spacing at a 620ms launch rate — the fix is fewer launches, not a thin band.
const MESH_WAVE_MS = 2600 // boundary -> centre travel time for one wave
const MESH_WAVE_DRAW = 0.05 // how long a single wall takes to trace itself in
// Band total is what governs overlap; HOW it splits between hold and fade
// governs how much GRADIENT survives. At hold 0.12 / fade 0.28 the lattice sat
// 62% at full alpha — overlapping correctly but visually flat. Moving most of
// the band into the fade keeps the same total (no gaps) while leaving a long
// brightness ramp behind each front, so the waves stay readable in a filled field.
const MESH_WAVE_HOLD = 0.06 // fully drawn and steady after tracing
const MESH_WAVE_FADE = 0.34 // then fades out over this, leaving the trail
/**
 * Minimum time between wave launches. Kicks arriving sooner are absorbed into
 * the wave already travelling. THIS is the wave-count control, not eviction:
 * dropping a wave from the buffer mid-life would blank every wall it still lit,
 * a visible pop. Throttling the launch means a wave always lives out its span.
 */
const MESH_WAVE_MIN_GAP_MS = 1100
/** Spread of ignition across a patch, so a comb assembles seed-first. */
const MESH_PATCH_SPREAD = 0.09
/** Scatter between patches, so they do not ignite along one contour line. */
const MESH_PATCH_JITTER = 0.05
/**
 * Warps the wave's iso-contours. depth01 is distance to the nearest EDGE, whose
 * contours are concentric RECTANGLES — so without this a front collapses as a
 * square as it nears the middle. Must stay a good fraction of the patch spread
 * to actually break the shape; too small and the square reappears.
 */
const MESH_CONTOUR_NOISE = 0.16
/** How much dimmer the deepest walls are, so the centre never sharpens up. */
const MESH_DEPTH_SOFTEN = 0.4
/**
 * Wave lifetime, past which every wall it lit has finished fading. The leading
 * 1 is depth's own ceiling; contour noise, patch jitter and patch spread all
 * stack ON TOP of it in `arrival`, so they must be counted here too.
 * Under-counting retires a wave while walls it lit are still mid-fade, which
 * blanks them instantly. Derived, not hand-tuned, so it cannot drift out of
 * step when any of those terms is adjusted.
 */
const MESH_WAVE_LIFE =
  1 +
  MESH_CONTOUR_NOISE +
  MESH_PATCH_JITTER +
  MESH_PATCH_SPREAD +
  MESH_WAVE_DRAW +
  MESH_WAVE_HOLD +
  MESH_WAVE_FADE
/**
 * Safety cap only. With the launch throttle above, the natural population is
 * MESH_WAVE_LIFE * MESH_WAVE_MS / MESH_WAVE_MIN_GAP_MS ~= 4, so this should
 * never actually bite; it exists so a pathological shutter stream cannot grow
 * the buffer without bound.
 */
const MESH_MAX_WAVES = 6

/** Mesh cell radius as a multiple of the border band's, so cells can be sized
 * independently of the band. The lattice pitch is derived from the RESULT, or
 * walls stop being shared. */
const MESH_CELL_SCALE = 1.4

/** Component-wise hex color mix (t=0 → a, t=1 → b). Inputs are #rrggbb. */
function mixHex(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const r = Math.round(((pa >> 16) & 255) * (1 - t) + ((pb >> 16) & 255) * t)
  const g = Math.round(((pa >> 8) & 255) * (1 - t) + ((pb >> 8) & 255) * t)
  const bl = Math.round((pa & 255) * (1 - t) + (pb & 255) * t)
  return `#${((1 << 24) | (r << 16) | (g << 8) | bl).toString(16).slice(1)}`
}

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
  /**
   * REQ-9: the headless viewport's pixel size for the current action. When
   * present (and the box is measured), the action point is letterbox-mapped
   * through the aspect difference instead of naively stretched.
   */
  visionViewportW?: number
  visionViewportH?: number
  /**
   * REQ-8: whether the CURRENT vision session took over from a FAILED crawl.
   * A new escalated action fires the one-shot "notice" beat (throttled 5s).
   */
  visionEscalated?: boolean
}

/**
 * REQ-9 AC1: letterbox-aware mapping of a source-viewport fraction onto the
 * frame box. A 16:9 headless viewport shown in a taller box letterboxes
 * vertically — a naive stretch pushes points toward the top/bottom edges.
 * Pure function; no allocation beyond the return value (OPT GATE, T8).
 */
export function mapPoint(
  x: number,
  y: number,
  vw?: number,
  vh?: number,
  boxW?: number,
  boxH?: number,
): { x: number; y: number } {
  if (!vw || !vh || !boxW || !boxH || boxW <= 0 || boxH <= 0) return { x, y }
  const srcAspect = vw / vh
  const boxAspect = boxW / boxH
  if (Math.abs(srcAspect - boxAspect) < 0.01) return { x, y }
  if (srcAspect > boxAspect) {
    // Source wider than box: fitted by width -> vertical letterbox band.
    const band = boxAspect / srcAspect
    return { x, y: (y - 0.5) * band + 0.5 }
  }
  // Source taller than box: fitted by height -> horizontal letterbox band.
  const band = srcAspect / boxAspect
  return { x: (x - 0.5) * band + 0.5, y }
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
  visionViewportW,
  visionViewportH,
  visionEscalated = false,
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

  // REQ-9: measured box (layout px) for letterbox-aware cursor mapping.
  // Updated via ResizeObserver — the same element the overlay traces.
  const [boxSize, setBoxSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 })
  useEffect(() => {
    const el = rootRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(() => {
      setBoxSize((prev) => {
        const w = el.offsetWidth
        const h = el.offsetHeight
        return prev.w === w && prev.h === h ? prev : { w, h }
      })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // REQ-8: the "notice" beat — one-shot on a NEW escalated action, throttled
  // to 5s. `noticeSeq` re-keys the expanding ring; `noticeUntilRef` is read
  // per frame by the draw loop (violet shift + aperture hold + scan boost).
  const noticeUntilRef = useRef<number>(0)
  const lastNoticeStepRef = useRef<number>(0)
  const [noticeSeq, setNoticeSeq] = useState(0)
  const [noticeActive, setNoticeActive] = useState(false)
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // A NEW action (step changed) moves the cursor and pushes the old point onto
  // the trail. Gated on the step rather than on the coordinates so a repeated
  // action at the same spot still registers as a fresh beat, and so an action
  // WITHOUT a point (scroll) holds position instead of teleporting to 0,0.
  useEffect(() => {
    if (!visionStep || visionStep === lastStepRef.current) return
    lastStepRef.current = visionStep
    // REQ-8 AC1: every vision action is an act of attention — fire the SAME
    // blink impulse a fetched page fires.
    shutterRef.current = 1
    // REQ-8 AC3: escalation provenance -> one-shot notice beat (5s throttle).
    if (visionEscalated && Date.now() - lastNoticeStepRef.current > 5000) {
      lastNoticeStepRef.current = Date.now()
      noticeUntilRef.current = Date.now() + NOTICE_DURATION_MS
      setNoticeSeq(s => s + 1)
      if (!prefersReducedMotion) {
        setNoticeActive(true)
        if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
        noticeTimerRef.current = setTimeout(() => setNoticeActive(false), NOTICE_DURATION_MS)
      }
    }
    if (typeof visionX !== "number" || typeof visionY !== "number") return
    // REQ-9 AC1: aspect-correct the point through the source viewport before
    // it becomes a box fraction. Missing dims -> naive mapping (AC2).
    const pt = mapPoint(visionX, visionY, visionViewportW, visionViewportH, boxSize.w, boxSize.h)
    setCursor((prev) => {
      if (prev) {
        setTrail((t) => [{ ...prev, k: 1 }, ...t].slice(0, CURSOR_TRAIL_LEN))
      }
      return pt
    })
  }, [visionStep, visionX, visionY, visionViewportW, visionViewportH, visionEscalated, boxSize.w, boxSize.h])

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

  // ── REQ-8: the hex-lattice scan (the eye READING) ────────────────────────
  // Geometry is precomputed in measure() into ONE flat typed array
  // ([x, y, arcPos, angle] × N) — rebuilt only on resize, zero per-frame
  // allocation (OPT GATE, T9). scanAlpha eases toward "is a vision session
  // interacting" so the lattice fades out over ~a lap when actions stop:
  // scanning always MEANS reading, never decorates.
  const hexRef = useRef<Float32Array | null>(null)
  const hexCountRef = useRef(0)
  const scanAlphaRef = useRef(0)
  // Kick-pulse lattice (user feedback round 3, Option 1): hexes rest dark and
  // pulse outward through the band on the SHUTTER's own clock. Geometry params
  // are derived from cell spacing in measure() so size and stacking agree.
  const hexGeomRef = useRef<{ radius: number; rows: [number, number] } | null>(null)
  // Full-surface mesh field (user-directed 2026-08-24). Packed [x, y, depth01,
  // radius] per cell, rebuilt only on resize — same discipline as the band.
  const meshRef = useRef<Float32Array | null>(null)
  const meshCountRef = useRef(0)
  // ON by default (user sign-off 2026-08-24). The film is now part of the
  // browser reading grammar, not an experiment: absence of the preference means
  // ENABLED, and the key exists only so it can be switched OFF — for A/B
  // comparison in the simulator, or by a user who does not want it.
  const meshEnabledRef = useRef(true)
  /**
   * Waves in flight. Each kick-pulse shutter launches one from the boundary;
   * several coexist, which is what makes them visibly follow one another
   * inward. Oldest is evicted at MESH_MAX_WAVES.
   */
  const meshWavesRef = useRef<{ start: number; strength: number; outward: boolean }[]>([])
  const meshPrevShutterRef = useRef(0)
  /** Launch counter — decides which waves run outward instead of inward. */
  const meshWaveSeqRef = useRef(0)
  /** Largest arrival in the lattice, so an outward wave can mirror against it. */
  const meshArrivalMaxRef = useRef(1)
  /** Uniform mesh cell radius — no per-cell taper (user revision 2026-08-24). */
  const meshRadiusRef = useRef(0)
  /**
   * Unique lattice walls, packed [x1, y1, x2, y2, phase, t0]. One entry per
   * SHARED wall, not six per cell — see the dedup note in measure(). This is
   * what the film actually draws; the cell array only seeds it.
   */
  const meshEdgesRef = useRef<Float32Array | null>(null)
  /** Wall length in px — the dash period used to trace an edge. */
  const meshEdgeLenRef = useRef(0)
  const hexPulseRef = useRef<{ start: number; strength: number }>({ start: 0, strength: 0 })
  const hexPrevShutterRef = useRef(0)
  const visionActionRef = useRef<string>(visionAction)
  const cursorRef = useRef<{ x: number; y: number } | null>(null)
  const reducedRef = useRef<boolean>(!!prefersReducedMotion)
  visionActionRef.current = visionAction
  cursorRef.current = cursor
  reducedRef.current = !!prefersReducedMotion

  stateRef.current = state
  colorRef.current = glowColor
  chromeRef.current = chromeInset

  // Mesh-film preference (user-directed 2026-08-24, under evaluation).
  //
  // Deliberately a PREFERENCE, not an event. The simulator's whole value is
  // that it drives the same iris:* crawler events production drives; adding a
  // simulator-only event to switch a visual on would be exactly the kind of
  // divergence between simulation and real behavior this surface exists to
  // prevent. A preference is read identically in both, so what is signed off
  // in the simulator is what ships.
  useEffect(() => {
    const read = () => {
      try {
        // Opt-OUT: only an explicit "0" disables it. An absent key (first run,
        // cleared storage, a fresh profile) means the film is on, which is what
        // makes it standard behavior rather than something to be discovered.
        meshEnabledRef.current = localStorage.getItem(MESH_PREF_KEY) !== "0"
      } catch {
        meshEnabledRef.current = true // storage unavailable -> standard behavior
      }
    }
    read()
    window.addEventListener(MESH_PREF_EVENT, read)
    return () => window.removeEventListener(MESH_PREF_EVENT, read)
  }, [])

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

      // REQ-8 AC4 (REVISED — user feedback round 3): hex-lattice geometry.
      // Proper honeycomb stacking: the hex circumradius is DERIVED from the
      // perimeter spacing (R = ds/√3, so flat-to-flat width == ds and
      // neighbouring columns touch exactly), and the second row nests at
      // 1.5·R inward with a ds/2 arc offset — cells stack into each other
      // instead of layering on top. Rebuilt ONLY here (resize).
      const cells: number[] = []
      const ds = Math.max(10, path.perim / 160)
      const hexR = ds / Math.sqrt(3)
      const row0 = 7
      const row1 = 7 + 1.5 * hexR
      const rows: [number, number] = [row0, row1]
      for (let d = 0; d < path.perim; d += ds) {
        for (let r = 0; r < rows.length; r++) {
          const dd = d + (r === 1 ? ds / 2 : 0)
          const p = path.at(dd)
          const nx = W / 2 - p.x
          const ny = H / 2 - p.y
          const len = Math.hypot(nx, ny) || 1
          cells.push(
            p.x + (nx / len) * rows[r],
            p.y + (ny / len) * rows[r],
            dd,
            Math.atan2(p.y - H / 2, p.x - W / 2),
          )
        }
      }
      hexRef.current = Float32Array.from(cells)
      hexCountRef.current = cells.length / 4
      hexGeomRef.current = { radius: hexR, rows }

      // ── REQ-8 (mesh film, user-directed 2026-08-24) ───────────────────────
      // The band above hugs the PERIMETER. This second field carries the same
      // honeycomb grammar ACROSS THE WHOLE SURFACE so the panel reads as a thin
      // mesh the pulse propagates through, rather than a lit edge.
      //
      // NO FUNNEL (user revision 2026-08-24). Cells are ONE uniform size across
      // the whole surface — the earlier depth-scaled taper read as a perspective
      // tunnel, which pulled the eye to the centre. What travels inward is the
      // PULSE, not the geometry.
      //
      // SCALES, NOT A GRID. A perfect honeycomb reads as graph paper, so the
      // field is thinned at build time by a deterministic per-cell hash: about a
      // quarter of the lattice sites are simply absent. Combined with the
      // clustered ignition in drawHexMesh, lit cells clump into irregular
      // patches with gaps between them — hexes grouped but disjointed, like
      // scales growing over the surface rather than a uniform screen.
      //
      // Built ONCE per resize, like the band. Rows are laid on a proper
      // odd-row-offset honeycomb (dx = √3·R, dy = 1.5·R, odd rows shifted by
      // dx/2). Cells inside the band's footprint are dropped so the two fields
      // never overdraw each other. Packed [x, y, phase01, reserved].
      const mesh: number[] = []
      const raw: number[] = []
      // CELL RADIUS == THE TILING RADIUS, EXACTLY (user revision 7).
      //
      // This must not be nudged. The grid pitch is a true pointy-top honeycomb
      // (dx = √3·R, dy = 1.5·R, odd rows offset dx/2), so at EXACTLY R the six
      // vertices of neighbouring cells coincide and adjacent hexes SHARE a
      // wall. The edge dedup below — the whole basis of the traced-outline
      // growth — depends on that coincidence.
      //
      // Measured: at 1.00·R, 6018 emitted walls collapse to 3905 unique (35%
      // shared). At 0.94·R — a hairline gap that earlier looked nicer for
      // stroked cells — NOTHING collapses (0%), every cell keeps its own
      // private boundary, and growth can never cross from one cell to the
      // next. A "nearly touching" lattice is not a connected one.
      // The mesh lattice is its OWN honeycomb, no longer pinned to the band's
      // pitch — MESH_CELL_SCALE makes its cells larger. What must hold is that
      // the PITCH BELOW is derived from meshR (not hexR): a lattice is only
      // self-consistent, and its walls only shared, when spacing matches the
      // radius it is drawn at. Scaling the radius while leaving the pitch on
      // hexR would silently break the dedup and every cell would go private
      // again.
      const meshR = hexR * MESH_CELL_SCALE
      // Coarse bucket for CONTIGUOUS patches. Sized so a bucket holds a handful
      // of ADJACENT cells — that adjacency is what makes a lit bucket a comb
      // rather than scattered confetti. Must be SEVERAL grid pitches wide, or a
      // bucket holds one or two cells and lights as a speck (at 2.6 they
      // averaged 2.2 cells and read as disconnected dots). Scaled with meshR so
      // combs keep their cell count as cells grow; 5 rather than 7 gives MORE,
      // smaller combs, which is what makes the surface read as many clusters.
      const CLUSTER_PX = meshR * 5
      // Start the field as close to the band as it can sit without overdrawing
      // it, so the innermost mesh cells read as the NEXT COURSE of the border
      // lattice rather than a separate decoration floating inside it. Band row
      // 1 is centred at rows[1] and extends hexR further in; a mesh cell needs
      // its own radius (0.94·hexR) of clearance beyond that.
      const innerEdge = rows[1] + hexR + meshR
      // The deepest a cell can sit from the nearest edge — half the SHORT side.
      // Used ONLY for the static density falloff and a fixed phase lead below.
      // It is never swept: a MOVING front over this quantity is precisely what
      // produced the funnel, and nothing animates it.
      const maxReach = Math.max(1, Math.min(W, H) / 2)
      const mdx = Math.sqrt(3) * meshR
      const mdy = 1.5 * meshR
      let rowIdx = 0
      let siteIdx = 0
      for (let my = mdy; my < H; my += mdy, rowIdx++) {
        const off = rowIdx % 2 === 1 ? mdx / 2 : 0
        let colIdx = -1
        for (let mx = off + mdx / 2; mx < W; mx += mdx, siteIdx++) {
          colIdx += 1
          // Distance to the nearest panel edge — 0 at the frame, large at centre.
          const edgeDist = Math.min(mx, W - mx, my, H - my)
          if (edgeDist < innerEdge) continue // the band already owns this ring
          // FULL, UNTHINNED lattice: the field is an ORDERED grid covering the
          // whole surface. Irregularity comes from WHICH cells are visible at
          // any instant, never from holes in the grid.
          //
          // Pass 1 collects raw sites; the phase needs each patch's seed, which
          // is not known until the patch is complete. Packed [x, y, cKey, keep].
          const cKey =
            ((Math.floor(mx / CLUSTER_PX) * 73856093) ^
              (Math.floor(my / CLUSTER_PX) * 19349663)) >>> 0
          // DENSITY FALLOFF BY DEPTH (user revision 6): thick and plentiful
          // against the border, thinning to sparse and disconnected toward the
          // middle — combs look like they grew OUT of the band and ran out of
          // steam. This is a STATIC property of the lattice, decided once here;
          // nothing sweeps it, so it cannot become the funnel again.
          const depth01 = Math.min(
            1,
            (edgeDist - innerEdge) / Math.max(1, maxReach - innerEdge),
          )
          // 96% of sites survive at the band, ~34% at the centre. The trails
          // only draw between two LIT neighbours, so thinning the field also
          // thins the connections — which is what makes the middle read as
          // less connected without any extra rule.
          // Raised (user revision 9: "more comb clusters, shouldn't see the
          // spacing between them"). Was 96 -> 34 across the depth, which left
          // visible dark holes inside combs; now near-solid at the boundary and
          // still thinning inward, so patches read as continuous honeycomb that
          // merges with its neighbours rather than as separated islands.
          const keepPct = 100 - 30 * depth01
          const keep =
            (((siteIdx * 2654435761) ^ (rowIdx * 40503)) >>> 0) % 100 < keepPct ? 1 : 0
          raw.push(mx, my, cKey, keep, rowIdx, colIdx, depth01)
        }
      }

      // ── Pass 2: BRANCHING GROWTH ORDER (user revision 4) ──────────────────
      // Cells in a patch must NOT share one phase. That made every comb snap in
      // and out as a rigid block — "stuck together". Instead each patch gets a
      // SEED (its centroid cell) and every other cell is delayed in proportion
      // to how many grid steps it sits from that seed. The patch therefore
      // GROWS outward, neighbour from neighbour, and dissolves in the same
      // order, so cells plainly appear and vanish at different times while
      // still belonging visibly to one comb.
      //
      // This also supplies the uniformity that pure randomness could not: the
      // order of appearance is structural (ring by ring), not a coin flip per
      // cell, so growth reads as branching rather than as noise.
      const sums = new Map<number, { x: number; y: number; n: number }>()
      for (let i = 0; i < raw.length; i += 7) {
        if (raw[i + 3] === 0) continue
        const key = raw[i + 2]
        const acc = sums.get(key)
        if (acc) {
          acc.x += raw[i]
          acc.y += raw[i + 1]
          acc.n += 1
        } else {
          sums.set(key, { x: raw[i], y: raw[i + 1], n: 1 })
        }
      }
      // One ring == one grid step out from the seed.
      const ringPx = Math.max(1, mdy)
      // row,col -> mesh cell index, for stitching neighbour links below.
      const siteAt = new Map<number, number>()
      for (let i = 0; i < raw.length; i += 7) {
        const mx = raw[i]
        const my = raw[i + 1]
        const cKey = raw[i + 2]
        const acc = sums.get(cKey)
        const ph = ((cKey * 2246822519) >>> 0) % 1000
        let ring = 0
        if (acc && acc.n > 0) {
          ring = Math.round(Math.hypot(mx - acc.x / acc.n, my - acc.y / acc.n) / ringPx)
        }
        // SIGN MATTERS. Life advances as `elapsed/LIFE + phase`, so a LARGER
        // phase reaches the visible window SOONER. Adding the ring delay
        // therefore made outer rings lead and the comb collapse toward its
        // seed — read as "disappearing inward". SUBTRACTING it puts the seed
        // first, so the patch grows outward from its centre and releases
        // outward too.
        // DEPTH LEAD (user revision 6): cells nearest the band reach the
        // visible window first, so each kick appears to push growth inward FROM
        // the border lattice. Larger phase = sooner, so depth is SUBTRACTED.
        // Deliberately small — this is a fixed per-cell offset, not a sweeping
        // front, and the density falloff means it peters out rather than
        // arriving at the centre as a ring.
        const phase =
          (1 +
            (ph / 1000 -
              ring * MESH_RING_STAGGER -
              raw[i + 6] * MESH_DEPTH_LEAD)) %
          1
        const idx = mesh.length / 4
        siteAt.set(raw[i + 4] * 4096 + raw[i + 5], idx)
        mesh.push(mx, my, phase, raw[i + 3])
      }
      meshRef.current = Float32Array.from(mesh)
      meshCountRef.current = mesh.length / 4
      meshRadiusRef.current = meshR

      // ── Pass 3: SHARED-EDGE LATTICE (user revision 7) ─────────────────────
      // THE DRAWN THING IS NOW THE EDGE, NOT THE CELL. Filling/stroking whole
      // hexes can only ever read as cells BLINKING: each is an independent
      // unit that appears and vanishes on its own. An organism creeps — its
      // outline extends from what already exists. So the lattice is decomposed
      // into unique undirected EDGES, and each edge draws ITSELF over time via
      // setLineDash/lineDashOffset, starting when the growth front reaches it.
      //
      // DEDUPLICATION IS THE POINT. Neighbouring hexes SHARE a wall. Emitting
      // six edges per cell would double-draw every interior wall and, worse,
      // would let one copy be growing while the other was already drawn. One
      // edge per wall means a wall is a single object two cells have in common
      // — which is exactly what makes growth cross from cell to cell instead
      // of each cell drawing its own private boundary.
      //
      // Vertices are quantised to 0.1px before keying so the two cells that
      // meet at a wall agree on its identity despite float drift.
      const patchMax = new Map<number, number>()
      for (let i = 0; i < raw.length; i += 7) {
        if (raw[i + 3] === 0) continue
        const acc = sums.get(raw[i + 2])
        if (!acc || acc.n === 0) continue
        const d = Math.hypot(raw[i] - acc.x / acc.n, raw[i + 1] - acc.y / acc.n)
        const prev = patchMax.get(raw[i + 2])
        if (prev === undefined || d > prev) patchMax.set(raw[i + 2], d)
      }

      const edgeAt = new Map<string, number>()
      const edges: number[] = []
      const q = (v: number) => Math.round(v * 10)
      for (let i = 0; i < raw.length; i += 7) {
        if (raw[i + 3] === 0) continue
        const mx = raw[i]
        const my = raw[i + 1]
        const cKey = raw[i + 2]
        const acc = sums.get(cKey)
        const ph = ((cKey * 2246822519) >>> 0) % 1000
        let ring = 0
        let t0 = 0
        if (acc && acc.n > 0) {
          const dist = Math.hypot(mx - acc.x / acc.n, my - acc.y / acc.n)
          ring = Math.round(dist / ringPx)
          // Normalised distance from the patch seed: 0 at the seed, 1 at the
          // rim. This is the growth ORDER — the front sweeps it 0 -> 1.
          t0 = Math.min(1, dist / Math.max(1, patchMax.get(cKey) || 1))
        }
        // ARRIVAL (user revision 8) — WHERE IN A WAVE'S TRAVEL THIS WALL IS
        // REACHED, expressed in the same 0..1 units the wave front sweeps.
        // Replaces the old free-running per-cell phase entirely: cells no
        // longer live on private clocks that happen to overlap, they are
        // reached by a front that starts at the boundary and moves inward.
        //
        // Three terms, in order of magnitude:
        //   depth01        — dominant. Boundary first, centre last. THIS is
        //                    what makes each wave travel inward.
        //   patch jitter   — so neighbouring patches do not all ignite on the
        //                    same contour line, which would read as a ring.
        //   t0 * spread    — within a patch, the seed is reached before its
        //                    rim, so a comb ASSEMBLES from its middle outward
        //                    as the wave crosses it rather than snapping on.
        //   contour noise — kills the SQUARE. depth01 is distance to the
        //     NEAREST EDGE, whose iso-contours are concentric rectangles, so a
        //     front sweeping it necessarily collapses as a rectangle and reads
        //     as a square funnel near the middle. Adding a smooth, non
        //     axis-aligned field to the arrival warps those contours into
        //     irregular lobes. The two trig terms use different, mutually
        //     prime-ish frequencies on x and y and are MULTIPLIED, so the
        //     result has no horizontal or vertical grain for the eye to lock
        //     onto — which a single sin(x)+sin(y) would have had.
        const nz =
          0.5 +
          0.5 *
            Math.sin(mx * 0.021 + my * 0.013) *
            Math.cos(mx * 0.009 - my * 0.017)
        const arrival =
          raw[i + 6] +
          nz * MESH_CONTOUR_NOISE +
          (ph / 1000) * MESH_PATCH_JITTER +
          t0 * MESH_PATCH_SPREAD
        for (let v = 0; v < 6; v++) {
          const a1 = (Math.PI / 3) * v + Math.PI / 6
          const a2 = (Math.PI / 3) * ((v + 1) % 6) + Math.PI / 6
          const x1 = mx + Math.cos(a1) * meshR
          const y1 = my + Math.sin(a1) * meshR
          const x2 = mx + Math.cos(a2) * meshR
          const y2 = my + Math.sin(a2) * meshR
          // Order-independent key so both owners of a wall produce the same one.
          const ka = `${q(x1)},${q(y1)}`
          const kb = `${q(x2)},${q(y2)}`
          const key = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`
          const seen = edgeAt.get(key)
          if (seen === undefined) {
            edgeAt.set(key, edges.length / 6)
            edges.push(x1, y1, x2, y2, arrival, raw[i + 6])
          } else {
            // A shared wall belongs to whichever side the wave reaches FIRST,
            // so growth flows into the neighbour rather than stalling at a
            // seam — this is what lets separate combs knit together.
            const o = seen * 6
            if (arrival < edges[o + 4]) {
              edges[o + 4] = arrival
              edges[o + 5] = raw[i + 6]
            }
          }
        }
      }
      meshEdgesRef.current = Float32Array.from(edges)
      meshEdgeLenRef.current = meshR // hex side length == circumradius
      // Mirror point for outward waves. Measured from the real lattice rather
      // than assumed, since arrival carries noise/jitter/spread on top of depth.
      let aMax = 1
      for (let e = 4; e < edges.length; e += 6) if (edges[e] > aMax) aMax = edges[e]
      meshArrivalMaxRef.current = aMax
    }
    measure()

    const ro = new ResizeObserver(measure)
    ro.observe(root)

    const t0 = Date.now()

    /** Rounded-rect stroke path at inset `o` with CONCENTRIC corner radius.
     * A ring parallel to the card border must shrink its corner radius by the
     * inset (same arc centre, radius r − o) — using the card's own radius was
     * what threw the bottom corners off the iframe edge. */
    function ringPath(o: number, rad: number) {
      ctx.beginPath()
      ctx.moveTo(rad + o, o)
      ctx.arcTo(W - o, o, W - o, H - o, rad)
      ctx.arcTo(W - o, H - o, o, H - o, rad)
      ctx.arcTo(o, H - o, o, o, rad)
      ctx.arcTo(o, o, W - o, o, rad)
      ctx.closePath()
    }

    /**
     * Inward wash — SINGLE RING with attached inner shadow (user feedback
     * round 9). The separate shadow ring was rejected: scaling its position
     * with the snap disconnected it from the colour ring on every kick. Now
     * there is ONE ring at ONE centreline, stroked TWICE:
     *
     *   pass 1 · SHADOW — the same path, ~1.7× wider, dark: only its inner
     *                     rim peeks out past the colour, reading as a
     *                     uniform inward shadow ATTACHED to the ring.
     *   pass 2 · COLOUR — the shutter light, flush at the frame edge,
     *                     swelling and brightening on each kick pulse.
     *
     * Identical centreline + identical corner radius = the shadow can never
     * drift, gap, or disconnect, at rest or mid-pulse.
     *
     * HOT PATH: two strokes of the same path per frame while crawling.
     */
    function drawEdgeWash(color: string, k: number, elapsed: number) {
      const breath = 0.5 + 0.5 * Math.sin((elapsed / PULSE_DURATION) * Math.PI * 2)
      // Ease the impulse so the close is fast and the re-open is soft.
      const snap = shutterRef.current * shutterRef.current
      const depth = Math.min(Math.max(Math.min(W, H) * 0.12, 20), 72)
      const r = path.r

      const lw = Math.max(2, depth * 0.28) * (1 + 0.35 * snap)
      const c = lw / 2
      const rad = Math.max(2, r - c)

      // Pass 1 · the inward shadow — wider under-stroke, same centreline.
      ctx.save()
      ctx.globalCompositeOperation = "source-over"
      ctx.strokeStyle = "#04080c"
      ctx.lineWidth = lw * 1.7
      ctx.shadowColor = "#04080c"
      ctx.shadowBlur = depth * 0.35
      ctx.globalAlpha = (0.14 + 0.10 * snap) * k
      ringPath(c, rad)
      ctx.stroke()
      ctx.restore()

      // Pass 2 · the colour ring on top — the shutter's light.
      ctx.save()
      ctx.globalCompositeOperation = "lighter"
      ctx.strokeStyle = color
      ctx.lineWidth = lw
      ctx.shadowColor = color
      ctx.shadowBlur = depth * 0.45 * (1 + 0.5 * snap)
      ctx.globalAlpha = (0.28 + 0.12 * breath + 0.50 * snap) * k
      ringPath(c, rad)
      ctx.stroke()
      ctx.restore()
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

    /**
     * REQ-8 (REVISED — user feedback rounds 3+12): the border flash. On each
     * page landing the ENTIRE rounded border flashes at once and decays on
     * the shutter's 620ms clock. During the ESCALATION notice the same flash
     * renders as DARKNESS (`dark=true`): source-over instead of additive, so
     * a black pulse sweeps the boundary — same grammar, inverted polarity.
     *
     * HOT PATH: runs only while a shutter impulse is decaying (~620ms per
     * kick); shadowBlur paid for those frames alone. One stroke.
     */
    function drawBorderFlash(color: string, k: number, dark = false) {
      const imp = shutterRef.current
      if (imp <= 0.01) return // resting between kicks
      ctx.save()
      ctx.globalCompositeOperation = dark ? "source-over" : "lighter"
      const a = imp * imp * (dark ? 0.75 : 0.9) * k // ease-out flash
      ctx.globalAlpha = Math.min(0.9, a)
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5 + 4.5 * imp // swells with the flash peak
      ctx.shadowColor = color
      ctx.shadowBlur = 18 * imp
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

    // Hex palette cache — rebuilt only when the base color or notice state
    // changes, never per frame. Sets alternate LUMINANCE (bright white vs dim
    // glow), not just hue: under additive blending same-brightness colors
    // wash out (user feedback round 3).
    let hexStylesKey = ""
    let hexStyles: { color: string; mul: number }[] = [
      { color: HEX_WHITE, mul: 1 },
    ]

    /**
     * REQ-8 AC2 (REVISED — user feedback round 3, Option 1 "Kick Pulse"):
     * the hex-lattice scan — the eye READING. Cells rest DARK between page
     * landings. Each shutter impulse (page_fetched) fires a pulse whose
     * wavefront sweeps OUTWARD through the band over the same ~620ms the
     * shutter takes to decay — the border exhales with every page, locked to
     * the shutter's own clock. While a vision session interacts without page
     * landings (sustained scroll), a gentler pulse fires every ~900ms so
     * reading is still visible. No orbiting, no independent flutter.
     * Cursor-side bias and fade-when-actions-stop unchanged.
     */
    function drawHexScan(baseColor: string, k: number, elapsed: number, now: number) {
      if (reducedRef.current) return // AC6: static band only under reduced motion
      const hex = hexRef.current
      const n = hexCountRef.current
      const geom = hexGeomRef.current
      const target = visionActionRef.current ? 1 : 0
      scanAlphaRef.current += (target - scanAlphaRef.current) * 0.04
      const scanK = scanAlphaRef.current
      if (scanK < 0.01 || !hex || n === 0 || !geom) return
      const notice = now < noticeUntilRef.current

      // Pulse scheduling. Rising shutter edge = page landed = full pulse.
      const sh = shutterRef.current
      if (sh > hexPrevShutterRef.current + 0.12) {
        hexPulseRef.current = { start: now, strength: 1 }
      } else if (visionActionRef.current && now - hexPulseRef.current.start > 900) {
        hexPulseRef.current = { start: now, strength: 0.5 }
      }
      hexPrevShutterRef.current = sh

      const PULSE_MS = HEX_PULSE_MS
      const age = now - hexPulseRef.current.start
      const maxDepth = geom.rows[1] + 46
      const front = (age / PULSE_MS) * maxDepth
      if (age > PULSE_MS * 2.2) return // resting dark between pulses

      let biasA = -Math.PI / 2
      if (cursorRef.current) {
        biasA = Math.atan2(
          cursorRef.current.y * H - H / 2,
          cursorRef.current.x * W - W / 2,
        )
      }
      const cacheKey = `${baseColor}|${notice ? 1 : 0}`
      if (hexStylesKey !== cacheKey) {
        hexStylesKey = cacheKey
        hexStyles = [
          { color: HEX_WHITE, mul: 1 }, // bright white — pops
          { color: baseColor, mul: 0.4 }, // dim glow — recedes
          { color: mixHex(baseColor, "#ffffff", 0.6), mul: 0.7 }, // pale glow
          { color: baseColor, mul: 0.4 },
        ]
      }
      ctx.save()
      ctx.globalCompositeOperation = "lighter"
      const size = geom.radius
      for (let i = 0; i < n; i++) {
        const o = i * 4
        const x = hex[o]
        const y = hex[o + 1]
        const ang = hex[o + 3]
        // Rows alternate by construction (measure() emits r0,r1,r0,r1…).
        const depth = geom.rows[i % 2]
        if (front <= depth) continue // wavefront has not reached this row yet
        // Exponential falloff behind the wavefront — each row flashes then
        // decays as the pulse passes outward.
        const flash = Math.exp(-(front - depth) / 26)
        const shimmer = 0.75 + 0.25 * Math.sin(i * 1.7 + elapsed * 0.003)
        let bias = 1
        if (cursorRef.current) {
          let da = Math.abs(ang - biasA)
          if (da > Math.PI) da = 2 * Math.PI - da
          bias = 0.7 + 0.8 * Math.max(0, Math.cos(da))
        }
        const set = hexStyles[i % 4]
        // NOTICE — scattered black SPOTS on the white ring (user round 11):
        // a deterministic hash per (cell, ~350ms tick) re-rolls which hexes
        // are dark, so spots appear/disappear all over the band instead of
        // forming a repeating stripe. Black needs source-over to be visible
        // under what is otherwise additive blending.
        let fill = set.color
        let mul = set.mul
        if (notice) {
          const spotTick = Math.floor(elapsed / 350)
          const h = ((i * 2654435761) ^ (spotTick * 40503)) >>> 0
          const dark = h % 100 < 45 // ~45% of cells are spots at any tick
          fill = dark ? "#04060a" : HEX_WHITE
          mul = 1
        }
        const alpha =
          flash *
          hexPulseRef.current.strength *
          shimmer *
          bias *
          mul *
          0.9 *
          scanK *
          k
        if (alpha <= 0.02) continue
        ctx.fillStyle = fill
        if (notice) {
          ctx.globalCompositeOperation =
            fill === HEX_WHITE ? "lighter" : "source-over"
        }
        ctx.globalAlpha = Math.min(0.9, alpha)
        ctx.beginPath()
        for (let v = 0; v < 6; v++) {
          const a = (Math.PI / 3) * v + Math.PI / 6
          const px = x + Math.cos(a) * size
          const py = y + Math.sin(a) * size
          if (v === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.fill()
      }
      ctx.restore()
    }

    /**
     * MESH FILM (user-directed 2026-08-24) — the surface counterpart to
     * drawHexScan's border band.
     *
     * Same pulse clock, same hash-spot idiom, same honeycomb grammar: this is
     * an EXTENSION of the signed-off lattice, not a second animation system.
     * Three properties the user asked for, and where each lives:
     *
     *  - RECEDES IN AND OUT — IN BRIGHTNESS, NOT IN SPACE (revision 3). The
     *    pulse is a global swell: every kick lifts the whole film and lets it
     *    fall. An earlier version swept a wavefront from the border to the
     *    centre; because the depth it swept was distance-to-nearest-edge, that
     *    front was a rectangular ring collapsing inward and read unavoidably as
     *    a funnel. Nothing in this function is a function of position now.
     *  - UNIFORM SIZE. Cells are one size everywhere (revision 2026-08-24 — the
     *    original depth-taper read as a perspective tunnel and pulled the eye to
     *    the centre). Only the PULSE travels; the geometry never scales.
     *  - AN ORDERED GRID THAT BLINKS. The lattice is complete and regular; what
     *    varies is which cells are currently VISIBLE. Every cell runs the same
     *    fade cycle offset by its own stable phase, so at any instant a
     *    scattered subset is lit all over the frame while the rest are dark,
     *    each materialising and dissolving in place. No cell ever moves, spins
     *    or turns — only its alpha changes.
     *
     * Outlines, not fills: the user asked for a mesh FILM, so cells are
     * stroked at low alpha. Gated on vision/crawl activity, so a page being
     * read normally stays completely clean.
     */
    function drawHexMesh(baseColor: string, k: number, elapsed: number, now: number) {
      if (!meshEnabledRef.current) return
      if (reducedRef.current) return // AC6: no travelling motion under reduced motion
      const mesh = meshRef.current
      const n = meshCountRef.current
      if (!mesh || n === 0) return

      // ACTIVITY GATE. This is a WEBCRAWL visual first: a crawl fires
      // `crawler_page_fetched`, not `crawler_vision_action`, so gating on
      // `visionActionRef` alone (as this first did) meant the film never ran
      // during the very scenario it was designed for. Any reading state counts.
      const stNow = stateRef.current
      const active =
        stNow === "loading" ||
        stNow === "dispersing" ||
        stNow === "crawling" ||
        !!visionActionRef.current
      if (!active) return

      // ── WAVE LAUNCH (user revision 8) ────────────────────────────────────
      // Each kick-pulse shutter LAUNCHES A WAVE from the boundary. Waves are
      // not a brightness envelope over a field of independently blinking cells
      // (revisions 3-7) — they are travelling fronts, and several are alive at
      // once, so one visibly follows another inward and the surface fills.
      //
      // The launch edge is the band's own: `shutterRef` rising. It cannot ride
      // `hexPulseRef`, which is advanced INSIDE drawHexScan and never ticks
      // during a plain crawl (no vision action) — so the film schedules from
      // the same signal independently and stays in phase with the band.
      const shNow = shutterRef.current
      const waves = meshWavesRef.current
      const launch = (strength: number) => {
        if (waves.length >= MESH_MAX_WAVES) waves.shift()
        // Every third wave runs CENTRE -> BOUNDARY instead of inward. Two
        // reasons, both about the square: a purely inward cadence trains the
        // eye to expect the rectangular collapse and makes it more legible
        // each time, and an outward wave sweeps the contours in the opposite
        // order so the two never superimpose into one clean shape. It also
        // keeps the middle alive rather than only ever being the place waves
        // go to die.
        meshWaveSeqRef.current += 1
        waves.push({
          start: now,
          strength,
          outward: meshWaveSeqRef.current % 3 === 0,
        })
      }
      const sinceLast = waves.length === 0 ? Infinity : now - waves[waves.length - 1].start
      if (shNow > meshPrevShutterRef.current + 0.12 && sinceLast >= MESH_WAVE_MIN_GAP_MS) {
        launch(1) // page landed, and the previous wave has had room to travel
      } else if (sinceLast >= MESH_WAVE_MIN_GAP_MS * 1.6) {
        launch(0.7) // sustained reading, so the film never stalls mid-crawl
      }
      meshPrevShutterRef.current = shNow

      // Retire waves whose every wall has finished fading.
      while (waves.length > 0 && now - waves[0].start > MESH_WAVE_MS * MESH_WAVE_LIFE) {
        waves.shift()
      }
      if (waves.length === 0) return
      const edges = meshEdgesRef.current
      const edgeLen = meshEdgeLenRef.current
      if (!edges || edgeLen <= 0) return

      ctx.save()
      ctx.globalCompositeOperation = "lighter"
      ctx.strokeStyle = baseColor
      ctx.lineWidth = 1
      // TWO PASSES over the walls, for cost rather than looks. A wall that is
      // FULLY drawn needs no dash state, so all completed walls at a given
      // alpha go into ONE batched path; only the handful currently mid-trace
      // pay a setLineDash + individual stroke. Alpha is quantised into buckets
      // so batching is possible at all — the eye cannot resolve the steps at
      // these opacities, and it turns ~1200 state changes per frame into ~12.
      const BUCKETS = 12
      const full: number[][] = []
      for (let b = 0; b < BUCKETS; b++) full.push([])
      const partial: number[] = []

      const arrivalMax = meshArrivalMaxRef.current
      for (let e = 0; e < edges.length; e += 6) {
        const arrival = edges[e + 4]
        // A wall may be lit by MORE THAN ONE wave — a later wave can re-light
        // it while the previous one's trail is still fading. Take the strongest
        // and the most advanced trace, so overlapping waves reinforce instead
        // of the newer one appearing to erase the older.
        const depth = edges[e + 5]
        let bestAlpha = 0
        let bestP = 0
        for (let w = 0; w < waves.length; w++) {
          const front = (now - waves[w].start) / MESH_WAVE_MS
          // An outward wave mirrors the arrival scale, so it reaches the
          // deepest walls first and the boundary last.
          const eff = waves[w].outward ? arrivalMax - arrival : arrival
          const u = front - eff
          if (u < 0) continue // this wave has not reached the wall yet
          // Trace in, hold, then fade — the fade is the TRAIL the user asked
          // for: walls behind the front keep their outline briefly and then
          // dissolve, so each wave leaves a receding wake rather than a
          // permanent lattice.
          let env: number
          if (u < MESH_WAVE_DRAW + MESH_WAVE_HOLD) env = 1
          else {
            env = 1 - (u - MESH_WAVE_DRAW - MESH_WAVE_HOLD) / MESH_WAVE_FADE
            if (env <= 0) continue
          }
          // Soften with depth so the middle never resolves into a crisp shape
          // — the square was legible partly because deep walls arrived at full
          // strength on a clean contour. Combined with the contour noise this
          // makes the centre read as the fading edge of growth rather than as
          // a target the waves converge on.
          const a = env * env * 0.62 * waves[w].strength * k * (1 - MESH_DEPTH_SOFTEN * depth)
          if (a > bestAlpha) bestAlpha = a
          const p = Math.min(1, u / MESH_WAVE_DRAW)
          if (p > bestP) bestP = p
        }
        if (bestAlpha <= 0.015) continue

        if (bestP >= 1) {
          const b = Math.min(
            BUCKETS - 1,
            Math.max(0, Math.round((bestAlpha / 0.62) * (BUCKETS - 1))),
          )
          full[b].push(e)
        } else {
          partial.push(e, bestP, bestAlpha)
        }
      }

      // Completed walls, batched per alpha bucket.
      ctx.setLineDash([])
      for (let b = 0; b < BUCKETS; b++) {
        const list = full[b]
        if (list.length === 0) continue
        ctx.globalAlpha = Math.min(0.62, (b / (BUCKETS - 1)) * 0.62)
        ctx.beginPath()
        for (let j = 0; j < list.length; j++) {
          const e = list[j]
          ctx.moveTo(edges[e], edges[e + 1])
          ctx.lineTo(edges[e + 2], edges[e + 3])
        }
        ctx.stroke()
      }

      // Walls currently drawing themselves. setLineDash with a period of the
      // full wall length plus a matching gap means exactly one dash exists per
      // wall; walking lineDashOffset from len down to 0 extends that dash from
      // one end to the other, so the wall is literally drawn in.
      for (let j = 0; j < partial.length; j += 3) {
        const e = partial[j]
        const p = partial[j + 1]
        ctx.globalAlpha = Math.min(0.62, partial[j + 2])
        ctx.setLineDash([edgeLen, edgeLen])
        ctx.lineDashOffset = edgeLen * (1 - p)
        ctx.beginPath()
        ctx.moveTo(edges[e], edges[e + 1])
        ctx.lineTo(edges[e + 2], edges[e + 3])
        ctx.stroke()
      }
      ctx.setLineDash([])
      ctx.lineDashOffset = 0
      ctx.restore()
    }

    function draw() {
      const now = Date.now()
      const elapsed = now - t0
      // Clamp dt so a backgrounded tab resuming does not fling the ring.
      // Session 247: this clamp MUST stay equal to OrbCanvas's (64 ms) —
      // both engines integrate phase per frame and never re-sync to absolute
      // time, so unequal clamps make the orb drift against this ring on any
      // dropped frame. See the note in OrbCanvas.tsx.
      const dt = Math.min(64, now - (lastFrameRef.current || now))
      lastFrameRef.current = now
      const st = stateRef.current
      const terminal = st === "complete" || st === "error"
      // REQ-8 AC3: during the notice beat the eye shifts violet.
      const noticeNow = now < noticeUntilRef.current
      const color = st === "error" ? ERROR_COLOR : noticeNow ? NOTICE_SOFT_WHITE : colorRef.current

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
      // REQ-8 AC3: during the notice beat the aperture HOLDS open — the eye
      // dilates instead of blinking.
      if (!noticeNow) {
        shutterRef.current = Math.max(0, shutterRef.current - dt / 620)
      }
      phaseRef.current =
        (phaseRef.current +
          (dt / lapMsRef.current) *
            (1 + shutterRef.current * SHUTTER_SPEED_BOOST) *
            (noticeNow ? 2 : 1)) %
        1

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
        // Mesh first, band second: the film is BEHIND the border lattice so the
        // signed-off band keeps its exact visual weight on top of it.
        drawHexMesh(color, k, elapsed, now)
        drawHexScan(color, k, elapsed, now)
        if (terminal) drawSettle(color, k)
        else if (noticeNow) {
          // ESCALATION (user feedback round 12): the comet streams stand
          // down in EVERY state, and the kick-pulse border flash renders as
          // DARKNESS — same grammar, inverted polarity.
          drawBorderFlash("#04060a", k, true)
        } else if (st === "loading" || st === "dispersing") {
          // Traveling motion survives ONLY in the ramp-up states (user
          // feedback round 3): loading/dispersing keep the orbiting head for
          // continuity with the crawl's opening gesture.
          drawStreams(color, k, elapsed, st === "loading" ? 1 : SHELLS.length)
        } else {
          // Crawling: FULL DARK between page landings. Each landing flashes
          // the entire border at once with the comet light — no orbiting.
          drawBorderFlash(color, k)
        }
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

      {/* REQ-8 AC3 (REVISED — user feedback round 1): the escalation "notice"
          ring — one expanding pulse, re-keyed per beat so it restarts. The
          violet tint was rejected at sign-off: the ring now wears a
          black↔white linear gradient. Skipped under reduced motion. */}
      {noticeActive && !prefersReducedMotion && (
        <span
          key={noticeSeq}
          className="absolute left-1/2 rounded-full iris-nav-touch"
          style={{
            top: `calc(50% + ${chromeInset / 2}px)`,
            width: ORB_SIZE * 1.4,
            height: ORB_SIZE * 1.4,
            border: "1px solid rgba(255,255,255,0.55)",
            background:
              "linear-gradient(135deg, rgba(255,255,255,0.22) 0%, rgba(0,0,0,0.45) 60%, transparent 78%)",
          }}
          aria-hidden="true"
        />
      )}

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
