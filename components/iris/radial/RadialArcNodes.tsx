"use client"

import React, { useEffect, useMemo, useState, useRef, useCallback } from "react"
import { CATEGORIES } from "./categories"
import { HexNode } from "./HexNode"
import { hexToRgba } from "../utils/hexToRgba"
import {
  type WinTransition,
  pickRandomTransition,
  photonFlash,
  WIN_DURATION_MS,
  ENTER_DURATION_MS,
} from "./WinTransitionEngine"

// ── Types ────────────────────────────────────────────────────────────

export type NodePosition = { x: number; y: number; sx: number; sy: number; angle: number }
export type NodeStyleFn = (idx: number, pos: NodePosition) => React.CSSProperties

export interface RadialArcNodesProps {
  glowColor: string
  isVisible: boolean
  onCategorySelect: (id: string) => void
  /** Optional external node style override. When not provided, internal
   *  WinTransitionEngine enter/exit animations are used. */
  nodeStyle?: NodeStyleFn
  extraSVG?: React.ReactNode
}

// ── Seeded particle generator (deterministic, client-side only) ──────

function mulberry32(seed: number) {
  return function () {
    let t = (seed += 0x6d2b79f5)
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

type Particle = { x: number; y: number; size: number; opacity: number }

function useParticles(count: number, minDist: number, maxDist: number, seed = 42): Particle[] {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  return useMemo(() => {
    if (!mounted) return []
    const rng = mulberry32(seed)
    return Array.from({ length: count }, (_, i) => {
      const angle = (i / count) * Math.PI * 2 + (rng() - 0.5) * 0.5
      const dist = minDist + rng() * (maxDist - minDist)
      return {
        x: Math.cos(angle) * dist,
        y: Math.sin(angle) * dist,
        size: 1 + rng() * 2.5,
        opacity: 0.15 + rng() * 0.4,
      }
    })
  }, [mounted, count, minDist, maxDist, seed])
}

// ── RadialArcNodes ───────────────────────────────────────────────────

/**
 * RadialArcNodes — the level 2 category menu for XurOrb.
 *
 * Extracted from the C-Random Rotate winner in MenuMockups.tsx.
 * Renders an SVG arc with 6 hex category nodes positioned on a semicircle.
 *
 * Uses WinTransitionEngine internally for enter/exit animations:
 * - When isVisible goes false→true: nodes enter with a random transition
 *   (spiral/gravity/magnet) + Photon Burst flash
 * - When isVisible goes true→false: nodes exit with a random transition
 * - Each transition picks a different type than the previous one
 *
 * If an external `nodeStyle` is provided, it overrides the internal
 * transition animations (for XurOrb to control if needed).
 *
 * Container: 246×246, same as prototype.
 */
export function RadialArcNodes({
  glowColor,
  isVisible,
  onCategorySelect,
  nodeStyle,
  extraSVG,
}: RadialArcNodesProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  const particles = useParticles(20, 55, 130, 88)

  // ── WinTransitionEngine state ────────────────────────────────────
  const [exitT, setExitT] = useState(0)       // 0 = not exiting, 1 = fully exited
  const [enterT, setEnterT] = useState(1)     // 1 = fully entered (no animation)
  const [isExiting, setIsExiting] = useState(false)
  const [transitionType, setTransitionType] = useState<WinTransition>('spiral')
  const rafRef = useRef<number>(0)
  const prevVisibleRef = useRef(isVisible)

  useEffect(() => { setMounted(true) }, [])

  // ── Trigger enter/exit when isVisible changes ────────────────────
  useEffect(() => {
    if (prevVisibleRef.current === isVisible) return
    prevVisibleRef.current = isVisible

    if (isVisible) {
      // Enter: nodes fly back in with Photon Burst flash
      setTransitionType(t => pickRandomTransition(t))
      setExitT(0)
      setIsExiting(false)
      setEnterT(0)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / ENTER_DURATION_MS)
        setEnterT(t)
        if (t < 1) rafRef.current = requestAnimationFrame(animate)
      }
      rafRef.current = requestAnimationFrame(animate)
    } else {
      // Exit: randomly pick a transition type, animate nodes out
      setTransitionType(t => pickRandomTransition(t))
      setIsExiting(true)
      setExitT(0)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / WIN_DURATION_MS)
        setExitT(t)
        if (t < 1) {
          rafRef.current = requestAnimationFrame(animate)
        } else {
          // Exit complete — hide SVG arc, particles, and spokes
          setIsExiting(false)
        }
      }
      rafRef.current = requestAnimationFrame(animate)
    }
  }, [isVisible])

  // Cleanup rAF
  useEffect(() => {
    return () => cancelAnimationFrame(rafRef.current)
  }, [])

  // ── Positions ────────────────────────────────────────────────────
  const positions = useMemo<NodePosition[]>(() => {
    if (!mounted) return Array.from({ length: 6 }, () => ({ x: 0, y: 0, sx: 123, sy: 123, angle: 0 }))
    return Array.from({ length: 6 }, (_, i) => {
      const angle = Math.PI + (i / 5) * Math.PI
      const x = Math.cos(angle) * 90
      const y = Math.sin(angle) * 90
      return { x, y, sx: Math.round((123 + x) * 100) / 100, sy: Math.round((123 + y) * 100) / 100, angle }
    })
  }, [mounted])

  const hasHover = hoveredId !== null

  const arcPath = (a1: number, a2: number, r = 90) => {
    const x1 = Math.round((123 + Math.cos(a1) * r) * 100) / 100
    const y1 = Math.round((123 + Math.sin(a1) * r) * 100) / 100
    const x2 = Math.round((123 + Math.cos(a2) * r) * 100) / 100
    const y2 = Math.round((123 + Math.sin(a2) * r) * 100) / 100
    return `M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`
  }

  const fullArcPath = arcPath(Math.PI, 2 * Math.PI)

  const activeArcPath = (() => {
    if (!hoveredId) return null
    const idx = CATEGORIES.findIndex(c => c.id === hoveredId)
    if (idx < 0) return null
    return arcPath(positions[Math.max(0, idx - 1)].angle, positions[Math.min(5, idx + 1)].angle)
  })()

  const labelOffsets: Record<number, { dx: number; dy: number; align: string }> = {
    0: { dx: -15, dy: 2, align: 'right' },
    1: { dx: -8, dy: -7, align: 'right' },
    2: { dx: 0, dy: -11, align: 'center' },
    3: { dx: 0, dy: -11, align: 'center' },
    4: { dx: 8, dy: -7, align: 'left' },
    5: { dx: 15, dy: 2, align: 'left' },
  }

  // ── Internal node style with WinTransitionEngine ─────────────────
  const internalNodeStyle = useCallback((i: number, pos: NodePosition): React.CSSProperties => {
    // If fully entered and not exiting, show at rest position
    if (enterT >= 1 && !isExiting) {
      return {
        transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))`,
        opacity: 1,
        transition: 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
      }
    }

    if (isExiting) {
      // Exit animation: apply current transition type with Photon Burst flash
      const flashT = Math.min(1, exitT / 0.15)
      const brightness = 1 + flashT * 2
      const scale = 1 + flashT * 0.25
      const done = exitT >= 1

      if (transitionType === 'spiral') {
        const baseAngle = Math.PI + (i / 5) * Math.PI
        const angle = baseAngle + exitT * Math.PI / 2
        const extraR = exitT * 50
        const dx = Math.cos(angle) * extraR
        const dy = Math.sin(angle) * extraR
        const rot = exitT * 90
        return {
          transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) rotate(${rot}deg) scale(${scale})`,
          opacity: done ? 0 : 1 - exitT,
          filter: `brightness(${brightness})`,
          visibility: done ? 'hidden' as const : 'visible' as const,
          transition: 'none',
        }
      } else if (transitionType === 'gravity') {
        const distFromCenter = Math.abs(i - 2.5) / 2.5
        const stagger = distFromCenter * 0.3
        const t = Math.max(0, Math.min(1, (exitT - stagger) / 0.7))
        const gravity = t * t * 150
        const rot = t * 30 * (i < 3 ? -1 : 1)
        return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y + gravity}px)) rotate(${rot}deg) scale(${scale})`,
          opacity: done ? 0 : 1 - exitT,
          filter: `brightness(${brightness})`,
          visibility: done ? 'hidden' as const : 'visible' as const,
          transition: 'none',
        }
      } else {
        // magnet
        const stagger = i / 5
        const t = Math.max(0, Math.min(1, (exitT - stagger * 0.4) / 0.6))
        const ease = t * t
        return {
          transform: `translate(calc(-50% + ${pos.x * (1 - ease * 0.8)}px), calc(-50% + ${pos.y * (1 - ease * 0.8)}px)) scale(${1 - ease * 0.8})`,
          opacity: 1 - ease,
          filter: `brightness(${brightness})`,
          visibility: done ? 'hidden' as const : 'visible' as const,
          transition: 'none',
        }
      }
    }

    // Enter animation: reverse current transition back to position with Photon Burst flash
    const { brightness, scale } = photonFlash(enterT)
    const reversed = 1 - enterT

    if (transitionType === 'spiral') {
      const baseAngle = Math.PI + (i / 5) * Math.PI
      const spiralAngle = baseAngle + Math.PI / 2
      const dx = Math.cos(spiralAngle) * 50 * reversed
      const dy = Math.sin(spiralAngle) * 50 * reversed
      const rot = 90 * reversed
      return {
        transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) rotate(${rot}deg) scale(${scale})`,
        opacity: enterT,
        filter: `brightness(${brightness})`,
        visibility: 'visible' as const,
        transition: 'none',
      }
    } else if (transitionType === 'gravity') {
      const gravity = reversed * 150
      const rot = reversed * 30 * (i < 3 ? -1 : 1)
      return {
        transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y + gravity}px)) rotate(${rot}deg) scale(${scale})`,
        opacity: enterT,
        filter: `brightness(${brightness})`,
        visibility: 'visible' as const,
        transition: 'none',
      }
    } else {
      // magnet
      const shrink = reversed * 0.8
      return {
        transform: `translate(calc(-50% + ${pos.x * (1 - reversed * 0.8)}px), calc(-50% + ${pos.y * (1 - reversed * 0.8)}px)) scale(${1 - shrink})`,
        opacity: enterT,
        filter: `brightness(${brightness})`,
        visibility: 'visible' as const,
        transition: 'none',
      }
    }
  }, [enterT, exitT, isExiting, transitionType])

  // Use external nodeStyle if provided, otherwise use internal WinTransitionEngine
  const effectiveNodeStyle = nodeStyle ?? internalNodeStyle

  // Nodes are visible during enter, at rest, and during exit (until fully gone)
  const nodesVisible = isVisible || isExiting

  return (
    <div className="relative" style={{ width: 246, height: 246, opacity: nodesVisible ? 1 : 0, transition: 'opacity 0.3s ease' }}>
      {/* SVG arc + spokes + hover ring */}
      {nodesVisible && (
        <svg width={246} height={246} className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
          <defs>
            <linearGradient id="arc-base-grad-radial" x1="50%" y1="50%" x2="50%" y2="0%">
              <stop offset="0%" stopColor={hexToRgba(glowColor, 0.05)} />
              <stop offset="100%" stopColor={hexToRgba(glowColor, 0.6)} />
            </linearGradient>
          </defs>
          {mounted && <path d={fullArcPath} fill="none" stroke={glowColor} strokeWidth={0.8} opacity={0.15} />}
          {mounted && activeArcPath && (
            <path d={activeArcPath} fill="none" stroke={glowColor} strokeWidth={2.5}
              opacity={0.7} strokeLinecap="round" style={{ transition: 'opacity 0.3s' }} />
          )}
          {mounted && positions.map((pos, i) => {
            const isActive = hoveredId === CATEGORIES[i].id
            const hIdx = hasHover ? CATEGORIES.findIndex(c => c.id === hoveredId) : -1
            const isNearby = hasHover && Math.abs(hIdx - i) === 1
            return (
              <line key={`radial-spoke-${i}`} x1={123} y1={123} x2={pos.sx} y2={pos.sy}
                stroke={glowColor}
                strokeWidth={isActive ? 1.5 : isNearby ? 0.8 : 0.4}
                opacity={hasHover ? (isActive ? 0.85 : isNearby ? 0.3 : 0.06) : 0}
                style={{ transition: 'opacity 0.4s ease, stroke-width 0.3s' }} />
            )
          })}
          {mounted && hoveredId && (() => {
            const idx = CATEGORIES.findIndex(c => c.id === hoveredId)
            if (idx < 0) return null
            const pos = positions[idx]
            return <circle cx={Math.round(((123 + pos.sx) / 2) * 100) / 100} cy={Math.round(((123 + pos.sy) / 2) * 100) / 100}
              r={2.5} fill={glowColor} opacity={0.8} style={{ animation: 'pulse 1.5s ease-in-out infinite' }} />
          })()}
          {mounted && hoveredId && (
            <circle cx={123} cy={123} r={10} fill="none" stroke={glowColor}
              strokeWidth={1} opacity={0.4} style={{ animation: 'pulse 2s ease-in-out infinite' }} />
          )}
          {extraSVG}
        </svg>
      )}

      {/* Particles */}
      {nodesVisible && (
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
          {particles.map((p, i) => (
            <div key={i} className="absolute rounded-full" style={{
              left: `calc(50% + ${p.x}px)`, top: `calc(50% + ${p.y}px)`,
              width: p.size, height: p.size, background: glowColor, opacity: p.opacity,
              boxShadow: `0 0 ${p.size * 2}px ${glowColor}`,
            }} />
          ))}
        </div>
      )}

      {/* Category hex nodes */}
      {mounted && CATEGORIES.map((cat, i) => (
        <div key={cat.id} className="absolute" style={{
          left: '50%', top: '50%',
          ...effectiveNodeStyle(i, positions[i]),
        }}>
          <HexNode
            glowColor={glowColor}
            icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)}
            onClick={() => onCategorySelect(cat.id)}
          />
        </div>
      ))}

      {/* Category label on hover */}
      {mounted && hoveredId && nodesVisible && (() => {
        const idx = CATEGORIES.findIndex(c => c.id === hoveredId)
        if (idx < 0) return null
        const pos = positions[idx]
        const off = labelOffsets[idx]
        const lx = Math.max(16, Math.min(230, pos.sx + off.dx))
        const ly = Math.max(8, Math.min(238, pos.sy + off.dy))
        return (
          <div className="absolute pointer-events-none" style={{
            left: `${lx}px`, top: `${ly}px`,
            transform: off.align === 'center' ? 'translate(-50%, -100%)' : off.align === 'right' ? 'translate(-100%, -100%)' : 'translate(0, -100%)',
            zIndex: 10,
          }}>
            <span style={{
              display: 'block', fontSize: '10px', fontWeight: 700,
              letterSpacing: '0.14em', textTransform: 'uppercase' as const,
              color: glowColor, textShadow: `0 0 12px ${glowColor}80, 0 0 4px ${glowColor}40`,
              whiteSpace: 'nowrap', opacity: 0.9,
              fontFamily: "'Courier New', Courier, monospace",
              textAlign: off.align as 'left' | 'center' | 'right',
            }}>
              {CATEGORIES[idx].label}
            </span>
          </div>
        )
      })()}
    </div>
  )
}
