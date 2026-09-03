'use client'

import React, { useEffect, useRef, useCallback, useState } from 'react'

interface PrototypeOrbShellsRotatingProps {
  glowColor?: string
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←'

const LABELS = [
  { final: '→ Chat ←', x: 0, y: 68, swirl: '180deg' },
  { final: '↑ Menu', x: 0, y: -68, swirl: '-120deg' },
  { final: '↑↑ Voice', x: -68, y: 30, swirl: '240deg' },
]

const SIZE = 90

// Same shells as C — this is a "copy of C" per spec
const SHELLS = [
  { scale: 1.05, speed: 1.0, count: 80, alpha: 0.55, size: 1.0 },
  { scale: 0.70, speed: 1.45, count: 56, alpha: 0.40, size: 0.8 },
  { scale: 0.42, speed: 0.62, count: 32, alpha: 0.85, size: 0.7 },
]

const PULSE_DURATION = 4200

// Animation timing — same as C
const OPENING_MS = 1700
const SETTLING_MS = 600
const TOTAL_MS = OPENING_MS + SETTLING_MS

/**
 * Rotating variant — a copy of C's shells whose click behavior rotates
 * between THREE PAIRED combos (orb animation + text animation):
 *
 *   C-pair  →  C's opening transition  +  C's iris-shutter text
 *   D-pair  →  D's gentle burst        +  D's magnetic-pull text
 *   A-pair  →  A's bigger bloom        +  A's fade-out text
 *
 * The pair is picked at random on each click, so the user can feel all
 * three "complete feels" in a single orb without having to choose.
 */
type PairMode = 'C' | 'D' | 'A'

export function PrototypeOrbShellsRotating({ glowColor = '#00d4ff' }: PrototypeOrbShellsRotatingProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const startTimeRef = useRef<number>(0)
  const animStartRef = useRef<number>(0)
  const pulseRef = useRef<number>(0)
  const pulseARef = useRef<number>(0) // A-pair has its own pulse that decays slower
  const pairModeRef = useRef<PairMode | null>(null) // null = no click yet, idle
  // Cycle counter — ensures every third click is the C-pair so the user
  // can always verify C's behavior. To revert to random pick, replace
  // `clickCountRef.current % 3` with `Math.floor(Math.random() * 3)`.
  const clickCountRef = useRef<number>(0)
  const [pairMode, setPairMode] = useState<PairMode | null>(null)
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

    function getTransitionState(elapsed: number) {
      if (elapsed < OPENING_MS) {
        const t = elapsed / OPENING_MS
        const sin = Math.sin(t * Math.PI)
        const ease = 1 - Math.pow(1 - t, 2)
        return {
          // Matches PrototypeOrbShells (C) exactly so the C-pair lands the
          // same as clicking the real C variant.
          shellScale: 0.7 + 0.35 * ease,
          bloom: 1 + 0.18 * sin,
          speedMult: 1 + 1.5 * sin,
          overallAlpha: 0.55 + 0.45 * ease,
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
        // Same tiny depth awareness as C (0.9–1.0)
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
      const elapsed = Date.now() - (startTimeRef.current ?? Date.now())
      const pulse = pulseRef.current
      const mode = pairModeRef.current
      ctx.clearRect(0, 0, SIZE, SIZE)
      ctx.globalCompositeOperation = 'lighter'
      const s = detailScale(elapsed)

      let scaleMul = 1
      let bloom = 1
      let speedMult = 1
      let overallAlpha = 1

      if (mode === 'C') {
        // C-pair: opening transition (1.7s opening, 0.6s settling, then rest)
        const transitionElapsed = Date.now() - animStartRef.current
        const state = getTransitionState(transitionElapsed)
        scaleMul = state.shellScale
        bloom = state.bloom
        speedMult = state.speedMult
        overallAlpha = state.overallAlpha
      } else if (mode === 'D') {
        // D-pair: gentle burst (0.9× speed, 0.25 bloom, ~0.75s decay)
        speedMult = 1 + pulse * 0.9
        bloom = 1 + pulse * 0.25
      } else if (mode === 'A') {
        // A-pair: bloom — slowed further per user feedback
        // Now 0.7× speed / 0.25 bloom (less intense) with a slower
        // ~2s decay (longer, more deliberate duration).
        const aPulse = pulseARef.current
        speedMult = 1 + aPulse * 0.7
        bloom = 1 + aPulse * 0.25
      }
      // else: idle (mode is null) — all multipliers stay at 1

      for (let i = SHELLS.length - 1; i >= 0; i--) {
        const shell = SHELLS[i]
        const shellDuration = 28000 / shell.speed
        const progress = ((elapsed * speedMult) % shellDuration) / shellDuration
        drawShell(shell, progress, s, scaleMul, bloom, overallAlpha, elapsed)
      }

      if (pulseRef.current > 0) {
        pulseRef.current = Math.max(0, pulseRef.current - 0.022)
      }
      // A-pair has its own slower decay (~2s instead of ~0.75s) so the
      // bloom is slow and deliberate, not a flash.
      if (pulseARef.current > 0) {
        pulseARef.current = Math.max(0, pulseARef.current - 0.008)
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
    // Cycle in order C → D → A → C → D → A so every third click is the
    // C-pair (the one the user specifically wanted present).
    const modes: PairMode[] = ['C', 'D', 'A']
    const next = modes[clickCountRef.current % 3]
    clickCountRef.current += 1
    pairModeRef.current = next
    setPairMode(next)

    if (next === 'C') {
      // Transition uses time-based state machine — reset its clock
      animStartRef.current = Date.now()
    } else if (next === 'D') {
      // D-pair pulse — decays fast (~0.75s)
      pulseRef.current = 1
    } else if (next === 'A') {
      // A-pair pulse — decays slower (~1.4s) so the bloom is less frantic
      pulseARef.current = 1
    }

    setIsAnimatingText(true)
  }, [])

  // Text animation class + CSS variables for the CURRENT pair. The pair
  // is null before any click, so no animation is applied.
  const getTextClass = () => {
    if (!isAnimatingText || !pairMode) return ''
    if (pairMode === 'C') return 'text-anim-rot-iris'
    if (pairMode === 'D') return 'text-anim-rot-pull'
    return 'text-anim-rot-fade' // A
  }

  const getTextVars = (label: { x: number; y: number }) => {
    if (pairMode === 'C') {
      // C's iris shutter: axis-specific collapse
      const axisCollapse =
        label.x === 0
          ? { x: 0, y: -label.y, sx: 1, sy: 0.1 }
          : { x: -label.x, y: 0, sx: 0.1, sy: 1 }
      return {
        ['--iris-x' as any]: `${axisCollapse.x}px`,
        ['--iris-y' as any]: `${axisCollapse.y}px`,
        ['--iris-sx' as any]: axisCollapse.sx,
        ['--iris-sy' as any]: axisCollapse.sy,
      }
    } else if (pairMode === 'D') {
      // D's magnetic pull: translate to orb center
      return {
        ['--pull-x' as any]: `${-label.x}px`,
        ['--pull-y' as any]: `${-label.y}px`,
      }
    }
    // A's fade: no variables needed
    return {}
  }

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
                className={getTextClass()}
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
                  ...getTextVars(label),
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
        /* C-pair text: iris shutter (axis-specific collapse) */
        @keyframes textAnimRotIris {
          0% { transform: translate(0, 0) scale(1, 1); opacity: 1; }
          100% { transform: translate(var(--iris-x), var(--iris-y)) scale(var(--iris-sx), var(--iris-sy)); opacity: 0; }
        }
        .text-anim-rot-iris {
          animation: textAnimRotIris 0.9s cubic-bezier(0.6, 0, 0.8, 1) forwards;
        }
        /* D-pair text: magnetic pull (translate to center, spiral, scale to 0) */
        @keyframes textAnimRotPull {
          0% { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 1; }
          60% { transform: translate(calc(var(--pull-x) * 0.6), calc(var(--pull-y) * 0.6)) scale(0.6) rotate(180deg); opacity: 0.6; }
          100% { transform: translate(var(--pull-x), var(--pull-y)) scale(0) rotate(360deg); opacity: 0; }
        }
        .text-anim-rot-pull {
          animation: textAnimRotPull 1s cubic-bezier(0.6, 0, 0.8, 1) forwards;
        }
        /* A-pair text: simple fade out */
        @keyframes textAnimRotFade {
          0% { opacity: 1; }
          100% { opacity: 0; }
        }
        .text-anim-rot-fade {
          animation: textAnimRotFade 0.8s ease-out forwards;
        }
      `}</style>
    </div>
  )
}
