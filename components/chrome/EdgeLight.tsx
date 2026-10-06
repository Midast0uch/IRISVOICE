'use client'

import { useRef } from 'react'
import { IrisApertureIcon } from '@/components/ui/IrisApertureIcon'
import { makePaletteSampler, withAlpha, type Palette } from '@/lib/brandPalette'
import { useCanvasLoop } from './useCanvasLoop'

export interface EdgeLightProps {
  /** Brand glow colour: the line when no palette is given, and the aperture fill when active. */
  glowColor: string
  /** Brand hues; the line and the travelling light use the head colour. */
  palette?: Palette
  /** This wing is spotlit: the line stays lit near the aperture. */
  spotlit: boolean
  /** A strand is working: the light leaves every ~2.6 s, in `workingColor`. */
  working?: boolean
  workingColor?: string
  onAperture: () => void
  /** Title and aria-label of the aperture button. */
  apertureTitle: string
  /** Aperture morph state (see IrisApertureIcon). */
  isActive: boolean
}

// Concept iris-strands.html `drawEdge`.
const GAP_R = 11          // gap in the line around the aperture
const CORNER_R = 14       // line stops short of the wing corners
const IDLE_MS = 7000
const WORKING_MS = 2600
const JITTER_MS = 900
const PULSE_LIFE_MS = 9000
const PULSE_SPEED = 0.045 // px per ms
const MAX_PULSES = 8      // bounded: a long pause cannot pile up pulses

interface Pulse { t0: number; col: string }

/**
 * The wing's top edge: one hairline with the spotlight aperture set into it at
 * the top middle. Place it in a positioned parent whose top edge is the wing's
 * top border; it is 24 px tall and centred on that edge. No box around the
 * aperture. Under prefers-reduced-motion it draws one still frame.
 */
export function EdgeLight({
  glowColor, palette, spotlit, working = false, workingColor, onAperture, apertureTitle, isActive,
}: EdgeLightProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pulses = useRef<Pulse[]>([])
  const nextAt = useRef(0)

  const base = palette?.[0] ?? glowColor
  const pulseCol = working && workingColor ? workingColor : base
  const sampler = palette ? makePaletteSampler(palette) : null
  // The deps of the loop: a change repaints the still frame; the animated loop reads the latest draw anyway.
  const key = `${base}|${spotlit}|${palette ? palette.join(',') : ''}`

  useCanvasLoop(canvasRef, (c, w, h, now, still) => {
    const y = h / 2, cx = w / 2
    const half = Math.max(1, w / 2 - CORNER_R)

    if (!still) {
      if (now > nextAt.current) {
        if (pulses.current.length < MAX_PULSES) pulses.current.push({ t0: now, col: pulseCol })
        nextAt.current = now + (working ? WORKING_MS : IDLE_MS) + Math.random() * JITTER_MS
      }
      pulses.current = pulses.current.filter((p) => now - p.t0 < PULSE_LIFE_MS)
    }

    // The hairline, brighter toward the aperture, with a gap where it sits.
    for (const dir of [-1, 1]) {
      const x0 = cx + dir * GAP_R, x1 = cx + dir * half
      const g = c.createLinearGradient(x0, 0, x1, 0)
      g.addColorStop(0, withAlpha(base, 0.22))
      g.addColorStop(1, withAlpha(sampler ? sampler(1) : base, 0.05))
      c.strokeStyle = g
      c.lineWidth = 1
      c.beginPath(); c.moveTo(x0, y + 0.5); c.lineTo(x1, y + 0.5); c.stroke()
    }

    // Spotlight: a steady glow near the aperture.
    if (spotlit) {
      for (const dir of [-1, 1]) {
        const x0 = cx + dir * GAP_R, x1 = cx + dir * 90
        const g = c.createLinearGradient(x0, 0, x1, 0)
        g.addColorStop(0, withAlpha(base, 0.7))
        g.addColorStop(1, withAlpha(base, 0))
        c.strokeStyle = g
        c.lineWidth = 1.2
        c.beginPath(); c.moveTo(x0, y + 0.5); c.lineTo(x1, y + 0.5); c.stroke()
      }
    }

    // Lights travel outward both ways, slowly, and fade before the corners.
    for (const p of pulses.current) {
      const d = GAP_R + (now - p.t0) * PULSE_SPEED
      const fade = Math.max(0, 1 - d / half)
      if (fade <= 0) continue
      for (const dir of [-1, 1]) {
        const x = cx + dir * d
        const g = c.createLinearGradient(x - 26, 0, x + 26, 0)
        g.addColorStop(0, withAlpha(p.col, 0))
        g.addColorStop(0.5, withAlpha(p.col, 0.55 * fade))
        g.addColorStop(1, withAlpha(p.col, 0))
        c.strokeStyle = g
        c.lineWidth = 1.3
        c.beginPath(); c.moveTo(x - 26, y + 0.5); c.lineTo(x + 26, y + 0.5); c.stroke()
      }
    }
  }, key)

  return (
    <div
      data-testid="edge-light"
      data-spotlit={spotlit ? 'true' : 'false'}
      data-working={working ? 'true' : 'false'}
      style={{ position: 'absolute', left: 0, right: 0, top: -12, height: 24, pointerEvents: 'none', zIndex: 50 }}
    >
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }}
      />
      <button
        type="button"
        className="iris-edge-ap"
        onClick={onAperture}
        title={apertureTitle}
        aria-label={apertureTitle}
        aria-pressed={isActive}
        style={{ color: base }}
      >
        <IrisApertureIcon isActive={isActive} glowColor={glowColor} fontColor={base} size={14} />
      </button>
    </div>
  )
}

export default EdgeLight
