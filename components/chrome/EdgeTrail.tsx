'use client'

import { useRef } from 'react'
import { makePaletteSampler, type Palette } from '@/lib/brandPalette'
import { useCanvasLoop } from './useCanvasLoop'

export interface EdgeTrailProps {
  /** Brand hues [head, body, tail]; the dots slide along them. */
  palette: Palette
}

// Concept iris-strands.html `drawDashEdge`.
const X0 = 10
const STEP = 6

const hash = (i: number) => {
  const x = Math.sin(i * 127.1) * 43758.5453
  return x - Math.floor(x)
}

/**
 * A faint particle trail along the inner left edge of the dashboard wing: the
 * Xur's trail, in the brand hues. Fills its positioned parent, ignores the
 * pointer. Under prefers-reduced-motion it draws one still frame.
 */
export function EdgeTrail({ palette }: EdgeTrailProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sample = makePaletteSampler(palette)

  useCanvasLoop(canvasRef, (c, w, h, now, still) => {
    const t = still ? 0 : now
    const fl = (t * 0.015) % STEP
    for (let y = fl; y < h; y += STEP) {
      const r = hash(Math.round(y - fl) * 3.1)
      const fadeIn = y < 60 ? y / 60 : 1
      // f runs 1 (head) -> 0 (tail) in the concept; the sampler takes 0 = head.
      const f = 0.5 + 0.5 * Math.sin(y / 200 - t / 5000)
      c.fillStyle = sample(1 - f, (0.14 + r * 0.3) * fadeIn)
      c.beginPath()
      c.arc(X0 + Math.sin(y / 45 + t / 2000) * 2 + (r - 0.5) * 2, y, 0.5 + r * 1.1, 0, Math.PI * 2)
      c.fill()
    }
  }, palette.join('|'))

  return (
    <canvas
      ref={canvasRef}
      data-testid="edge-trail"
      aria-hidden="true"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', display: 'block' }}
    />
  )
}

export default EdgeTrail
