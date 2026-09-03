'use client'

import React, { useEffect, useRef, useCallback, useState } from 'react'

interface PrototypeOrbShellsDepthProps {
  glowColor?: string
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←'

const LABELS = [
  { final: '→ Chat ←', x: 0, y: 68, swirl: '180deg' },
  { final: '↑ Menu', x: 0, y: -68, swirl: '-120deg' },
  { final: '↑↑ Voice', x: -68, y: 30, swirl: '240deg' },
]

const SIZE = 90

// D keeps its denser shells (180/130/80) — now with the continuous burst
// feedback that used to live in C.
const SHELLS = [
  { scale: 1.05, speed: 1.0, count: 180, alpha: 0.55, size: 1.0 },
  { scale: 0.70, speed: 1.45, count: 130, alpha: 0.45, size: 0.8 },
  { scale: 0.42, speed: 0.62, count: 80, alpha: 0.85, size: 0.7 },
]

const PULSE_DURATION = 4200

/**
 * Variant D (swapped) — Layered shells + depth awareness + softer burst
 * feedback + magnetic-pull text disappearance.
 *
 *   Continuous idle → click → burst: gentle speedup (0.9× amplitude),
 *                       small bloom (0.25), short decay (~0.75s)
 *   Text labels magnetically pull toward the orb center while spiraling
 *   inward and shrinking — the labels are "consumed" by the orb.
 */
export function PrototypeOrbShellsDepth({ glowColor = '#00d4ff' }: PrototypeOrbShellsDepthProps) {
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

    function drawShell(
      shell: typeof SHELLS[number],
      progress: number,
      s: number,
      bloom: number,
      elapsed: number,
    ) {
      const currentAngle = progress * Math.PI * 2
      ctx.fillStyle = glowColor

      for (let i = 0; i < shell.count; i++) {
        const trailOffset = (i / shell.count) * Math.PI * 2
        const angle = currentAngle - trailOffset
        const pt = curvePoint(angle, s)
        const effectiveScale = shell.scale * bloom
        let px = ((pt.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
        let py = ((pt.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2

        const fade = 1 - i / shell.count
        // Depth awareness — wider than C (0.75–1.0) so D feels more volumetric.
        const depthWave = 0.5 + 0.5 * Math.sin(angle * 0.5 + elapsed * 0.0003)
        const depthFactor = 0.75 + 0.25 * depthWave

        const particleSize = (0.5 + fade * 1.6) * (SIZE / 100) * shell.size
        ctx.globalAlpha = fade * 0.6 * shell.alpha * depthFactor
        ctx.beginPath()
        ctx.arc(px, py, particleSize, 0, Math.PI * 2)
        ctx.fill()
      }

      const lead = curvePoint(currentAngle, s)
      const effectiveScale = shell.scale * bloom
      const lx = ((lead.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
      const ly = ((lead.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
      ctx.globalAlpha = shell.alpha
      ctx.beginPath()
      ctx.arc(lx, ly, (SIZE / 36) * shell.size, 0, Math.PI * 2)
      ctx.fill()
    }

    function draw() {
      const elapsed = Date.now() - (startTimeRef.current ?? Date.now())
      const pulse = pulseRef.current
      ctx.clearRect(0, 0, SIZE, SIZE)
      ctx.globalCompositeOperation = 'lighter'
      const s = detailScale(elapsed)
      const speedBoost = 1 + pulse * 0.9
      const bloom = 1 + pulse * 0.25

      for (let i = SHELLS.length - 1; i >= 0; i--) {
        const shell = SHELLS[i]
        const shellDuration = 28000 / shell.speed
        const progress = ((elapsed * speedBoost) % shellDuration) / shellDuration
        drawShell(shell, progress, s, bloom, elapsed)
      }

      if (pulseRef.current > 0) {
        pulseRef.current = Math.max(0, pulseRef.current - 0.022)
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
                className={isAnimatingText ? 'text-anim-C-pull' : ''}
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
                  // Each label pulls toward the orb center (opposite of its
                  // current offset) while spiraling into the center.
                  ['--pull-x' as any]: `${-label.x}px`,
                  ['--pull-y' as any]: `${-label.y}px`,
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
        /* D: magnetic pull — each label translates to the orb center
           (-label.x, -label.y) while spiraling and shrinking */
        @keyframes textAnimCPull {
          0% { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 1; }
          60% { transform: translate(calc(var(--pull-x) * 0.6), calc(var(--pull-y) * 0.6)) scale(0.6) rotate(180deg); opacity: 0.6; }
          100% { transform: translate(var(--pull-x), var(--pull-y)) scale(0) rotate(360deg); opacity: 0; }
        }
        .text-anim-C-pull {
          animation: textAnimCPull 1s cubic-bezier(0.6, 0, 0.8, 1) forwards;
        }
      `}</style>
    </div>
  )
}
