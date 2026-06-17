'use client'

import React, { useEffect, useRef, useCallback, useState } from 'react'

interface PrototypeOrbProps {
  glowColor?: string
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←'

const LABELS = [
  { final: '→ Chat ←', x: 0, y: 68, swirl: '180deg' },
  { final: '↑ Menu', x: 0, y: -68, swirl: '-120deg' },
  { final: '↑↑ Voice', x: -68, y: 30, swirl: '240deg' },
]

export function PrototypeOrb({ glowColor = '#00d4ff' }: PrototypeOrbProps) {
  const xurCanvasRef = useRef<HTMLCanvasElement>(null)
  const rippleCanvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const startTimeRef = useRef<number>(0)
  const ripplesRef = useRef<Array<{ r: number; alpha: number; speed: number; width: number }>>([])
  const [isSpinning, setIsSpinning] = useState(false)
  const [inverted, setInverted] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const [scrambledSet, setScrambledSet] = useState<Set<number>>(new Set())
  const [displayTexts, setDisplayTexts] = useState<string[]>(['', '', ''])
  const scrambleTimersRef = useRef<ReturnType<typeof setInterval>[]>([])
  const switchTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // --- Xur Spiral ---
  useEffect(() => {
    const canvas = xurCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const size = 90
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const PARTICLE_COUNT = 68
    const ROTATION_DURATION = 24000
    const PULSE_DURATION = 4200

    function detailScale(t: number) {
      return 0.52 + 0.48 * (0.5 + 0.5 * Math.sin((t / PULSE_DURATION) * Math.PI * 2))
    }

    function curvePoint(t: number, s: number) {
      return {
        x: 50 + (7.0 * Math.cos(t) - 3.0 * s * Math.cos(9 * t)) * 3.9,
        y: 50 + (7.0 * Math.sin(t) - 3.0 * s * Math.sin(9 * t)) * 3.9,
      }
    }

    if (!startTimeRef.current) startTimeRef.current = Date.now()

    function draw() {
      const elapsed = Date.now() - startTimeRef.current
      ctx.clearRect(0, 0, size, size)
      ctx.fillStyle = glowColor

      const s = detailScale(elapsed)
      const progress = (elapsed % ROTATION_DURATION) / ROTATION_DURATION
      const currentAngle = progress * Math.PI * 2

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const trailOffset = (i / PARTICLE_COUNT) * Math.PI * 2
        const angle = currentAngle - trailOffset
        const pt = curvePoint(angle, s)
        const px = (pt.x / 100) * size
        const py = (pt.y / 100) * size
        const fade = 1 - i / PARTICLE_COUNT
        const particleSize = (1 + fade * 2) * (size / 100)
        ctx.globalAlpha = fade * 0.6
        ctx.beginPath()
        ctx.arc(px, py, particleSize, 0, Math.PI * 2)
        ctx.fill()
      }

      const lead = curvePoint(currentAngle, s)
      ctx.globalAlpha = 1
      ctx.beginPath()
      ctx.arc((lead.x / 100) * size, (lead.y / 100) * size, size / 32, 0, Math.PI * 2)
      ctx.fill()

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [glowColor])

  // --- Scramble Engine ---
  const scramble = useCallback((idx: number, finalText: string) => {
    const len = finalText.length
    let frame = 0
    const totalFrames = 24

    // Clear any existing timer for this index
    if (scrambleTimersRef.current[idx]) {
      clearInterval(scrambleTimersRef.current[idx])
    }

    const timer = setInterval(() => {
      frame++
      let out = ''
      for (let i = 0; i < len; i++) {
        if (frame / totalFrames > i / len) {
          out += finalText[i]
        } else {
          out += CHARS[Math.floor(Math.random() * CHARS.length)]
        }
      }
      setDisplayTexts(prev => {
        const next = [...prev]
        next[idx] = out
        return next
      })
      if (frame >= totalFrames) {
        clearInterval(timer)
        setDisplayTexts(prev => {
          const next = [...prev]
          next[idx] = finalText
          return next
        })
      }
    }, 30)

    scrambleTimersRef.current[idx] = timer
  }, [])

  // Auto-cycle active label
  useEffect(() => {
    switchTimerRef.current = setInterval(() => {
      setActiveIdx(prev => {
        const next = (prev + 1) % 3
        setScrambledSet(s => {
          const ns = new Set(s)
          ns.delete(next) // Allow rescramble
          return ns
        })
        return next
      })
    }, 2800)

    return () => {
      if (switchTimerRef.current) clearInterval(switchTimerRef.current)
    }
  }, [])

  // Trigger scramble when active changes
  useEffect(() => {
    if (!scrambledSet.has(activeIdx)) {
      scramble(activeIdx, LABELS[activeIdx].final)
      setScrambledSet(s => new Set([...s, activeIdx]))
    }
  }, [activeIdx, scrambledSet, scramble])

  // Cleanup scramble timers
  useEffect(() => {
    return () => {
      scrambleTimersRef.current.forEach(t => clearInterval(t))
    }
  }, [])

  // --- Ripple Engine ---
  useEffect(() => {
    const canvas = rippleCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const rSize = 480
    canvas.width = rSize * dpr
    canvas.height = rSize * dpr
    ctx.scale(dpr, dpr)

    function spawnRipple() {
      ripplesRef.current.push({ r: 10, alpha: 0.45, speed: 2.2, width: 1.5 })
      ripplesRef.current.push({ r: 6, alpha: 0.25, speed: 1.4, width: 2.5 })
      ripplesRef.current.push({ r: 2, alpha: 0.6, speed: 3.0, width: 1 })
    }

    // Expose spawn function
    ;(canvas as any).__spawnRipple = spawnRipple

    function drawRipples() {
      ctx.clearRect(0, 0, rSize, rSize)
      const center = { x: rSize / 2, y: rSize / 2 }

      for (let i = ripplesRef.current.length - 1; i >= 0; i--) {
        const rip = ripplesRef.current[i]
        rip.r += rip.speed
        rip.alpha -= 0.0035
        rip.width = Math.max(0.3, rip.width - 0.008)

        if (rip.alpha <= 0) {
          ripplesRef.current.splice(i, 1)
          continue
        }

        ctx.strokeStyle = `rgba(148, 163, 184, ${rip.alpha})`
        ctx.lineWidth = rip.width
        ctx.beginPath()
        ctx.arc(center.x, center.y, rip.r, 0, Math.PI * 2)
        ctx.stroke()
      }
      rafRef.current = requestAnimationFrame(drawRipples)
    }

    rafRef.current = requestAnimationFrame(drawRipples)
    return () => cancelAnimationFrame(rafRef.current)
  }, [])

  const handleClick = useCallback(() => {
    setIsSpinning(true)
    setInverted(true)

    // Spawn ripples
    const canvas = rippleCanvasRef.current
    if (canvas && (canvas as any).__spawnRipple) {
      ;(canvas as any).__spawnRipple()
    }

    setTimeout(() => setInverted(false), 350)
    setTimeout(() => setIsSpinning(false), 2000)
  }, [])

  return (
    <div className="relative" style={{ perspective: '900px', width: '320px', height: '320px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {/* Ripple canvas */}
      <canvas
        ref={rippleCanvasRef}
        className="absolute pointer-events-none"
        style={{ inset: '-80px', zIndex: 0 }}
      />

      {/* Floating wrapper */}
      <div
        className="relative"
        style={{
          animation: 'protoFloat 4s ease-in-out infinite',
        }}
      >
        <div
          className="relative flex items-center justify-center cursor-pointer"
          style={{ width: '180px', height: '180px', transformStyle: 'preserve-3d' }}
          onClick={handleClick}
        >
          {/* Front face */}
          <div
            className="absolute inset-0 rounded-full flex flex-col items-center justify-center"
            style={{ transform: 'translateZ(12px)' }}
          >
            {/* Spiral wrap */}
            <div
              className="relative"
              style={{
                width: '90px',
                height: '90px',
                zIndex: 2,
                transition: 'transform 1.5s cubic-bezier(0.4, 0, 0.2, 1)',
                transform: isSpinning ? 'rotate(360deg) scale(0.85)' : 'rotate(0deg) scale(1)',
              }}
            >
              <canvas
                ref={xurCanvasRef}
                style={{ width: '90px', height: '90px', display: 'block' }}
              />
            </div>

            {/* Orbiting words */}
            <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
              {LABELS.map((label, i) => (
                <div
                  key={i}
                  className="absolute"
                  style={{
                    left: '50%',
                    top: '50%',
                    transition: 'all 1.5s cubic-bezier(0.4, 0, 0.2, 1)',
                    transform: isSpinning
                      ? `translate(-50%, -50%) translate(0, 0) rotate(${label.swirl}) scale(0.3)`
                      : `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)`,
                    opacity: isSpinning ? 0 : 1,
                  }}
                >
                  <span
                    style={{
                      display: 'block',
                      fontSize: '11px',
                      fontWeight: 700,
                      letterSpacing: '0.12em',
                      textTransform: 'uppercase' as const,
                      color: activeIdx === i
                        ? inverted
                          ? '#0f172a'
                          : '#e2e8f0'
                        : '#475569',
                      textShadow: activeIdx === i
                        ? inverted
                          ? 'none'
                          : '0 0 16px rgba(226,232,240,0.35), 0 0 4px rgba(148,163,184,0.5)'
                        : '0 0 6px rgba(148,163,184,0.1)',
                      whiteSpace: 'nowrap',
                      opacity: activeIdx === i ? 1 : 0.4,
                      transition: 'all 0.35s ease',
                      minWidth: '80px',
                      textAlign: 'center',
                      background: inverted && activeIdx === i ? '#e2e8f0' : 'transparent',
                      padding: inverted && activeIdx === i ? '4px 10px' : '0',
                      borderRadius: inverted && activeIdx === i ? '4px' : '0',
                      boxShadow: inverted && activeIdx === i ? '0 0 20px rgba(226,232,240,0.4)' : 'none',
                      fontFamily: "'Courier New', Courier, monospace",
                    }}
                  >
                    {displayTexts[i] || ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Float keyframes */}
      <style>{`
        @keyframes protoFloat {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-8px); }
        }
      `}</style>
    </div>
  )
}
