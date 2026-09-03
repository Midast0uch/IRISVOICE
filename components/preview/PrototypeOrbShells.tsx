'use client'

import React, { useEffect, useRef, useCallback, useState } from 'react'

interface PrototypeOrbShellsProps {
  glowColor?: string
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←'

const LABELS = [
  { final: '→ Chat ←', x: 0, y: 68, swirl: '180deg' },
  { final: '↑ Menu', x: 0, y: -68, swirl: '-120deg' },
  { final: '↑↑ Voice', x: -68, y: 30, swirl: '240deg' },
]

const SIZE = 90

// C keeps its original lighter shell counts (80/56/32) — now with the
// one-shot transition behavior that used to live in D.
const SHELLS = [
  { scale: 1.05, speed: 1.0, count: 80, alpha: 0.55, size: 1.0 },
  { scale: 0.70, speed: 1.45, count: 56, alpha: 0.40, size: 0.8 },
  { scale: 0.42, speed: 0.62, count: 32, alpha: 0.85, size: 0.7 },
]

// Transition timing — moved from D. Gentler than the original D pass.
const OPENING_MS = 1700
const SETTLING_MS = 600
const TOTAL_MS = OPENING_MS + SETTLING_MS

const PULSE_DURATION = 4200

/**
 * Variant C (swapped) — Layered concentric shells + opening transition
 * + iris-shutter text disappearance.
 *
 *   Continuous idle → click → 1.7s opening (shells expand, slight bloom)
 *                      → 0.6s settling (ease back)
 *                      → rest (spiral still visible)
 *   Text labels collapse toward the orb center with axis-specific scaling
 *   (vertical labels squash vertically, side label squashes horizontally),
 *   like a camera shutter closing.
 */
export function PrototypeOrbShells({ glowColor = '#00d4ff' }: PrototypeOrbShellsProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const animStartRef = useRef<number>(0)
  const [replayCount, setReplayCount] = useState(0)
  const [activeIdx, setActiveIdx] = useState(0)
  const [scrambledSet, setScrambledSet] = useState<Set<number>>(new Set())
  const [displayTexts, setDisplayTexts] = useState<string[]>(['', '', ''])
  const [isAnimatingText, setIsAnimatingText] = useState(false)
  const scrambleTimersRef = useRef<ReturnType<typeof setInterval>[]>([])
  const switchTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    animStartRef.current = Date.now()
  }, [replayCount])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = SIZE * dpr
    canvas.height = SIZE * dpr
    ctx.scale(dpr, dpr)

    function detailScale(t: number) {
      return 0.52 + 0.48 * (0.5 + 0.5 * Math.sin((t / PULSE_DURATION) * Math.PI * 2))
    }

    function curvePoint(t: number, s: number) {
      return {
        x: 50 + (7.0 * Math.cos(t) - 3.0 * s * Math.cos(9 * t)) * 3.9,
        y: 50 + (7.0 * Math.sin(t) - 3.0 * s * Math.sin(9 * t)) * 3.9,
      }
    }

    function getAnimState(elapsed: number) {
      if (elapsed < OPENING_MS) {
        const t = elapsed / OPENING_MS
        const sin = Math.sin(t * Math.PI)
        const ease = 1 - Math.pow(1 - t, 2)
        return {
          shellScale: 0.7 + 0.35 * ease, // 0.70 → 1.05
          bloom: 1 + 0.18 * sin, // 1.00 → 1.18
          speedMult: 1 + 1.5 * sin, // 1.0× → 2.5×
          overallAlpha: 0.55 + 0.45 * ease, // 0.55 → 1.0
        }
      } else if (elapsed < TOTAL_MS) {
        const t = (elapsed - OPENING_MS) / SETTLING_MS
        const ease = 1 - Math.pow(1 - t, 2)
        return {
          shellScale: 1.05 - 0.05 * ease,
          bloom: 1.0,
          speedMult: 1.0,
          overallAlpha: 0.75 + 0.25 * ease,
        }
      } else {
        return {
          shellScale: 1.0,
          bloom: 1.0,
          speedMult: 1.0,
          overallAlpha: 1.0,
        }
      }
    }

    function drawShell(
      shell: typeof SHELLS[number],
      progress: number,
      s: number,
      scaleMul: number,
      bloom: number,
      overallAlpha: number,
      elapsed: number,
    ) {
      const currentAngle = progress * Math.PI * 2
      ctx.fillStyle = glowColor

      for (let i = 0; i < shell.count; i++) {
        const trailOffset = (i / shell.count) * Math.PI * 2
        const angle = currentAngle - trailOffset
        const pt = curvePoint(angle, s)
        const effectiveScale = shell.scale * scaleMul * bloom
        let px = ((pt.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
        let py = ((pt.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2

        const fade = 1 - i / shell.count
        // A tiny bit of depth awareness from A — narrow range (0.9–1.0) so
        // the Xur spiral has visible volume without overwhelming the shells.
        const depthWave = 0.5 + 0.5 * Math.sin(angle * 0.5 + elapsed * 0.0003)
        const depthFactor = 0.9 + 0.1 * depthWave

        const particleSize = (0.5 + fade * 1.6) * (SIZE / 100) * shell.size
        ctx.globalAlpha = fade * 0.6 * shell.alpha * overallAlpha * depthFactor
        ctx.beginPath()
        ctx.arc(px, py, particleSize, 0, Math.PI * 2)
        ctx.fill()
      }

      const lead = curvePoint(currentAngle, s)
      const effectiveScale = shell.scale * scaleMul * bloom
      const lx = ((lead.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
      const ly = ((lead.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
      ctx.globalAlpha = shell.alpha * overallAlpha
      ctx.beginPath()
      ctx.arc(lx, ly, (SIZE / 36) * shell.size, 0, Math.PI * 2)
      ctx.fill()
    }

    function draw() {
      const now = Date.now()
      const elapsed = now - (animStartRef.current || now)
      const state = getAnimState(elapsed)
      ctx.clearRect(0, 0, SIZE, SIZE)
      ctx.globalCompositeOperation = 'lighter'
      const s = detailScale(elapsed)

      for (let i = SHELLS.length - 1; i >= 0; i--) {
        const shell = SHELLS[i]
        const shellDuration = 28000 / shell.speed
        const progress = ((elapsed * state.speedMult) % shellDuration) / shellDuration
        drawShell(shell, progress, s, state.shellScale, state.bloom, state.overallAlpha, elapsed)
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
    setReplayCount(c => c + 1)
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
          }}
        >
          <canvas
            ref={canvasRef}
            style={{ width: `${SIZE}px`, height: `${SIZE}px`, display: 'block' }}
          />
        </div>
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
          {LABELS.map((label, i) => {
            // Iris shutter: each label collapses toward the orb center
            // along the AXIS that makes sense for its position.
            //   CHAT (below): collapse up + scaleY 0
            //   MENU (above): collapse down + scaleY 0
            //   VOICE (side): collapse right + scaleX 0
            const axisCollapse =
              label.x === 0
                ? { x: 0, y: -label.y, sx: 1, sy: 0.1 }
                : { x: -label.x, y: 0, sx: 0.1, sy: 1 }
            return (
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
                  className={isAnimatingText ? 'text-anim-D-iris' : ''}
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
                    transformOrigin: 'center center',
                    ['--iris-x' as any]: `${axisCollapse.x}px`,
                    ['--iris-y' as any]: `${axisCollapse.y}px`,
                    ['--iris-sx' as any]: axisCollapse.sx,
                    ['--iris-sy' as any]: axisCollapse.sy,
                  } as React.CSSProperties}
                >
                  {displayTexts[i] || ''}
                </span>
              </div>
            )
          })}
        </div>
      </div>
      <style>{`
        @keyframes protoFloat {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-6px); }
        }
        /* C: iris shutter — each label translates to the orb center while
           scaling along the appropriate axis (vertical labels squash
           vertically, side label squashes horizontally) */
        @keyframes textAnimDIris {
          0% { transform: translate(0, 0) scale(1, 1); opacity: 1; }
          100% { transform: translate(var(--iris-x), var(--iris-y)) scale(var(--iris-sx), var(--iris-sy)); opacity: 0; }
        }
        .text-anim-D-iris {
          animation: textAnimDIris 0.9s cubic-bezier(0.6, 0, 0.8, 1) forwards;
        }
      `}</style>
    </div>
  )
}
