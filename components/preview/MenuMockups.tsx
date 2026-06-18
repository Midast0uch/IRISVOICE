'use client'

import React, { useState, useEffect, useMemo } from 'react'
import type { ElementType } from 'react'
import { Mic, Palette, Activity } from 'lucide-react'
import { IconRobot, IconTopologyStar3, IconBasketCog } from '@tabler/icons-react'
import { PrototypeOrbBreathing } from './PrototypeOrbBreathing'

// ── Shared category data ─────────────────────────────────────────────
const CATEGORIES = [
  { id: 'voice', label: 'Voice', icon: Mic },
  { id: 'agent', label: 'Agent', icon: IconRobot },
  { id: 'automate', label: 'Automate', icon: IconTopologyStar3 },
  { id: 'system', label: 'System', icon: IconBasketCog },
  { id: 'customize', label: 'Customize', icon: Palette },
  { id: 'monitor', label: 'Monitor', icon: Activity },
] as const

// ── Hex node (40px) — glassmorphic hex ───────────────────────────────
const HEX_CLIP = 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)'

function HexNode({
  glowColor,
  icon: Icon,
  isActive,
  onHover,
  onClick,
  size = 40,
}: {
  glowColor: string
  icon: ElementType
  isActive: boolean
  onHover: (hovering: boolean) => void
  onClick?: () => void
  size?: number
}) {
  return (
    <button
      className="relative flex items-center justify-center cursor-pointer"
      style={{
        width: size,
        height: size,
        clipPath: HEX_CLIP,
        border: 'none',
        background: 'none',
        padding: 0,
        opacity: isActive ? 1 : 0.8,
        transform: isActive ? 'scale(1.08)' : 'scale(1)',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        flexShrink: 0,
      }}
      onClick={onClick}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      {/* Outer glow */}
      <div
        className="absolute pointer-events-none"
        style={{
          inset: -6,
          clipPath: HEX_CLIP,
          background: `radial-gradient(circle, ${glowColor}${Math.round(0.35 * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
          filter: 'blur(6px)',
          opacity: isActive ? 1 : 0.4,
          transition: 'opacity 0.3s ease',
        }}
      />
      {/* Liquid metal border */}
      <div
        className="absolute pointer-events-none"
        style={{
          inset: 0,
          clipPath: HEX_CLIP,
          background: `conic-gradient(from 0deg,
            #ffffff 0deg,
            ${glowColor} 45deg,
            #101014 120deg,
            #ffffff 180deg,
            ${glowColor} 225deg,
            #101014 300deg,
            #ffffff 360deg) border-box`,
          WebkitMask: 'linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0)',
          WebkitMaskComposite: 'destination-out',
          maskComposite: 'exclude',
          filter: 'drop-shadow(0 0 1px rgba(255,255,255,0.3))',
          zIndex: 2,
        }}
      />
      {/* Glassmorphic base */}
      <div
        className="absolute inset-0 flex items-center justify-center overflow-hidden"
        style={{
          clipPath: HEX_CLIP,
          background: isActive
            ? `linear-gradient(135deg, color-mix(in srgb, ${glowColor}, #0a0a0c 80%) 0%, #0a0a0c 100%)`
            : `linear-gradient(135deg, #0a0a0c 0%, color-mix(in srgb, ${glowColor}, #0a0a0c 90%) 100%)`,
          boxShadow: '0 2px 8px rgba(0,0,0,0.5), inset 0 1px 2px rgba(255,255,255,0.2)',
          zIndex: 3,
        }}
      >
        {/* Hex-grid pattern overlay */}
        <div
          className="absolute inset-0 pointer-events-none opacity-[0.04]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='49' viewBox='0 0 28 49'%3E%3Cg fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.4'%3E%3Cpath d='M13.99 9.25l13 7.5v15l-13 7.5L1 31.75v-15l12.99-7.5zM3 17.9v12.7l10.99 6.34 11-6.35V17.9l-11-6.34L3 17.9zM0 15l12.98-7.5V0h-2v6.35L0 12.69v2.3zm0 18.5L12.98 41v8h-2v-6.85L0 35.81v-2.3zM15 0v7.5L27.99 15H28v-2.31h-.01L17 6.35V0h-2zm0 49v-8l12.99-7.5H28v2.31h-.01L17 42.15V49h-2z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
            backgroundSize: `${size * 0.35}px ${size * 0.6}px`,
          }}
        />
        {/* Active state fill */}
        {isActive && (
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              clipPath: HEX_CLIP,
              background: `radial-gradient(circle, ${glowColor}35 0%, transparent 70%)`,
              zIndex: 3,
            }}
          />
        )}
        {/* Icon */}
        <div className="relative z-10 flex items-center justify-center pointer-events-none">
          <Icon
            style={{
              width: size * 0.4,
              height: size * 0.4,
              color: isActive ? '#ffffff' : '#94a3b8',
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.5))',
            }}
            strokeWidth={1.5}
          />
        </div>
      </div>
    </button>
  )
}

// ── Orb component (no labels, no glitch text by default) ─────────────
// Positioned absolutely at the center of the parent container.
// Both the Orb and the hex nodes use the same coordinate origin
// (left:50%, top:50% of the parent) so they are always aligned.
// showLabels: when true, enables PrototypeOrbBreathing's built-in glitch text.
// onClick: forwarded for orb click → glitch text transitions.
const ORB_SIZE = 180
function Orb({ glowColor, showLabels = false, onClick }: { glowColor: string; showLabels?: boolean; onClick?: () => void }) {
  return (
    <div
      className="absolute"
      style={{
        left: '50%',
        top: '50%',
        width: ORB_SIZE,
        height: ORB_SIZE,
        transform: 'translate(-50%, -50%)',
        zIndex: 0,
        cursor: onClick ? 'pointer' : undefined,
      }}
      onClick={onClick}
    >
      <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={showLabels} />
    </div>
  )
}

// ── Helper: compute radial positions (client-side only) ──────────────
function useRadialPositions(count: number, radius: number, startAngle = -Math.PI / 2) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  return useMemo(() => {
    if (!mounted) return Array.from({ length: count }, () => ({ x: 0, y: 0 }))
    return Array.from({ length: count }, (_, i) => {
      const angle = startAngle + (i / count) * Math.PI * 2
      return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius }
    })
  }, [mounted, count, radius, startAngle])
}

// ── Seeded particle generator (deterministic, client-side only) ──────
// Uses a mulberry32 PRNG seeded with a constant so particles are identical
// on every render. No Math.random() — prevents SSR hydration mismatch.
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

// ── Mockup 1: Radial Hex (PRIMARY) ───────────────────────────────────
function MockupRadialHex({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const positions = useRadialPositions(6, 108)

  return (
    <div className="relative" style={{ width: 300, height: 300 }}>
      <Orb glowColor={glowColor} />
      {CATEGORIES.map((cat, i) => (
        <div
          key={cat.id}
          className="absolute"
          style={{
            left: '50%',
            top: '50%',
            transform: `translate(calc(-50% + ${positions[i].x}px), calc(-50% + ${positions[i].y}px))`,
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 2: Radial Compact (tighter ring) ──────────────────────────
function MockupRadialCompact({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const positions = useRadialPositions(6, 82)

  return (
    <div className="relative" style={{ width: 260, height: 260 }}>
      <Orb glowColor={glowColor} />
      {CATEGORIES.map((cat, i) => (
        <div
          key={cat.id}
          className="absolute"
          style={{
            left: '50%',
            top: '50%',
            transform: `translate(calc(-50% + ${positions[i].x}px), calc(-50% + ${positions[i].y}px))`,
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)}
            size={36}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 3: Orbital (varying distances + rings) ────────────────────
// ── Mockup 3: Iris Bloom (petal-shaped radial layout) ────────────────
function MockupOrbital({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  const c = 160
  const r = 125

  return (
    <div className="relative" style={{ width: 320, height: 320 }}>
      <Orb glowColor={glowColor} />
      {/* Petal paths — curved strokes from orb center to node tips */}
      <svg width={320} height={320} className="absolute inset-0 pointer-events-none">
        <defs>
          <linearGradient id={`petal-grad`} x1="50%" y1="50%" x2="50%" y2="0%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0.6)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.05)} />
          </linearGradient>
        </defs>
        {CATEGORIES.map((cat, i) => {
          const angle = (i / 6) * Math.PI * 2 - Math.PI / 2
          const tx = Math.round((c + Math.cos(angle) * r) * 100) / 100
          const ty = Math.round((c + Math.sin(angle) * r) * 100) / 100
          // Control point pulled slightly inward for petal shape
          const cpDist = r * 0.4
          const cpx = Math.round((c + Math.cos(angle) * cpDist) * 100) / 100
          const cpy = Math.round((c + Math.sin(angle) * cpDist) * 100) / 100
          return (
            <g key={cat.id}>
              <path
                d={`M ${c} ${c} Q ${cpx} ${cpy} ${tx} ${ty}`}
                fill="none"
                stroke={`url(#petal-grad)`}
                strokeWidth={hoveredId === cat.id ? 2.5 : 1.5}
                strokeLinecap="round"
                opacity={hoveredId && hoveredId !== cat.id ? 0.2 : 0.7}
                style={{ transition: 'opacity 0.3s, stroke-width 0.3s' }}
              />
              {/* Small node connector dot at petal tip */}
              <circle cx={tx} cy={ty} r={2} fill={glowColor} opacity={0.4} />
            </g>
          )
        })}
      </svg>
      {/* Category nodes at petal tips */}
      {mounted && CATEGORIES.map((cat, i) => {
        const angle = (i / 6) * Math.PI * 2 - Math.PI / 2
        return (
          <div
            key={cat.id}
            className="absolute"
            style={{
              left: `${((c + Math.cos(angle) * r) / 320) * 100}%`,
              top: `${((c + Math.sin(angle) * r) / 320) * 100}%`,
              transform: 'translate(-50%, -50%)',
            }}
          >
            <HexNode
              glowColor={glowColor}
              icon={cat.icon}
              isActive={hoveredId === cat.id}
              onHover={(v) => setHoveredId(v ? cat.id : null)}
              size={38}
            />
          </div>
        )
      })}
    </div>
  )
}

// ── Mockup 4: Orbital Stacked (two orbit layers) ─────────────────────
// ── Mockup 4: Constellation (geometric star pattern with connecting lines) ──
function MockupOrbitalStacked({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  const c = 160
  const r = 130

  // Calculate 6 node positions forming a hexagon
  const positions = CATEGORIES.map((_, i) => {
    const angle = (i / 6) * Math.PI * 2 - Math.PI / 2
    return { x: Math.round((c + Math.cos(angle) * r) * 100) / 100, y: Math.round((c + Math.sin(angle) * r) * 100) / 100, angle }
  })

  return (
    <div className="relative" style={{ width: 320, height: 320 }}>
      <Orb glowColor={glowColor} />
      {/* SVG: constellation lines connecting all nodes */}
      <svg width={320} height={320} className="absolute inset-0 pointer-events-none">
        <defs>
          <radialGradient id={`constellation-fade`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0.3)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.05)} />
          </radialGradient>
        </defs>
        {/* Connect every node to every other node (complete graph) */}
        {positions.map((p1, i) =>
          positions.slice(i + 1).map((p2, j) => {
            const idx = `${i}-${i + 1 + j}`
            const isActive = hoveredId && (hoveredId === CATEGORIES[i].id || hoveredId === CATEGORIES[i + 1 + j].id)
            return (
              <line
                key={idx}
                x1={p1.x} y1={p1.y}
                x2={p2.x} y2={p2.y}
                stroke={glowColor}
                strokeWidth={isActive ? 1 : 0.5}
                opacity={hoveredId ? (isActive ? 0.6 : 0.08) : 0.2}
                style={{ transition: 'opacity 0.3s, stroke-width 0.3s' }}
              />
            )
          })
        )}
        {/* Small dots at midpoints of each line */}
        {positions.map((p1, i) =>
          positions.slice(i + 1).map((p2, j) => {
            const mx = (p1.x + p2.x) / 2
            const my = (p1.y + p2.y) / 2
            return (
              <circle key={`dot-${i}-${j}`} cx={mx} cy={my} r={1} fill={glowColor} opacity={0.4} />
            )
          })
        )}
      </svg>
      {/* Category nodes */}
      {mounted && positions.map((pos, i) => (
        <div
          key={CATEGORIES[i].id}
          className="absolute"
          style={{
            left: `${(pos.x / 320) * 100}%`,
            top: `${(pos.y / 320) * 100}%`,
            transform: 'translate(-50%, -50%)',
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={CATEGORIES[i].icon}
            isActive={hoveredId === CATEGORIES[i].id}
            onHover={(v) => setHoveredId(v ? CATEGORIES[i].id : null)}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 5: Dock ───────────────────────────────────────────────────
function MockupDock({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  return (
    <div className="flex flex-col items-center gap-5">
      {/* Orb inline (not absolute — Dock stacks vertically) */}
      <div style={{ width: ORB_SIZE, height: ORB_SIZE }}>
        <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={false} />
      </div>
      {/* Dock bar */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-xl"
        style={{
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        {CATEGORIES.map((cat) => (
          <div key={cat.id} className="flex flex-col items-center gap-1.5">
            <HexNode
              glowColor={glowColor}
              icon={cat.icon}
              isActive={hoveredId === cat.id}
              onHover={(v) => setHoveredId(v ? cat.id : null)}
            />
            <span
              style={{
                fontSize: '7px',
                color: hoveredId === cat.id ? '#ffffff' : '#475569',
                letterSpacing: '0.08em',
                textTransform: 'uppercase' as const,
                fontWeight: 600,
                transition: 'color 0.2s',
              }}
            >
              {cat.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Mockup 6: Radial Arc (top half-circle) ───────────────────────────
// ── Mockup 6: Radial Arc + Arc Chords (enhanced) ────────────────────
// Nodes on the top half-arc with chord lines between every pair.
// Hover highlights all chords connected to the hovered node — fits the
// arc style because chords of an arc are a natural geometric concept.
function MockupRadialArc({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  const particles = useParticles(30, 55, 130, 99)

  const positions = useMemo(() => {
    if (!mounted) return Array.from({ length: 6 }, () => ({ x: 0, y: 0, sx: 150, sy: 150 }))
    return Array.from({ length: 6 }, (_, i) => {
      const angle = Math.PI + (i / 5) * Math.PI // PI to 2PI = top half
      const x = Math.cos(angle) * 110
      const y = Math.sin(angle) * 110
      return { x, y, sx: Math.round((150 + x) * 100) / 100, sy: Math.round((150 + y) * 100) / 100 }
    })
  }, [mounted])

  return (
    <div className="relative" style={{ width: 300, height: 300 }}>
      <Orb glowColor={glowColor} />
      {/* Arc decoration */}
      <div
        className="absolute rounded-full pointer-events-none"
        style={{
          left: '50%',
          top: '50%',
          width: 220,
          height: 220,
          transform: 'translate(-50%, -50%)',
          border: `1px solid ${glowColor}10`,
          clipPath: 'inset(0 0 50% 0)',
        }}
      />
      {/* SVG: Arc chord connections */}
      <svg width={300} height={300} className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
        <defs>
          <linearGradient id="arc-chord-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0.05)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.5)} />
          </linearGradient>
        </defs>
        {/* Chord lines between all pairs of arc nodes */}
        {mounted && positions.map((p1, i) =>
          positions.slice(i + 1).map((p2, j) => {
            const idx = `arc-chord-${i}-${i + 1 + j}`
            const isActive = hoveredId !== null && (hoveredId === CATEGORIES[i].id || hoveredId === CATEGORIES[i + 1 + j].id)
            return (
              <line
                key={idx}
                x1={p1.sx} y1={p1.sy}
                x2={p2.sx} y2={p2.sy}
                stroke={glowColor}
                strokeWidth={isActive ? 1.2 : 0.5}
                opacity={hoveredId ? (isActive ? 0.7 : 0.04) : 0.15}
                style={{ transition: 'opacity 0.3s, stroke-width 0.3s' }}
              />
            )
          })
        )}
        {/* Midpoint dots on active chords */}
        {mounted && hoveredId && positions.map((p1, i) =>
          positions.slice(i + 1).map((p2, j) => {
            const isActive = hoveredId === CATEGORIES[i].id || hoveredId === CATEGORIES[i + 1 + j].id
            if (!isActive) return null
            const mx = Math.round(((p1.sx + p2.sx) / 2) * 100) / 100
            const my = Math.round(((p1.sy + p2.sy) / 2) * 100) / 100
            return <circle key={`arc-dot-${i}-${j}`} cx={mx} cy={my} r={1.5} fill={glowColor} opacity={0.6} />
          })
        )}
      </svg>
      {/* Particles around the arc */}
      <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
        {particles.map((p, i) => (
          <div key={i} className="absolute rounded-full" style={{
            left: `calc(50% + ${p.x}px)`,
            top: `calc(50% + ${p.y}px)`,
            width: p.size, height: p.size,
            background: glowColor,
            opacity: p.opacity,
            boxShadow: `0 0 ${p.size * 2}px ${glowColor}`,
          }} />
        ))}
      </div>
      {mounted && CATEGORIES.map((cat, i) => (
        <div
          key={cat.id}
          className="absolute"
          style={{
            left: '50%',
            top: '50%',
            transform: `translate(calc(-50% + ${positions[i].x}px), calc(-50% + ${positions[i].y}px))`,
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)}
          />
        </div>
      ))}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════
// ── Radial Arc + Spokes: shared base ────────────────────────────────
// All 9 transition variants share this layout. Only the node animation
// on orb click differs between them.
// ══════════════════════════════════════════════════════════════════════

type NodePosition = { x: number; y: number; sx: number; sy: number; angle: number }
type NodeStyleFn = (idx: number, pos: NodePosition) => React.CSSProperties

function RadialArcBase({
  glowColor,
  nodeId,
  isGlitchMode,
  onOrbClick,
  nodeStyle,
  extraSVG,
}: {
  glowColor: string
  nodeId: string
  isGlitchMode: boolean
  onOrbClick: () => void
  nodeStyle: NodeStyleFn
  extraSVG?: React.ReactNode
}) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  const particles = useParticles(20, 55, 130, 88)

  useEffect(() => { setMounted(true) }, [])

  const positions = useMemo(() => {
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
    <div className="relative" style={{ width: 246, height: 246 }}>
      <Orb glowColor={glowColor} onClick={onOrbClick} showLabels={isGlitchMode} />
      {/* SVG + particles: hidden instantly during glitch */}
      {!isGlitchMode && (
        <>
          <svg width={246} height={246} className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
            <defs>
              <linearGradient id={`arc-base-grad-${nodeId}`} x1="50%" y1="50%" x2="50%" y2="0%">
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
                <line key={`${nodeId}-spoke-${i}`} x1={123} y1={123} x2={pos.sx} y2={pos.sy}
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
          <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
            {particles.map((p, i) => (
              <div key={i} className="absolute rounded-full" style={{
                left: `calc(50% + ${p.x}px)`, top: `calc(50% + ${p.y}px)`,
                width: p.size, height: p.size, background: glowColor, opacity: p.opacity,
                boxShadow: `0 0 ${p.size * 2}px ${glowColor}`,
              }} />
            ))}
          </div>
        </>
      )}
      {/* Category nodes */}
      {mounted && CATEGORIES.map((cat, i) => (
        <div key={cat.id} className="absolute" style={{
          left: '50%', top: '50%',
          ...nodeStyle(i, positions[i]),
        }}>
          <HexNode glowColor={glowColor} icon={cat.icon}
            isActive={!isGlitchMode && hoveredId === cat.id}
            onHover={(v) => !isGlitchMode && setHoveredId(v ? cat.id : null)} />
        </div>
      ))}
      {/* Category label */}
      {mounted && hoveredId && !isGlitchMode && (() => {
        const idx = CATEGORIES.findIndex(c => c.id === hoveredId)
        if (idx < 0) return null
        const pos = positions[idx]
        const off = labelOffsets[idx]
        const lx = Math.max(16, Math.min(230, pos.sx + off.dx))
        const ly = Math.max(8, Math.min(238, pos.sy + off.dy))
        return (
          <div key={`${nodeId}-label`} className="absolute pointer-events-none" style={{
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
              textAlign: off.align as any,
            }}>
              {CATEGORIES[idx].label}
            </span>
          </div>
        )
      })()}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════
// ── GROUP A — 3 transitions ─────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════

// ── A1: Magnet Pull ─────────────────────────────────────────────────
// Nodes shrink and get pulled into the orb center sequentially.
function MockupTransitionMagnet({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [pullProgress, setPullProgress] = useState(0) // 0 = normal, 1 = fully pulled in

  const handleOrbClick = () => {
    if (isGlitch) {
      // Reverse: nodes expand back from center
      setIsGlitch(false)
      setPullProgress(0)
    } else {
      setIsGlitch(true)
      // Animate 0 → 1 over 500ms
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 500)
        setPullProgress(t)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="magnet" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      nodeStyle={(i, pos) => {
        // Each node shrinks and moves toward center, staggered by 80ms worth via pullProgress
        const stagger = i / 5
        const t = Math.max(0, Math.min(1, (pullProgress - stagger * 0.4) / 0.6))
        const ease = t * t // ease-in
        return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px)) scale(${1 - ease * 0.8})`,
          opacity: 1 - ease,
          transition: isGlitch ? 'none' : 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
        }
      }}
    />
  )
}

// ── A2: Photon Burst ────────────────────────────────────────────────
// Nodes flash white then explode outward with scale-up + fade.
function MockupTransitionBurst({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [burstPhase, setBurstPhase] = useState(0) // 0=normal, 0-0.3=flash, 0.3-1=burst

  const handleOrbClick = () => {
    if (isGlitch) {
      setIsGlitch(false)
      setBurstPhase(0)
    } else {
      setIsGlitch(true)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 600)
        setBurstPhase(t)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="burst" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      nodeStyle={(i, pos) => {
        const angle = Math.PI + (i / 5) * Math.PI
        if (burstPhase <= 0.2) {
          // Phase 1: flash — scale up slightly, go bright
          const flash = burstPhase / 0.2
          return {
            transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px)) scale(${1 + flash * 0.3})`,
            opacity: 1,
            filter: `brightness(${1 + flash * 2})`,
            transition: 'none',
          }
        }
        // Phase 2: burst outward
        const burst = (burstPhase - 0.2) / 0.8
        const ease = 1 - (1 - burst) * (1 - burst) // ease-out
        const dist = ease * 65
        const dx = Math.cos(angle) * dist
        const dy = Math.sin(angle) * dist
        return {
          transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) scale(${1.3 - ease * 0.3})`,
          opacity: 1 - ease,
          filter: `brightness(${3 - ease * 2})`,
          transition: 'none',
        }
      }}
    />
  )
}

// ── A3: Orbit Sweep ─────────────────────────────────────────────────
// Nodes break formation and orbit around the orb before fading.
function MockupTransitionOrbit({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [orbitAngle, setOrbitAngle] = useState(0)

  const handleOrbClick = () => {
    if (isGlitch) {
      setIsGlitch(false)
      setOrbitAngle(0)
    } else {
      setIsGlitch(true)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 700)
        setOrbitAngle(t * Math.PI * 1.5) // 270° sweep
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="orbit" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      nodeStyle={(i, pos) => {
        if (!isGlitch) return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))`,
          opacity: 1,
          filter: 'brightness(1)',
          visibility: 'visible',
          transition: 'transform 0.6s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease, filter 0.3s ease',
        }
        const t = orbitAngle / (Math.PI * 1.5) // 0 to 1
        const baseAngle = Math.PI + (i / 5) * Math.PI
        const sweepAngle = baseAngle + orbitAngle
        const r = 90 + orbitAngle * 12 // radius grows as they orbit
        const x = Math.cos(sweepAngle) * r
        const y = Math.sin(sweepAngle) * r
        // Photon Burst flash effect in first 15%
        const flashT = Math.min(1, t / 0.15)
        const brightness = 1 + flashT * 2
        const scale = 1 + flashT * 0.25
        const done = t >= 1
        return {
          transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) rotate(${orbitAngle * 180 / Math.PI}deg) scale(${scale})`,
          opacity: done ? 0 : 1 - t,
          filter: `brightness(${brightness})`,
          visibility: done ? 'hidden' : 'visible',
          transition: 'none',
        }
      }}
    />
  )
}

// ══════════════════════════════════════════════════════════════════════
// ── GROUP B — 3 transitions ─────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════

// ── B1: Pulse Wave ──────────────────────────────────────────────────
// Expanding ring from orb center — nodes vanish as the ring passes.
function MockupTransitionPulse({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [waveRadius, setWaveRadius] = useState(0)

  const handleOrbClick = () => {
    if (isGlitch) {
      setIsGlitch(false)
      setWaveRadius(0)
    } else {
      setIsGlitch(true)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 600)
        setWaveRadius(t * 115) // expand to 115px (fits in 246px container)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="pulse" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      extraSVG={isGlitch ? (
        <circle cx={123} cy={123} r={waveRadius} fill="none"
          stroke={glowColor} strokeWidth={2} opacity={0.6}
          style={{ transition: 'none' }} />
      ) : undefined}
      nodeStyle={(i, pos) => {
        if (!isGlitch) return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))`,
          transition: 'opacity 0.3s ease',
        }
        // Each node sits at a known distance from center (~110px)
        // It vanishes when the wave passes it
        const dist = 90
        const vanished = waveRadius > dist
        return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px)) scale(${vanished ? 0.5 : 1})`,
          opacity: vanished ? 0 : 1,
          transition: 'none',
        }
      }}
    />
  )
}

// ── B2: Gravity Drop ────────────────────────────────────────────────
// Nodes lose grip and fall downward with acceleration.
function MockupTransitionGravity({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [dropT, setDropT] = useState(0)

  const handleOrbClick = () => {
    if (isGlitch) {
      setIsGlitch(false)
      setDropT(0)
    } else {
      setIsGlitch(true)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 700)
        setDropT(t)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="gravity" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      nodeStyle={(i, pos) => {
        if (!isGlitch) return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))`,
          transition: 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
        }
        // Stagger: outer nodes (0,5) drop first, inner (2,3) last
        const distFromCenter = Math.abs(i - 2.5) / 2.5 // 0 for center nodes, 1 for outer
        const stagger = distFromCenter * 0.3
        const t = Math.max(0, Math.min(1, (dropT - stagger) / 0.7))
        const gravity = t * t * 150 // accelerate downward
        const fade = t > 0.7 ? (t - 0.7) / 0.3 : 0
        return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y + gravity}px)) rotate(${t * 30 * (i < 3 ? -1 : 1)}deg)`,
          opacity: 1 - fade,
          transition: 'none',
        }
      }}
    />
  )
}

// ── B3: Shatter ─────────────────────────────────────────────────────
// Nodes crack and fragment into scatter pieces.
function MockupTransitionShatter({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [shatterT, setShatterT] = useState(0)
  // Pre-computed random scatter directions for each node
  const scatterDirs = useMemo(() =>
    Array.from({ length: 6 }, (_, i) => ({
      dx: Math.cos(Math.PI + (i / 5) * Math.PI + (Math.random() - 0.5)) * (65 + Math.random() * 50),
      dy: Math.sin(Math.PI + (i / 5) * Math.PI + (Math.random() - 0.5)) * (65 + Math.random() * 50),
      rot: (Math.random() - 0.5) * 360,
    })), [])

  const handleOrbClick = () => {
    if (isGlitch) {
      setIsGlitch(false)
      setShatterT(0)
    } else {
      setIsGlitch(true)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 500)
        setShatterT(t)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="shatter" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      nodeStyle={(i, pos) => {
        if (!isGlitch) return {
          transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))`,
          transition: 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
        }
        const s = scatterDirs[i]
        const t = shatterT
        const ease = t * t
        return {
          transform: `translate(calc(-50% + ${pos.x + s.dx * ease}px), calc(-50% + ${pos.y + s.dy * ease + t * t * 32}px)) rotate(${s.rot * ease}deg) scale(${1 - t * 0.6})`,
          opacity: 1 - t,
          transition: 'none',
        }
      }}
    />
  )
}

// ══════════════════════════════════════════════════════════════════════
// ── GROUP C — Spiral Dissolve (WINNER) + random Gravity/Magnet ──────
// ══════════════════════════════════════════════════════════════════════

type WinTransition = 'spiral' | 'gravity' | 'magnet'

function MockupTransitionSpiral({ glowColor }: { glowColor: string }) {
  const [isGlitch, setIsGlitch] = useState(false)
  const [spiralT, setSpiralT] = useState(0)
  const [enterT, setEnterT] = useState(1) // 1 = fully entered (no animation)
  const [transitionType, setTransitionType] = useState<WinTransition>('spiral')

  // Pick a random transition, different from the current one
  const pickRandomTransition = (current: WinTransition): WinTransition => {
    const options: WinTransition[] = ['spiral', 'gravity', 'magnet']
    const filtered = options.filter(t => t !== current)
    return filtered[Math.floor(Math.random() * filtered.length)]
  }

  const handleOrbClick = () => {
    if (isGlitch) {
      // Enter: nodes fly back in with Photon Burst flash
      setIsGlitch(false)
      setSpiralT(0)
      setEnterT(0)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 600)
        setEnterT(t)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    } else {
      // Exit: randomly pick a transition type
      setTransitionType(pickRandomTransition(transitionType))
      setIsGlitch(true)
      let start: number | null = null
      const animate = (ts: number) => {
        if (!start) start = ts
        const t = Math.min(1, (ts - start) / 700)
        setSpiralT(t)
        if (t < 1) requestAnimationFrame(animate)
      }
      requestAnimationFrame(animate)
    }
  }

  // Photon Burst flash helper: peak at 15%, then settle
  const photonFlash = (t: number) => {
    if (t < 0.15) {
      const flash = t / 0.15
      return { brightness: 1 + flash * 2, scale: 1 + flash * 0.25 }
    }
    const settle = (t - 0.15) / 0.85
    return { brightness: 3 - settle * 2, scale: 1.25 - settle * 0.25 }
  }

  return (
    <RadialArcBase glowColor={glowColor} nodeId="spiral" isGlitchMode={isGlitch}
      onOrbClick={handleOrbClick}
      nodeStyle={(i, pos) => {
        if (!isGlitch) {
          // Enter animation: reverse current transition back to position with Photon Burst flash
          const { brightness, scale } = photonFlash(enterT)
          const reversed = 1 - enterT

          let dx = 0, dy = 0, rot = 0
          if (transitionType === 'spiral') {
            const baseAngle = Math.PI + (i / 5) * Math.PI
            const spiralAngle = baseAngle + Math.PI / 2
            dx = Math.cos(spiralAngle) * 50 * reversed
            dy = Math.sin(spiralAngle) * 50 * reversed
            rot = 90 * reversed
          } else if (transitionType === 'gravity') {
            // Reverse: nodes float up from below
            const gravity = reversed * 150
            dy = gravity
            rot = reversed * 30 * (i < 3 ? -1 : 1)
          } else if (transitionType === 'magnet') {
            // Reverse: nodes expand from center back to position
            const shrink = reversed * 0.8
            const pullX = pos.x * reversed
            const pullY = pos.y * reversed
            dx = -pullX
            dy = -pullY
            // Scale back from 0.2 to 1
            return {
              transform: `translate(calc(-50% + ${pos.x * (1 - reversed * 0.8)}px), calc(-50% + ${pos.y * (1 - reversed * 0.8)}px)) scale(${1 - shrink})`,
              opacity: enterT,
              filter: `brightness(${brightness})`,
              visibility: 'visible',
              transition: 'none',
            }
          }

          return {
            transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) rotate(${rot}deg) scale(${scale})`,
            opacity: enterT,
            filter: `brightness(${brightness})`,
            visibility: 'visible',
            transition: 'none',
          }
        }

        // Exit animation: apply current transition type with Photon Burst flash
        const flashT = Math.min(1, spiralT / 0.15)
        const brightness = 1 + flashT * 2
        const scale = 1 + flashT * 0.25
        const done = spiralT >= 1

        let dx = 0, dy = 0, rot = 0
        if (transitionType === 'spiral') {
          const baseAngle = Math.PI + (i / 5) * Math.PI
          const angle = baseAngle + spiralT * Math.PI / 2
          const extraR = spiralT * 50
          dx = Math.cos(angle) * extraR
          dy = Math.sin(angle) * extraR
          rot = spiralT * 90
        } else if (transitionType === 'gravity') {
          // Nodes fall downward with acceleration
          const distFromCenter = Math.abs(i - 2.5) / 2.5
          const stagger = distFromCenter * 0.3
          const t = Math.max(0, Math.min(1, (spiralT - stagger) / 0.7))
          const gravity = t * t * 150
          rot = t * 30 * (i < 3 ? -1 : 1)
          // For gravity, we need the base position + gravity offset
          // But spiralT is used for the animation progress, and we need to apply gravity to the original position
          // The issue is that the base position is pos.x, pos.y, and gravity adds to dy
          return {
            transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y + gravity}px)) rotate(${rot}deg) scale(${scale})`,
            opacity: done ? 0 : 1 - spiralT,
            filter: `brightness(${brightness})`,
            visibility: done ? 'hidden' : 'visible',
            transition: 'none',
          }
        } else if (transitionType === 'magnet') {
          // Nodes shrink and get pulled into center
          const stagger = i / 5
          const t = Math.max(0, Math.min(1, (spiralT - stagger * 0.4) / 0.6))
          const ease = t * t
          return {
            transform: `translate(calc(-50% + ${pos.x * (1 - ease * 0.8)}px), calc(-50% + ${pos.y * (1 - ease * 0.8)}px)) scale(${1 - ease * 0.8})`,
            opacity: 1 - ease,
            filter: `brightness(${brightness})`,
            visibility: done ? 'hidden' : 'visible',
            transition: 'none',
          }
        }

        return {
          transform: `translate(calc(-50% + ${pos.x + dx}px), calc(-50% + ${pos.y + dy}px)) rotate(${rot}deg) scale(${scale})`,
          opacity: done ? 0 : 1 - spiralT,
          filter: `brightness(${brightness})`,
          visibility: done ? 'hidden' : 'visible',
          transition: 'none',
        }
      }}
    />
  )
}

// ── Mockup 7: Concentric (inner 3 + outer 3) ────────────────────────
function MockupConcentric({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const innerPos = useRadialPositions(3, 65)
  const outerPos = useRadialPositions(3, 115, Math.PI / 6)
  const particles = useParticles(30, 50, 130, 55)

  return (
    <div className="relative" style={{ width: 300, height: 300 }}>
      <Orb glowColor={glowColor} />
      {/* Ring decorations */}
      {[65, 115].map((r) => (
        <div
          key={r}
          className="absolute rounded-full pointer-events-none"
          style={{
            left: '50%',
            top: '50%',
            width: r * 2,
            height: r * 2,
            transform: 'translate(-50%, -50%)',
            border: `1px solid ${glowColor}10`,
          }}
        />
      ))}
      {/* Particles around the rings */}
      <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
        {particles.map((p, i) => (
          <div key={i} className="absolute rounded-full" style={{
            left: `calc(50% + ${p.x}px)`,
            top: `calc(50% + ${p.y}px)`,
            width: p.size, height: p.size,
            background: glowColor,
            opacity: p.opacity,
            boxShadow: `0 0 ${p.size * 2}px ${glowColor}`,
          }} />
        ))}
      </div>
      {/* Inner ring */}
      {CATEGORIES.slice(0, 3).map((cat, i) => (
        <div
          key={cat.id}
          className="absolute"
          style={{
            left: '50%',
            top: '50%',
            transform: `translate(calc(-50% + ${innerPos[i].x}px), calc(-50% + ${innerPos[i].y}px))`,
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)}
            size={36}
          />
        </div>
      ))}
      {/* Outer ring */}
      {CATEGORIES.slice(3).map((cat, i) => (
        <div
          key={cat.id}
          className="absolute"
          style={{
            left: '50%',
            top: '50%',
            transform: `translate(calc(-50% + ${outerPos[i].x}px), calc(-50% + ${outerPos[i].y}px))`,
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)}
          />
        </div>
      ))}
    </div>
  )
}

// ── Shared SVG helpers for wheel-view style elements ──────────────────
function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.substring(0, 2), 16)
  const g = parseInt(h.substring(2, 4), 16)
  const b = parseInt(h.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Rotating dashed ring (wheel-view style) */
function RotatingRing({ cx, cy, r, color, speed = 6, dash = '18 4', strokeW = 2.7 }: {
  cx: number; cy: number; r: number; color: string; speed?: number; dash?: string; strokeW?: number
}) {
  return (
    <circle
      cx={cx} cy={cy} r={r}
      fill="none" stroke={hexToRgba(color, 0.4)}
      strokeWidth={strokeW} strokeDasharray={dash}
      style={{
        animation: `spin ${speed}s linear infinite`,
        transformOrigin: `${cx}px ${cy}px`,
      }}
    />
  )
}

/** Neon edge bloom circle */
function NeonBloom({ cx, cy, r, color }: { cx: number; cy: number; r: number; color: string }) {
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="2"
        style={{ opacity: 0.4, filter: 'blur(8px)' }} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="0.75"
        style={{ opacity: 0.8, filter: `drop-shadow(0 0 4px ${color})` }} />
    </>
  )
}

/** Core shimmer engine — pulsing white halo */
function CoreShimmer({ cx, cy, r }: { cx: number; cy: number; r: number }) {
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="white" strokeWidth="6"
        style={{ opacity: 0.15, filter: 'blur(12px)', animation: 'pulse 4s ease-in-out infinite' }} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="white" strokeWidth="2"
        style={{ opacity: 0.9, filter: 'drop-shadow(0 0 10px white) drop-shadow(0 0 15px white)' }} />
    </>
  )
}

/** Liquid metal structural frame */
function StructuralFrame({ cx, cy, r, color }: { cx: number; cy: number; r: number; color: string }) {
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={hexToRgba(color, 0.1)} strokeWidth="40"
        style={{ filter: 'blur(40px)', opacity: 0.3 }} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="0.5" />
    </>
  )
}

// ── Mockup 8: Orbital (orb + particles + rotating rings) ─────────────
// Uses 180px orb (same as other mockups) for consistent visual centering.
// Lissajous curve in PrototypeOrbBreathing has asymmetric visual mass;
// smaller orb relative to container reduces perceived offset.
function MockupOrbitalParticles({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const positions = useRadialPositions(6, 115)
  const particles = useParticles(40, 95, 135, 42)
  const c = 160 // center of 320px container
  const ORB_SIZE = 180

  return (
    <div className="relative" style={{ width: 320, height: 320 }}>
      {/* SVG: rotating rings only — no halo/bloom/shimmer */}
      <svg width={320} height={320} className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
        <RotatingRing cx={c} cy={c} r={125} color={glowColor} speed={8} dash="20 5" strokeW={2} />
        <RotatingRing cx={c} cy={c} r={105} color={glowColor} speed={5} dash="40 12" strokeW={1.5} />
      </svg>
      {/* Particles floating between orb and rings */}
      <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
        {particles.map((p, i) => (
          <div key={i} className="absolute rounded-full" style={{
            left: `calc(50% + ${p.x}px)`,
            top: `calc(50% + ${p.y}px)`,
            width: p.size, height: p.size,
            background: glowColor,
            opacity: p.opacity,
            filter: `blur(${p.size > 2 ? 1 : 0}px)`,
            boxShadow: `0 0 ${p.size * 2}px ${glowColor}`,
          }} />
        ))}
      </div>
      {/* Standard 180px orb — matches other mockups for consistent centering */}
      <div className="absolute" style={{
        left: '50%', top: '50%',
        width: ORB_SIZE, height: ORB_SIZE,
        transform: 'translate(-50%, -50%)',
        zIndex: 2,
      }}>
        <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={false} />
      </div>
      {/* Hex nodes */}
      {CATEGORIES.map((cat, i) => (
        <div key={cat.id} className="absolute" style={{
          left: '50%', top: '50%',
          transform: `translate(calc(-50% + ${positions[i].x}px), calc(-50% + ${positions[i].y}px))`,
          zIndex: 3,
        }}>
          <HexNode glowColor={glowColor} icon={cat.icon}
            isActive={hoveredId === cat.id}
            onHover={(v) => setHoveredId(v ? cat.id : null)} />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 10: Hybrid Polish — Concentric (3 rings + ring nodes) ────
// Uses 180px orb (same as other mockups) for consistent visual centering.
// ── Mockup 9: Vortex Spiral (logarithmic spiral inward to orb) ─────────
function MockupHybridPolish({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  const c = 160
  const ORB_SIZE = 180

  // Logarithmic spiral: r = a * e^(b*theta)
  // 6 nodes spiral inward from outer to inner
  const spiralNodes = CATEGORIES.map((_, i) => {
    const t = i / 5 // 0 to 1
    const angle = t * Math.PI * 2.5 // 2.5 turns
    const r = 145 - t * 70 // radius decreases from 145 to 75
    return { x: Math.cos(angle) * r, y: Math.sin(angle) * r, angle, r, t }
  })

  // Generate spiral path points for the visible curve
  const spiralPath = (() => {
    const points: string[] = []
    for (let t = 0; t <= 1; t += 0.02) {
      const angle = t * Math.PI * 2.5
      const r = 145 - t * 70
      const x = Math.round((c + Math.cos(angle) * r) * 100) / 100
      const y = Math.round((c + Math.sin(angle) * r) * 100) / 100
      points.push(`${t === 0 ? 'M' : 'L'} ${x} ${y}`)
    }
    return points.join(' ')
  })()

  return (
    <div className="relative" style={{ width: 320, height: 320 }}>
      {/* Spiral path */}
      <svg width={320} height={320} className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
        <defs>
          <linearGradient id={`spiral-grad`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0.05)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.4)} />
          </linearGradient>
        </defs>
        <path
          d={spiralPath}
          fill="none"
          stroke={`url(#spiral-grad)`}
          strokeWidth={1.2}
          strokeLinecap="round"
          opacity={0.6}
        />
      </svg>
      {/* Orb at center */}
      <div className="absolute" style={{
        left: '50%', top: '50%',
        width: ORB_SIZE, height: ORB_SIZE,
        transform: 'translate(-50%, -50%)',
        zIndex: 2,
      }}>
        <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={false} />
      </div>
      {/* Spiral nodes */}
      {mounted && spiralNodes.map((node, i) => (
        <div
          key={CATEGORIES[i].id}
          className="absolute"
          style={{
            left: `${((c + node.x) / 320) * 100}%`,
            top: `${((c + node.y) / 320) * 100}%`,
            transform: 'translate(-50%, -50%)',
            zIndex: 3,
          }}
        >
          <HexNode
            glowColor={glowColor}
            icon={CATEGORIES[i].icon}
            isActive={hoveredId === CATEGORIES[i].id}
            onHover={(v) => setHoveredId(v ? CATEGORIES[i].id : null)}
            size={node.t < 0.3 ? 40 : node.t < 0.7 ? 34 : 30}
          />
        </div>
      ))}
    </div>
  )
}

/** Ring-shaped node — concentric design. Small circle with liquid-metal border + icon. */
function RingNode({
  glowColor, icon: Icon, isActive, onHover, onClick, size = 32,
}: { glowColor: string; icon: ElementType; isActive: boolean; onHover: (hovering: boolean) => void; onClick?: () => void; size?: number }) {
  return (
    <button
      className="relative flex items-center justify-center cursor-pointer"
      style={{
        width: size, height: size,
        border: 'none', background: 'none', padding: 0,
        opacity: isActive ? 1 : 0.75,
        transform: isActive ? 'scale(1.15)' : 'scale(1)',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        flexShrink: 0,
      }}
      onClick={onClick}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      {/* Neon glow ring */}
      <div className="absolute pointer-events-none" style={{
        inset: -5, borderRadius: '50%',
        background: `radial-gradient(circle, ${hexToRgba(glowColor, 0.5)} 0%, transparent 70%)`,
        filter: 'blur(5px)',
        opacity: isActive ? 1 : 0.3,
      }} />
      {/* Liquid metal border ring */}
      <div className="absolute pointer-events-none" style={{
        inset: 0, borderRadius: '50%',
        background: `conic-gradient(from 0deg,
          #ffffff 0deg, ${glowColor} 60deg, #101014 150deg,
          #ffffff 220deg, ${glowColor} 280deg, #101014 350deg) border-box`,
        WebkitMask: 'linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0)',
        WebkitMaskComposite: 'destination-out', maskComposite: 'exclude',
        filter: `drop-shadow(0 0 2px ${glowColor})`,
        zIndex: 2,
      }} />
      {/* Glassmorphic base */}
      <div className="absolute inset-0 flex items-center justify-center overflow-hidden" style={{
        borderRadius: '50%',
        background: isActive
          ? `radial-gradient(circle, ${hexToRgba(glowColor, 0.35)} 0%, #0a0a0c 75%)`
          : `linear-gradient(135deg, #0a0a0c 0%, ${hexToRgba(glowColor, 0.12)} 100%)`,
        boxShadow: '0 2px 6px rgba(0,0,0,0.5), inset 0 1px 1px rgba(255,255,255,0.15)',
        zIndex: 3,
      }}>
        {/* Specular sweep */}
        <div className="absolute inset-0 pointer-events-none" style={{
          borderRadius: '50%',
          background: 'linear-gradient(135deg, rgba(255,255,255,0.12) 0%, transparent 50%, rgba(255,255,255,0.04) 100%)',
          zIndex: 4,
        }} />
        <div className="relative z-10 flex items-center justify-center pointer-events-none">
          <Icon style={{ width: size * 0.42, height: size * 0.42, color: isActive ? '#ffffff' : '#94a3b8',
            filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.5))' }} strokeWidth={1.5} />
        </div>
      </div>
    </button>
  )
}

/** Liquid-metal styled hex node — adds specular sheen + neon edge to the base hex */
function LiquidHexNode({
  glowColor, icon: Icon, isActive, onHover, onClick, size = 40,
}: { glowColor: string; icon: ElementType; isActive: boolean; onHover: (hovering: boolean) => void; onClick?: () => void; size?: number }) {
  return (
    <button
      className="relative flex items-center justify-center cursor-pointer"
      style={{
        width: size, height: size,
        clipPath: HEX_CLIP,
        border: 'none', background: 'none', padding: 0,
        opacity: isActive ? 1 : 0.8,
        transform: isActive ? 'scale(1.08)' : 'scale(1)',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        flexShrink: 0,
      }}
      onClick={onClick}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      {/* Neon edge bloom */}
      <div className="absolute pointer-events-none" style={{
        inset: -8, clipPath: HEX_CLIP,
        background: `radial-gradient(circle, ${glowColor}${Math.round(0.5 * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
        filter: 'blur(6px)', opacity: isActive ? 1 : 0.3,
      }} />
      {/* Liquid metal border — conic gradient with specular */}
      <div className="absolute pointer-events-none" style={{
        inset: 0, clipPath: HEX_CLIP,
        background: `conic-gradient(from 0deg,
          #ffffff 0deg, ${glowColor} 45deg, #101014 120deg,
          #ffffff 180deg, ${glowColor} 225deg, #101014 300deg, #ffffff 360deg) border-box`,
        WebkitMask: 'linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0)',
        WebkitMaskComposite: 'destination-out', maskComposite: 'exclude',
        filter: `drop-shadow(0 0 1px rgba(255,255,255,0.3)) drop-shadow(0 0 3px ${glowColor})`,
        zIndex: 2,
      }} />
      {/* Glassmorphic base with radial glow on active */}
      <div className="absolute inset-0 flex items-center justify-center overflow-hidden" style={{
        clipPath: HEX_CLIP,
        background: isActive
          ? `radial-gradient(circle, ${hexToRgba(glowColor, 0.3)} 0%, #0a0a0c 80%)`
          : `linear-gradient(135deg, #0a0a0c 0%, ${hexToRgba(glowColor, 0.1)} 100%)`,
        boxShadow: '0 2px 8px rgba(0,0,0,0.5), inset 0 1px 2px rgba(255,255,255,0.2)',
        zIndex: 3,
      }}>
        {/* Specular highlight sweep */}
        <div className="absolute inset-0 pointer-events-none" style={{
          clipPath: HEX_CLIP,
          background: 'linear-gradient(135deg, rgba(255,255,255,0.15) 0%, transparent 50%, rgba(255,255,255,0.05) 100%)',
          zIndex: 4,
        }} />
        <div className="relative z-10 flex items-center justify-center pointer-events-none">
          <Icon style={{ width: size * 0.4, height: size * 0.4, color: isActive ? '#ffffff' : '#94a3b8',
            filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.5))' }} strokeWidth={1.5} />
        </div>
      </div>
    </button>
  )
}

// ── Mockup 11: Dock Redesign (tight arch arcs inside dock) ───────
function MockupDockRedesign({ glowColor }: { glowColor: string }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const btnW = 40
  const dockH = 44 // same as original Dock
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  // Particles spread horizontally across the dock, not in a circle
  const dockParticles = useMemo(() => {
    if (!mounted) return []
    const rng = mulberry32(77)
    // Base particles spread across dock
    const base = Array.from({ length: 16 }, () => ({
      x: (rng() - 0.5) * 240,
      y: (rng() - 0.5) * (dockH - 12),
      size: 1 + rng() * 2,
      opacity: 0.1 + rng() * 0.25,
    }))
    // Extra particles near Customize (+73px) and Monitor (+115px)
    const extras = Array.from({ length: 8 }, (_, i) => {
      const cx = i < 4 ? 73 : 115 // Customize or Monitor position
      return {
        x: cx + (rng() - 0.5) * 30,
        y: (rng() - 0.5) * (dockH - 12),
        size: 1.5 + rng() * 2,
        opacity: 0.2 + rng() * 0.3,
      }
    })
    return [...base, ...extras]
  }, [mounted])
  // Arch (∩): peak below top, feet near bottom, vertically centered in dock
  const pad = 6
  const footY = 36  // feet shifted up 4px
  const cpY = 0  // peak at y=9, clear of top
  const archPath = `M ${pad} ${footY} C ${pad} ${cpY}, ${btnW - pad} ${cpY}, ${btnW - pad} ${footY}`

  return (
    <div className="flex flex-col items-center gap-1">
      {/* Orb — same size as original Dock mockup (ORB_SIZE = 180px) */}
      <div style={{ width: ORB_SIZE, height: ORB_SIZE }}>
        <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={false} />
      </div>
      {/* Dock container */}
      <div style={{ position: 'relative' }}>
        {/* Dock bar — same visual size as original (rounded-xl, px-3 py-2) */}
        <div
          className="flex items-center gap-0.5 px-3 rounded-xl"
          style={{
            position: 'relative',
            height: dockH,
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            overflow: 'hidden',
          }}
        >
          {CATEGORIES.map((cat) => {
            const isActive = hoveredId === cat.id
            return (
              <div key={cat.id}
                className="flex flex-col items-center"
                onMouseEnter={() => setHoveredId(cat.id)}
                onMouseLeave={() => setHoveredId(null)}
                style={{ cursor: 'pointer', position: 'relative', width: btnW, height: dockH }}>
                {/* Arch (∩) — SVG clips peak at top, feet at bottom */}
                <div style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: btnW,
                  height: dockH,
                  pointerEvents: 'none',
                }}>
                  <svg width={btnW} height={dockH} viewBox={`0 0 ${btnW} ${dockH}`}
                    style={{ overflow: 'hidden' }}>
                    <defs>
                      <linearGradient id={`dock-arc-${cat.id}`} x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor={isActive ? '#ffffff' : 'rgba(100,110,120,0.2)'} />
                        <stop offset="50%" stopColor={isActive ? hexToRgba(glowColor, 0.6) : 'rgba(200,210,220,0.12)'} />
                        <stop offset="100%" stopColor={isActive ? '#101014' : 'rgba(80,90,100,0.2)'} />
                      </linearGradient>
                    </defs>
                    {isActive && <path d={archPath} fill="none"
                      stroke={glowColor} strokeWidth="4" style={{ filter: 'blur(4px)', opacity: 0.25 }} />}
                    <path d={archPath} fill="none"
                      stroke={`url(#dock-arc-${cat.id})`} strokeWidth="2"
                      strokeLinecap="round" style={{ cursor: 'pointer' }} />
                    <path d={archPath} fill="none"
                      stroke={isActive ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.08)'}
                      strokeWidth="0.5" />
                  </svg>
                </div>
                {/* Icon nestled under the arch */}
                <div style={{
                  position: 'relative',
                  width: btnW,
                  height: dockH,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <cat.icon style={{
                    width: 14, height: 14,
                    color: isActive ? '#ffffff' : '#64748b',
                    filter: isActive ? `drop-shadow(0 0 3px ${glowColor})` : 'none',
                    transition: 'color 0.2s, filter 0.2s',
                    pointerEvents: 'none',
                  }} strokeWidth={1.5} />
                </div>
              </div>
            )
          })}
          {/* Particles floating inside dock */}
          <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-xl">
            {dockParticles.map((p, i) => (
              <div key={i} className="absolute rounded-full" style={{
                left: `calc(50% + ${p.x}px)`,
                top: `calc(50% + ${p.y}px)`,
                width: p.size, height: p.size,
                background: glowColor,
                opacity: p.opacity,
                boxShadow: `0 0 ${p.size * 2}px ${glowColor}`,
              }} />
            ))}
          </div>
          {/* Glowing shimmer at top of dock — pulses gently */}
          <style>{`@keyframes dock-shimmer-pulse { 0%,100% { opacity: 0.5; } 50% { opacity: 1; } }`}</style>
          <div className="absolute pointer-events-none" style={{
            top: 0, left: 0, right: 0,
            height: 3,
            background: `linear-gradient(90deg, transparent 0%, ${hexToRgba(glowColor, 0.3)} 15%, ${hexToRgba(glowColor, 0.8)} 50%, ${hexToRgba(glowColor, 0.3)} 85%, transparent 100%)`,
            borderRadius: '12px 12px 0 0',
            animation: 'dock-shimmer-pulse 3s ease-in-out infinite',
          }} />
        </div>
        {/* Labels below dock bar */}
        <div className="flex items-center gap-0.5 px-3" style={{ marginTop: 2 }}>
          {CATEGORIES.map((cat) => {
            const isActive = hoveredId === cat.id
            return (
              <div key={cat.id} style={{ width: btnW, textAlign: 'center' }}>
                <span style={{
                  fontSize: '7px', color: isActive ? '#ffffff' : '#475569',
                  letterSpacing: '0.08em', textTransform: 'uppercase' as const,
                  fontWeight: 600, transition: 'color 0.2s',
                }}>
                  {cat.label}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────
interface MenuMockupsProps {
  glowColor: string
}

const MOCKUPS = [
  { key: 'radial-hex', title: 'Radial Hex', badge: 'PRIMARY', description: 'Classic hex circle around the orb. The main layout — balanced, familiar, proven.', Component: MockupRadialHex },
  { key: 'radial-compact', title: 'Radial Compact', badge: null, description: 'Tighter ring, smaller nodes. Same radial feel but more compact — less visual weight.', Component: MockupRadialCompact },
  { key: 'orbital', title: 'Iris Bloom', badge: 'NEW', description: 'Curved petal paths radiate from the orb to each node. Organic, flower-like, flows from the core.', Component: MockupOrbital },
  { key: 'orbital-stacked', title: 'Constellation', badge: 'NEW', description: 'All nodes connected by thin lines forming a geometric star web. Hover reveals connection highlights.', Component: MockupOrbitalStacked },
  { key: 'dock', title: 'Dock', badge: null, description: 'Orb above, hex nodes in a compact dock bar below. Clean, minimal, macOS-inspired.', Component: MockupDock },
  { key: 'radial-arc', title: 'Radial Arc', badge: null, description: 'Nodes spread across the top half-circle with chord connections. Hover lights up all chords from that node. Leaves the bottom open for other UI.', Component: MockupRadialArc },
  { key: 'radial-arc-spokes', title: 'A1 — Magnet Pull', badge: 'A', description: 'Nodes shrink and get pulled into the orb center sequentially — like gravity consuming them.', Component: MockupTransitionMagnet },
  { key: 'radial-arc-burst', title: 'A2 — Photon Burst', badge: 'A', description: 'Nodes flash white then explode outward with scale + brightness — energetic burst exit.', Component: MockupTransitionBurst },
  { key: 'radial-arc-orbit', title: 'A3 — Orbit Sweep', badge: 'A', description: 'Nodes break formation and orbit around the orb in a sweeping arc before fading — flowing orbital motion.', Component: MockupTransitionOrbit },
  { key: 'radial-arc-pulse', title: 'B1 — Pulse Wave', badge: 'B', description: 'Expanding ring from orb center — nodes vanish as the ring passes each one.', Component: MockupTransitionPulse },
  { key: 'radial-arc-gravity', title: 'B2 — Gravity Drop', badge: 'B', description: 'Nodes lose grip and fall downward with acceleration — physics-based drop.', Component: MockupTransitionGravity },
  { key: 'radial-arc-shatter', title: 'B3 — Shatter', badge: 'B', description: 'Nodes crack and scatter into fragments — destructive, dramatic exit.', Component: MockupTransitionShatter },
  { key: 'radial-arc-web', title: 'C — Random Rotate', badge: '★ PICK', description: 'Winner. Each click randomly picks one of: Spiral Dissolve, Gravity Drop, or Magnet Pull. Enter: nodes reverse the transition with Photon Burst flash (brightness 1→3→1, scale 1→1.25→1).', Component: MockupTransitionSpiral },
  { key: 'concentric', title: 'Concentric', badge: null, description: 'Two rings of 3 — inner fast-access, outer secondary. Visual hierarchy.', Component: MockupConcentric },
  { key: 'orbital-halo', title: 'Orbital + Particles', badge: 'NEW', description: 'Bigger orb with radiating particles that blend into rotating dashed rings. Industrial feel without SVG overlays.', Component: MockupOrbitalParticles },
  { key: 'hybrid-polish', title: 'Vortex Spiral', badge: 'NEW', description: 'Logarithmic spiral that tightens as it approaches the orb. Nodes draw inward — gravity into the core.', Component: MockupHybridPolish },
  { key: 'dock-redesign', title: 'Dock Redesign', badge: 'NEW', description: 'Dock layout with mini arc-segment buttons — liquid metal fills, glow on active. Clean, compact.', Component: MockupDockRedesign },
]

export function MenuMockups({ glowColor }: MenuMockupsProps) {
  return (
    <div className="flex flex-col items-center gap-10 w-full">
      {/* CSS keyframes for ring animations */}
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 0.1; } 50% { opacity: 0.35; } }
      `}</style>
      {MOCKUPS.map((m) => (
        <div
          key={m.key}
          className="flex flex-col items-center gap-6 p-8 rounded-2xl w-full"
          style={{
            background: m.badge
              ? 'linear-gradient(180deg, rgba(251, 191, 36, 0.04) 0%, rgba(255, 255, 255, 0.02) 100%)'
              : 'rgba(255, 255, 255, 0.02)',
            border: m.badge
              ? '1px solid rgba(251, 191, 36, 0.25)'
              : '1px solid rgba(255, 255, 255, 0.06)',
            boxShadow: m.badge ? '0 0 32px rgba(251, 191, 36, 0.06)' : 'none',
          }}
        >
          {/* Title + badge */}
          <div className="flex items-center gap-3">
            <h4 className="text-xs font-bold uppercase tracking-widest" style={{ color: glowColor }}>
              {m.title}
            </h4>
            {m.badge && (
              <span
                className="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider"
                style={{
                  background: 'linear-gradient(135deg, #fde68a 0%, #fbbf24 50%, #f59e0b 100%)',
                  color: '#0a0a0e',
                  boxShadow: '0 0 10px rgba(251, 191, 36, 0.4)',
                }}
              >
                {m.badge}
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 text-center max-w-md">
            {m.description}
          </p>

          {/* Mockup content */}
          <m.Component glowColor={glowColor} />
        </div>
      ))}
    </div>
  )
}
