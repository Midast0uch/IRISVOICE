'use client'

import React, { useEffect, useRef, useCallback, useState } from 'react'

interface PrototypeOrbDepthAlphaProps {
  glowColor?: string
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←'

const LABELS = [
  { final: '→ Chat ←', x: 0, y: 68, swirl: '180deg' },
  { final: '↑ Menu', x: 0, y: -68, swirl: '-120deg' },
  { final: '↑↑ Voice', x: -68, y: 30, swirl: '240deg' },
]

const SIZE = 90
const PARTICLE_COUNT = 220
const ROTATION_DURATION = 24000
const PULSE_DURATION = 4200

/**
 * Option A — Density + depth-aware alpha + Spiral-out text animation
 *
 * On click: particles bloom outward, rotation accelerates briefly, AND
 * each orbiting label spirals off-screen with its own rotation arc.
 * This is the A-flavour text disappearance — choose to keep it, or pick
 * another variant's text animation for the final design.
 */
export function PrototypeOrbDepthAlpha({ glowColor = '#00d4ff' }: PrototypeOrbDepthAlphaProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const startTimeRef = useRef<number>(0)
  const pulseRef = useRef<number>(0)
  const [activeIdx, setActiveIdx] = useState(0)
  const [scrambledSet, setScrambledSet] = useState<Set<number>>(new Set())
  const [displayTexts, setDisplayTexts] = useState<string[]>(['', '', ''])
  const [isAnimatingText, setIsAnimatingText] = useState(false)
  const scrambleTimersRef = useRef<ReturnType<typeof setInterval>[]>([])
  const switchTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = SIZE * dpr
    canvas.height = SIZE * dpr
    ctx.scale(dpr, dpr)

    if (!startTimeRef.current) startTimeRef.current = Date.now()

    function detailScale(t: number) {
      return 0.52 + 0.48 * (0.5 + 0.5 * Math.sin((t / PULSE_DURATION) * Math.PI * 2))
    }

    function curvePoint(t: number, s: number) {
      return {
        x: 50 + (7.0 * Math.cos(t) - 3.0 * s * Math.cos(9 * t)) * 3.9,
        y: 50 + (7.0 * Math.sin(t) - 3.0 * s * Math.sin(9 * t)) * 3.9,
      }
    }

    function draw() {
      const elapsed = Date.now() - (startTimeRef.current ?? Date.now())
      ctx.clearRect(0, 0, SIZE, SIZE)
      ctx.globalCompositeOperation = 'lighter'
      ctx.fillStyle = glowColor

      const s = detailScale(elapsed)
      const pulse = pulseRef.current
      const speedBoost = 1 + pulse * 1.6
      const progress = ((elapsed * speedBoost) % ROTATION_DURATION) / ROTATION_DURATION
      const currentAngle = progress * Math.PI * 2
      const bloom = 1 + pulse * 0.35

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const trailOffset = (i / PARTICLE_COUNT) * Math.PI * 2
        const angle = currentAngle - trailOffset
        const pt = curvePoint(angle, s)
        let px = ((pt.x - 50) / 50) * (SIZE / 2) * bloom + SIZE / 2
        let py = ((pt.y - 50) / 50) * (SIZE / 2) * bloom + SIZE / 2

        const fade = 1 - i / PARTICLE_COUNT
        const depthWave = 0.5 + 0.5 * Math.sin(angle * 0.3 + elapsed * 0.00025)
        const depthFactor = 0.25 + 0.75 * depthWave

        const particleSize = (0.6 + fade * 1.8) * (SIZE / 100) * (0.5 + depthFactor * 0.8)
        ctx.globalAlpha = fade * 0.55 * depthFactor
        ctx.beginPath()
        ctx.arc(px, py, particleSize, 0, Math.PI * 2)
        ctx.fill()
      }

      const lead = curvePoint(currentAngle, s)
      const lx = ((lead.x - 50) / 50) * (SIZE / 2) * bloom + SIZE / 2
      const ly = ((lead.y - 50) / 50) * (SIZE / 2) * bloom + SIZE / 2
      ctx.globalAlpha = 1
      ctx.beginPath()
      ctx.arc(lx, ly, SIZE / 32, 0, Math.PI * 2)
      ctx.fill()

      if (pulseRef.current > 0) {
        pulseRef.current = Math.max(0, pulseRef.current - 0.015)
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [glowColor])

  const scramble = useCallback((idx: number, finalText: string) => {
    const len = finalText.length
    let frame = 0
    const totalFrames = 24
    if (scrambleTimersRef.current[idx]) clearInterval(scrambleTimersRef.current[idx])
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

  useEffect(() => {
    switchTimerRef.current = setInterval(() => {
      setActiveIdx(prev => {
        const next = (prev + 1) % 3
        setScrambledSet(s => {
          const ns = new Set(s)
          ns.delete(next)
          return ns
        })
        return next
      })
    }, 2800)
    return () => {
      if (switchTimerRef.current) clearInterval(switchTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (!scrambledSet.has(activeIdx)) {
      scramble(activeIdx, LABELS[activeIdx].final)
      setScrambledSet(s => new Set([...s, activeIdx]))
    }
  }, [activeIdx, scrambledSet, scramble])

  useEffect(() => {
    return () => {
      scrambleTimersRef.current.forEach(t => clearInterval(t))
    }
  }, [])

  const handleTextAnimEnd = useCallback(() => {
    setTimeout(() => setIsAnimatingText(false), 700)
  }, [])

  const handleClick = useCallback(() => {
    pulseRef.current = 1
    setIsAnimatingText(true)
  }, [])

  return (
    <div
      className="relative flex items-center justify-center cursor-pointer"
      style={{ perspective: '900px', width: '180px', height: '180px', transformStyle: 'preserve-3d' }}
      onClick={handleClick}
    >
      <div
        className="absolute inset-0 rounded-full flex flex-col items-center justify-center"
        style={{ transform: 'translateZ(12px)' }}
      >
        <div
          className="relative"
          style={{
            width: `${SIZE}px`,
            height: `${SIZE}px`,
            zIndex: 2,
            animation: 'protoFloat 4s ease-in-out infinite',
          }}
        >
          <canvas
            ref={canvasRef}
            style={{ width: `${SIZE}px`, height: `${SIZE}px`, display: 'block' }}
          />
        </div>
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
          {LABELS.map((label, i) => (
            <div
              key={i}
              className="absolute"
              style={{
                left: '50%',
                top: '50%',
                transform: `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)`,
              }}
            >
              <span
                className={isAnimatingText ? 'text-anim-A-spiral' : ''}
                onAnimationEnd={isAnimatingText ? handleTextAnimEnd : undefined}
                style={{
                  display: 'block',
                  fontSize: '11px',
                  fontWeight: 700,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase' as const,
                  color: activeIdx === i ? '#e2e8f0' : '#475569',
                  textShadow: activeIdx === i
                    ? '0 0 16px rgba(226,232,240,0.35), 0 0 4px rgba(148,163,184,0.5)'
                    : '0 0 6px rgba(148,163,184,0.1)',
                  whiteSpace: 'nowrap',
                  opacity: activeIdx === i ? 1 : 0.4,
                  fontFamily: "'Courier New', Courier, monospace",
                  // CSS variables for the text animation: each label flies
                  // outward to 2× its current offset
                  ['--fly-x' as any]: `${label.x * 2}px`,
                  ['--fly-y' as any]: `${label.y * 2}px`,
                } as React.CSSProperties}
              >
                {displayTexts[i] || ''}
              </span>
            </div>
          ))}
        </div>
      </div>
      <style>{`
        @keyframes protoFloat {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-6px); }
        }
        /* A: spiral outward — rotate 540° while flying outward 2× its offset */
        @keyframes textAnimASpiral {
          0% { transform: translate(0, 0) rotate(0deg) scale(1); opacity: 1; }
          100% { transform: translate(var(--fly-x), var(--fly-y)) rotate(540deg) scale(0); opacity: 0; }
        }
        .text-anim-A-spiral {
          animation: textAnimASpiral 1s cubic-bezier(0.4, 0, 0.7, 1) forwards;
        }
      `}</style>
    </div>
  )
}
