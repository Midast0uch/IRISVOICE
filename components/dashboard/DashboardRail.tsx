"use client"

import React, { useEffect, useRef } from "react"
import { useCanvasLoop } from "@/components/chrome/useCanvasLoop"
import { hash01, xurPoint } from "@/components/chat/spine/spineModel"
import { makePaletteSampler, type Palette } from "@/lib/brandPalette"

export type RailView = "settings" | "surfaces"

export interface RailPlace {
  id: string
  label: string
  /** Small amber text at the right edge (a count of changes, "live"). */
  badge?: string | number
  title?: string
}

export interface DashboardRailProps {
  view: RailView
  onView: (v: RailView) => void
  /** The places of the current view, top to bottom. */
  places: RailPlace[]
  /** The place on screen; null when it is not one of `places`. */
  current: string | null
  onPlace: (id: string) => void
  /** Orbs only (the Xur button folds the rail). */
  folded: boolean
  /** The brand hues, second hue first: the Xur rides in these. */
  palette: Palette
  /** The user / model block at the foot. */
  footer?: React.ReactNode
}

// Concept iris-dashboard.html `drawRail`.
const SPINE_X = 15
const DOT_STEP = 7
const XUR_R = 10
const XUR_TURNS_PER_30S = 12
const EASE = 0.12 // how far the Xur travels toward its place per frame

const VIEWS: { id: RailView; label: string; glyph: string }[] = [
  { id: "settings", label: "Settings", glyph: "⚙" },
  { id: "surfaces", label: "Surfaces", glyph: "▦" },
]

/**
 * The dashboard's rail: a spine with two views (Settings / Surfaces). One canvas
 * draws the particle line, an orb at each place and the Xur riding to the current
 * place. Under prefers-reduced-motion it draws one still frame; the loop pauses
 * while the document is hidden (both from useCanvasLoop).
 */
export function DashboardRail({ view, onView, places, current, onPlace, folded, palette, footer }: DashboardRailProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const riderY = useRef<number | null>(null)
  const sample = makePaletteSampler(palette)

  // The Xur starts at its place when the view changes, it does not ride across lists.
  useEffect(() => { riderY.current = null }, [view])

  const key = `${view}|${current}|${folded}|${places.map((p) => p.id).join(",")}|${palette.join(",")}`

  useCanvasLoop(canvasRef, (c, w, h, now, still) => {
    const scroll = scrollRef.current
    const top = 8, bottom = h - 8
    const fl = still ? 0 : (now * 0.012) % DOT_STEP

    // The particle line.
    for (let y = top + fl; y < bottom; y += DOT_STEP) {
      const r = hash01(Math.round(y - fl))
      c.fillStyle = sample(1 - (0.35 + 0.3 * r), 0.1 + r * 0.18)
      c.beginPath(); c.arc(SPINE_X + (r - 0.5) * 1.6, y, 0.45 + r * 0.8, 0, Math.PI * 2); c.fill()
    }

    // An orb at each place (hollow when it is not the current one).
    const at: { y: number | null } = { y: null }
    scroll?.querySelectorAll<HTMLElement>("[data-place]").forEach((b) => {
      const y = b.offsetTop + b.offsetHeight / 2
      const cur = b.getAttribute("aria-current") === "true"
      if (cur) at.y = y
      c.fillStyle = cur ? sample(0) : "rgba(138,146,168,.55)"
      c.beginPath(); c.arc(SPINE_X, y, cur ? 3 : 2.2, 0, Math.PI * 2); c.fill()
      if (!cur) { c.fillStyle = "#04050c"; c.beginPath(); c.arc(SPINE_X, y, 1.1, 0, Math.PI * 2); c.fill() }
    })

    // The Xur, riding to the current place.
    if (at.y !== null) {
      const ty = at.y
      riderY.current = riderY.current == null || still ? ty : riderY.current + (ty - riderY.current) * EASE
      drawXur(c, SPINE_X, riderY.current, XUR_R, now, still, sample)
    }
  }, key)

  return (
    <nav className="iris-rail" aria-label="Dashboard places" data-folded={folded ? "true" : "false"} data-testid="dash-rail">
      <div className="iris-rail-scroll" ref={scrollRef}>
        <canvas ref={canvasRef} className="iris-rail-cv" data-testid="rail-spine" aria-hidden="true" />
        <div className="iris-rsw" role="group" aria-label="Rail view">
          {VIEWS.map((v) => (
            <button key={v.id} type="button" aria-pressed={view === v.id} title={v.label} onClick={() => onView(v.id)}>
              <span>{v.label}</span>
              <b className="gl" aria-hidden="true">{v.glyph}</b>
            </button>
          ))}
        </div>
        {places.map((p) => (
          <button
            key={p.id}
            type="button"
            className="iris-place"
            data-place={p.id}
            aria-current={current === p.id ? "true" : undefined}
            title={p.title ?? p.label}
            onClick={() => onPlace(p.id)}
          >
            <span>{p.label}</span>
            {p.badge !== undefined && p.badge !== "" && <em className="n">{p.badge}</em>}
          </button>
        ))}
      </div>
      {footer}
    </nav>
  )
}

/** The Xur on the spine (concept `drawXur`, with the rail's settings). */
function drawXur(
  c: CanvasRenderingContext2D, cx: number, cy: number, R: number, now: number, still: boolean,
  sample: (t: number, a?: number) => string,
) {
  const sc = R / 10, n = 44
  const rot = still ? 0.6 : (now * 1.2) / 30000 * Math.PI * XUR_TURNS_PER_30S
  for (let i = 0; i < n; i++) {
    const a = rot - (i / n) * Math.PI * 2
    const [x, y] = xurPoint(a, 0.55)
    const f = 1 - i / n
    c.fillStyle = sample(1 - f, 0.15 + f * 0.75)
    c.beginPath(); c.arc(cx + x * sc, cy + y * sc, Math.max(0.5, (0.35 + f * 1.4) * 0.9), 0, Math.PI * 2); c.fill()
  }
}
