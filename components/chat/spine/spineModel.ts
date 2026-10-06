/**
 * The living spine — pure model (no DOM, no canvas).
 *
 * Look and behaviour: docs/design/chatview-2026-10-06/iris-strands.html
 * (`xAt`, `drawSpine`, `measure`, `showChips`). Everything the spine decides
 * that can be decided without a canvas lives here so it can be tested:
 *
 *   - brand: one hue -> three neighbouring hues (the Xur is never one flat colour)
 *   - detour: where the spine bends into a personal task card's step line
 *   - target: where the agent Xur rides (running rows, else the streaming reply)
 *   - knots: ONLY where something entered from outside the strand
 *   - chips: which turns are in view; the drag-to-scrub scroll position
 *
 * Knot data contract (documented in docs/architecture/CHAT_VIEW.md section 9):
 * an entry in the timeline carries `data-knot="<kind>"`, kind = "ref" (pulled in
 * from another strand / card / artifact), "author" (another author: a person or
 * another agent) or "helper" (a helper strand reporting back). Landmarks are
 * never knots.
 */

export const SPINE_X0 = 14

// ── brand: one hue -> three neighbour hues ────────────────────────────────────
export interface Brand {
  h: number
  /** hue offset of the second colour */
  d2: number
  /** hue offset of the third colour */
  d3: number
}

/** Aether defaults of the concept (BrandColorContext shimmer primary/secondary/accent). */
export const DEFAULT_BRAND: Brand = { h: 190, d2: 25, d3: -40 }

function rgbToHue(r: number, g: number, b: number): number | null {
  const R = r / 255
  const G = g / 255
  const B = b / 255
  const max = Math.max(R, G, B)
  const min = Math.min(R, G, B)
  const d = max - min
  if (d === 0) return null // grey: no hue
  let h: number
  if (max === R) h = ((G - B) / d) % 6
  else if (max === G) h = (B - R) / d + 2
  else h = (R - G) / d + 4
  return Math.round(((h * 60) % 360 + 360) % 360)
}

/** Hue (0-359) of a CSS colour: #rgb, #rrggbb, rgb()/rgba(), hsl()/hsla(). null when not readable. */
export function parseHue(color: string | undefined | null): number | null {
  if (!color) return null
  const c = color.trim().toLowerCase()
  let m = c.match(/^#([0-9a-f]{3}|[0-9a-f]{6})(?:[0-9a-f]{2})?$/)
  if (m) {
    let hex = m[1]
    if (hex.length === 3) hex = hex.split("").map((x) => x + x).join("")
    const n = parseInt(hex, 16)
    return rgbToHue((n >> 16) & 255, (n >> 8) & 255, n & 255)
  }
  m = c.match(/^hsla?\(\s*(-?[\d.]+)/)
  if (m) return ((Math.round(parseFloat(m[1])) % 360) + 360) % 360
  m = c.match(/^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/)
  if (m) return rgbToHue(+m[1], +m[2], +m[3])
  return null
}

export function brandFrom(glowColor: string | undefined | null): Brand {
  const h = parseHue(glowColor)
  return h === null ? DEFAULT_BRAND : { ...DEFAULT_BRAND, h }
}

export function hsla(h: number, s: number, l: number, a = 1): string {
  return `hsla(${((Math.round(h) % 360) + 360) % 360},${s}%,${l}%,${a})`
}

/** The trail colour at position f (1 = head, 0 = tail): moves through the three hues. */
export function trailColor(b: Brand, f: number, a: number): string {
  const h = f > 0.5 ? b.h + (1 - f) * 2 * b.d2 : b.h + b.d2 + (0.5 - f) * 2 * (b.d3 - b.d2)
  return hsla(h, 95, 56 + f * 16, a)
}

/** The three brand colours (concept --b1 / --b2 / --b3). */
export function brandColors(b: Brand): [string, string, string] {
  return [hsla(b.h, 100, 64), hsla(b.h + b.d2, 92, 68), hsla(b.h + b.d3, 85, 60)]
}

/** One point of the Xur curve (components/Xur.tsx), unscaled. */
export function xurPoint(a: number, s: number): [number, number] {
  return [7 * Math.cos(a) - 3 * s * Math.cos(9 * a), 7 * Math.sin(a) - 3 * s * Math.sin(9 * a)]
}

/** Deterministic 0..1 noise per particle index. */
export function hash01(i: number): number {
  const x = Math.sin(i * 127.1) * 43758.5453
  return x - Math.floor(x)
}

// ── the detour into a personal task card ──────────────────────────────────────
/** A card's step line, in canvas x and scroll-content y. */
export interface Detour {
  x: number
  y0: number
  y1: number
}

/** Fade length (px) of the bend in and out. */
export const DETOUR_EASE = 46

export function smoothstep(a: number, b: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/** 0 = on the spine, 1 = fully on the card's step line. */
export function detourWeight(d: Detour, y: number): number {
  return Math.min(smoothstep(d.y0 - DETOUR_EASE, d.y0, y), 1 - smoothstep(d.y1, d.y1 + DETOUR_EASE, y))
}

/** The detour that pulls hardest at y (cards do not overlap in y, so it is the one the spine is in). */
export function dominantDetour(detours: Detour[], y: number): { d: Detour | null; k: number } {
  let best: Detour | null = null
  let bk = 0
  for (const d of detours) {
    const k = detourWeight(d, y)
    if (k > bk) {
      bk = k
      best = d
    }
  }
  return { d: best, k: bk }
}

/** x of the spine at content-y: SPINE_X0, bent toward the card's step line inside a card. */
export function xAt(y: number, detours: Detour[], x0 = SPINE_X0): number {
  const { d, k } = dominantDetour(detours, y)
  return d ? x0 + (d.x - x0) * k : x0
}

/** Wobble scale: 1 on the spine, 0 inside a card (the step line is straight). */
export function wobbleAt(y: number, detours: Detour[], x0 = SPINE_X0): number {
  return 1 - Math.min(1, Math.abs(xAt(y, detours, x0) - x0) / 20)
}

// ── where the agent Xur rides ─────────────────────────────────────────────────
/** Mean of the running rows; else the streaming reply; else nowhere. */
export function pickTarget(runYs: number[], replyY: number | null): number | null {
  if (runYs.length) return runYs.reduce((a, b) => a + b, 0) / runYs.length
  return replyY
}

// ── knots: only where something entered from outside this strand ──────────────
export type KnotKind = "ref" | "author" | "helper"

export function normKnotKind(s: string | undefined | null): KnotKind {
  return s === "author" || s === "helper" ? s : "ref"
}

export function knotColor(b: Brand, kind: KnotKind): string {
  const [c1, c2, c3] = brandColors(b)
  return kind === "ref" ? c2 : kind === "author" ? c3 : c1
}

/** The part of a turn record the knot rules read (lib/turns/turnStore.ts TurnRecord). */
export interface KnotTurnInput {
  id: string
  clientRef?: string
  author: string
  refs: string[]
}

export interface KnotTurn {
  /** Candidate element ids (msg-<id>), first one that is in the DOM wins: the user's prompt, else the turn. */
  ids: string[]
  kind: KnotKind
}

/** Authors that are this strand's own voices: a knot is never drawn for them. */
const OWN_AUTHORS = new Set(["", "user", "iris", "@iris"])

/**
 * A turn becomes a knot ONLY when something from outside came in:
 * non-empty refs (another strand's turn, a task card, an artifact), or an author that is not
 * this strand's own. A plain turn, a landmark, a finished tool: no knot.
 */
export function turnKnots(turns: KnotTurnInput[]): KnotTurn[] {
  const out: KnotTurn[] = []
  for (const t of turns) {
    const foreign = !OWN_AUTHORS.has((t.author || "").toLowerCase())
    const kind: KnotKind | null = foreign ? "author" : t.refs && t.refs.length > 0 ? "ref" : null
    if (!kind) continue
    out.push({ ids: t.clientRef ? [t.clientRef, t.id] : [t.id], kind })
  }
  return out
}

// ── chips ─────────────────────────────────────────────────────────────────────
export interface SpineChip {
  messageId: string
  label: string
  /** scroll-content y of the turn; undefined when its element is not rendered */
  y?: number
  /** set when a knot sits on this turn (shown as "from outside") */
  knot?: KnotKind
}

/** Which chips are in the visible part of the scroll area (the list highlights them). */
export function chipsInView(chips: { y?: number }[], top: number, height: number): boolean[] {
  return chips.map((c) => c.y !== undefined && c.y >= top && c.y <= top + height)
}

/** Drag on the gutter: fraction (0..1) of the gutter height -> scrollTop. */
export function scrubTop(fraction: number, scrollHeight: number, clientHeight: number): number {
  const f = Math.max(0, Math.min(1, fraction))
  return f * Math.max(0, scrollHeight - clientHeight)
}
