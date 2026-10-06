'use client'

import { useEffect, useRef } from 'react'
import { makePaletteSampler, type Palette } from '@/lib/brandPalette'

interface XurProps {
  size?: number
  color?: string
  speed?: number
  /**
   * Optional brand palette [head, body, tail]. When given, particle i takes a
   * colour interpolated head -> body -> tail along the trail and `color` is
   * ignored. Without it the trail is drawn in one `color`, as before.
   */
  palette?: Palette
}

export function Xur({ size = 32, color = 'currentColor', speed = 1, palette }: XurProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const startRef = useRef<number>(0)
  // A stable key so a new array with the same colours does not restart the loop.
  const paletteKey = palette ? palette.join('|') : ''

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const PARTICLE_COUNT = 68
    const ROTATION_DURATION = 30000 / speed
    const PULSE_DURATION = 4200 / speed
    // Per-particle colours (head = index 0). Null keeps the single-colour path.
    const pal = paletteKey ? (paletteKey.split('|') as unknown as Palette) : null
    const sample = pal ? makePaletteSampler(pal) : null
    const colors = sample
      ? Array.from({ length: PARTICLE_COUNT }, (_, i) => sample(i / PARTICLE_COUNT))
      : null

    function detailScale(t: number): number {
      return 0.52 + 0.48 * (0.5 + 0.5 * Math.sin((t / PULSE_DURATION) * Math.PI * 2))
    }

    function curvePoint(t: number, s: number) {
      const x = 50 + (7.0 * Math.cos(t) - 3.0 * s * Math.cos(9 * t)) * 3.9
      const y = 50 + (7.0 * Math.sin(t) - 3.0 * s * Math.sin(9 * t)) * 3.9
      return { x, y }
    }

    function animate(timestamp: number) {
      if (!startRef.current) startRef.current = timestamp
      const elapsed = timestamp - startRef.current

      ctx.clearRect(0, 0, size, size)
      if (!colors) {
        ctx.strokeStyle = color
        ctx.fillStyle = color
      }

      const s = detailScale(elapsed)
      const progress = (elapsed % ROTATION_DURATION) / ROTATION_DURATION
      const currentAngle = progress * Math.PI * 2

      // Draw trailing particles
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const trailOffset = (i / PARTICLE_COUNT) * Math.PI * 2
        const angle = currentAngle - trailOffset
        const pt = curvePoint(angle, s)
        const px = (pt.x / 100) * size
        const py = (pt.y / 100) * size

        const fade = 1 - i / PARTICLE_COUNT
        const particleSize = (1 + fade * 2) * (size / 100)

        if (colors) ctx.fillStyle = colors[i]
        ctx.globalAlpha = fade * 0.6
        ctx.beginPath()
        ctx.arc(px, py, particleSize, 0, Math.PI * 2)
        ctx.fill()
      }

      // Draw leading dot (brightest)
      const lead = curvePoint(currentAngle, s)
      ctx.globalAlpha = 1
      if (colors) ctx.fillStyle = colors[0]
      ctx.beginPath()
      ctx.arc((lead.x / 100) * size, (lead.y / 100) * size, size / 32, 0, Math.PI * 2)
      ctx.fill()

      ctx.globalAlpha = 1
      // Session 312 (UX lock, settled cards): speed <= 0 renders ONE static
      // frame and never schedules another — the marker stops moving when the
      // card's activity is done. Callers passing a positive speed are
      // unchanged.
      if (speed > 0) {
        rafRef.current = requestAnimationFrame(animate)
      }
    }

    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [size, color, speed, paletteKey])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size, display: 'block' }}
      aria-label="Loading"
    />
  )
}
