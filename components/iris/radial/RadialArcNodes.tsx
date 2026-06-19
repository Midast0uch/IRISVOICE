"use client"

import React, { useEffect, useMemo, useState } from "react"
import { CATEGORIES } from "./categories"
import { HexNode } from "./HexNode"
import { hexToRgba } from "../utils/hexToRgba"

// ── Types ────────────────────────────────────────────────────────────

export type NodePosition = { x: number; y: number; sx: number; sy: number; angle: number }
export type NodeStyleFn = (idx: number, pos: NodePosition) => React.CSSProperties

export interface RadialArcNodesProps {
  glowColor: string
  isVisible: boolean
  onCategorySelect: (id: string) => void
  nodeStyle?: NodeStyleFn
  extraSVG?: React.ReactNode
}

// ── Seeded particle generator (deterministic, client-side only) ──────
// Uses a mulberry32 PRNG so particles are identical on every render.
// No Math.random() — prevents SSR hydration mismatch.

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

// ── Default node style (visible, positioned on arc) ──────────────────

const defaultNodeStyle: NodeStyleFn = (_idx, pos) => ({
  transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))`,
  opacity: 1,
  transition: 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
})

// ── RadialArcNodes ───────────────────────────────────────────────────

/**
 * RadialArcNodes — the level 2 category menu for XurOrb.
 *
 * Extracted from the C-Random Rotate winner in MenuMockups.tsx.
 * Renders an SVG arc with 6 hex category nodes positioned on a semicircle.
 *
 * Key differences from the prototype's RadialArcBase:
 * - NO Orb component inside — XurOrb renders the orb separately
 * - NO state machine for transitions — enter/exit transitions come from
 *   XurOrb via the `nodeStyle` prop
 * - Accepts `onCategorySelect` for hex node clicks
 * - Accepts `isVisible` to control show/hide
 *
 * Container: 246×246, same as prototype.
 */
export function RadialArcNodes({
  glowColor,
  isVisible,
  onCategorySelect,
  nodeStyle = defaultNodeStyle,
  extraSVG,
}: RadialArcNodesProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  const particles = useParticles(20, 55, 130, 88)

  useEffect(() => { setMounted(true) }, [])

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

  return (
    <div className="relative" style={{ width: 246, height: 246, opacity: isVisible ? 1 : 0, transition: 'opacity 0.3s ease' }}>
      {/* SVG arc + spokes + hover ring */}
      {isVisible && (
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
      {isVisible && (
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
          ...nodeStyle(i, positions[i]),
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
      {mounted && hoveredId && isVisible && (() => {
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
