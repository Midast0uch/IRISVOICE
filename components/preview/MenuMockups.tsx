'use client'

import React, { useState, useEffect, useMemo } from 'react'
import type { ElementType } from 'react'
import { Mic, Settings, Zap, Shield, Palette, BarChart3 } from 'lucide-react'
import { PrototypeOrbBreathing } from './PrototypeOrbBreathing'

// ── Shared category data ─────────────────────────────────────────────
const CATEGORIES = [
  { id: 'voice', label: 'Voice', icon: Mic },
  { id: 'agent', label: 'Agent', icon: Settings },
  { id: 'automate', label: 'Automate', icon: Zap },
  { id: 'system', label: 'System', icon: Shield },
  { id: 'customize', label: 'Customize', icon: Palette },
  { id: 'monitor', label: 'Monitor', icon: BarChart3 },
] as const

// ── Hex node (40px) — glassmorphic hex ───────────────────────────────
const HEX_CLIP = 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)'

function HexNode({
  glowColor,
  icon: Icon,
  isActive,
  onClick,
  size = 40,
}: {
  glowColor: string
  icon: ElementType
  isActive: boolean
  onClick: () => void
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
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = isActive ? 'scale(1.08) rotate(3deg) translateY(-2px)' : 'scale(1.05) rotate(3deg) translateY(-2px)'
        e.currentTarget.style.opacity = '1'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = isActive ? 'scale(1.08)' : 'scale(1)'
        e.currentTarget.style.opacity = isActive ? '1' : '0.8'
      }}
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

// ── Orb component (no labels, no glitch text) ────────────────────────
// Positioned absolutely at the center of the parent container.
// Both the Orb and the hex nodes use the same coordinate origin
// (left:50%, top:50% of the parent) so they are always aligned.
const ORB_SIZE = 180
function Orb({ glowColor }: { glowColor: string }) {
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
      }}
    >
      <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={false} />
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

// ── Mockup 1: Radial Hex (PRIMARY) ───────────────────────────────────
function MockupRadialHex({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 2: Radial Compact (tighter ring) ──────────────────────────
function MockupRadialCompact({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
            size={36}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 3: Orbital (varying distances + rings) ────────────────────
function MockupOrbital({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const angles = [0, 60, 120, 180, 240, 300]
  const radii = [88, 106, 120, 88, 106, 120]
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  return (
    <div className="relative" style={{ width: 300, height: 300 }}>
      <Orb glowColor={glowColor} />
      {/* Decorative rings */}
      {[88, 106, 120].map((r) => (
        <div
          key={r}
          className="absolute rounded-full pointer-events-none"
          style={{
            left: '50%',
            top: '50%',
            width: r * 2,
            height: r * 2,
            transform: 'translate(-50%, -50%)',
            border: `1px solid ${glowColor}12`,
          }}
        />
      ))}
      {/* Nodes */}
      {mounted && CATEGORIES.map((cat, i) => {
        const angle = (angles[i] * Math.PI) / 180
        const r = radii[i]
        return (
          <div
            key={cat.id}
            className="absolute"
            style={{
              left: '50%',
              top: '50%',
              transform: `translate(calc(-50% + ${Math.cos(angle) * r}px), calc(-50% + ${Math.sin(angle) * r}px))`,
            }}
          >
            <HexNode
              glowColor={glowColor}
              icon={cat.icon}
              isActive={activeId === cat.id}
              onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
            />
          </div>
        )
      })}
    </div>
  )
}

// ── Mockup 4: Orbital Stacked (two orbit layers) ─────────────────────
function MockupOrbitalStacked({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const innerPos = useRadialPositions(3, 72)
  const outerPos = useRadialPositions(3, 120, -Math.PI / 2 + Math.PI / 3)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  return (
    <div className="relative" style={{ width: 300, height: 300 }}>
      <Orb glowColor={glowColor} />
      {/* Ring decorations */}
      {[72, 120].map((r) => (
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
      {/* Inner ring: Voice, Automate, Customize */}
      {mounted && CATEGORIES.slice(0, 3).map((cat, i) => (
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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
            size={36}
          />
        </div>
      ))}
      {/* Outer ring: Agent, System, Monitor */}
      {mounted && CATEGORIES.slice(3).map((cat, i) => (
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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 5: Dock ───────────────────────────────────────────────────
function MockupDock({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)

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
              isActive={activeId === cat.id}
              onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
            />
            <span
              style={{
                fontSize: '7px',
                color: activeId === cat.id ? '#ffffff' : '#475569',
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
function MockupRadialArc({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  const positions = useMemo(() => {
    if (!mounted) return Array.from({ length: 6 }, () => ({ x: 0, y: 0 }))
    // Spread across top 180° arc
    return Array.from({ length: 6 }, (_, i) => {
      const angle = Math.PI + (i / 5) * Math.PI // PI to 2PI = top half
      return { x: Math.cos(angle) * 110, y: Math.sin(angle) * 110 }
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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
          />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 7: Concentric (inner 3 + outer 3) ────────────────────────
function MockupConcentric({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const innerPos = useRadialPositions(3, 65)
  const outerPos = useRadialPositions(3, 115, Math.PI / 6)

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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
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
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)}
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

// ── Mockup 8: Orbital + Halo ─────────────────────────────────────────
function MockupOrbitalHalo({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const positions = useRadialPositions(6, 110)
  const c = 160 // SVG center (320/2)

  return (
    <div className="relative" style={{ width: 320, height: 320 }}>
      {/* SVG decorative layer — rings, bloom, shimmer */}
      <svg width={320} height={320} className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
        <StructuralFrame cx={c} cy={c} r={120} color={glowColor} />
        <RotatingRing cx={c} cy={c} r={128} color={glowColor} speed={6} />
        <RotatingRing cx={c} cy={c} r={100} color={glowColor} speed={4} dash="45 15" strokeW={2} />
        <NeonBloom cx={c} cy={c} r={130} color={glowColor} />
        <CoreShimmer cx={c} cy={c} r={20} />
      </svg>
      {/* Orb */}
      <Orb glowColor={glowColor} />
      {/* Hex nodes */}
      {CATEGORIES.map((cat, i) => (
        <div key={cat.id} className="absolute" style={{
          left: '50%', top: '50%',
          transform: `translate(calc(-50% + ${positions[i].x}px), calc(-50% + ${positions[i].y}px))`,
        }}>
          <HexNode glowColor={glowColor} icon={cat.icon}
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)} />
        </div>
      ))}
    </div>
  )
}

// ── Mockup 9: Arc-Segment Nodes ──────────────────────────────────────
function MockupArcSegments({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const svgSize = 340
  const c = svgSize / 2
  const outerR = 130
  const innerR = 110
  const segmentAngle = 360 / 6
  const gap = 3 // degrees gap between segments

  const polarToXY = (cx: number, cy: number, r: number, angleDeg: number) => {
    const rad = ((angleDeg - 90) * Math.PI) / 180
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
  }

  const arcPath = (r: number, startDeg: number, endDeg: number) => {
    const s = polarToXY(c, c, r, endDeg)
    const e = polarToXY(c, c, r, startDeg)
    const large = endDeg - startDeg > 180 ? 1 : 0
    return `M ${s.x} ${s.y} A ${r} ${r} 0 ${large} 0 ${e.x} ${e.y}`
  }

  return (
    <div className="relative" style={{ width: svgSize, height: svgSize }}>
      <svg width={svgSize} height={svgSize} className="absolute inset-0">
        <defs>
          <linearGradient id="arc-lm" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(100,110,120,0.25)" />
            <stop offset="40%" stopColor="rgba(200,210,220,0.15)" />
            <stop offset="60%" stopColor="rgba(100,110,120,0.2)" />
            <stop offset="100%" stopColor="rgba(80,90,100,0.25)" />
          </linearGradient>
          <linearGradient id="arc-lm-active" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="25%" stopColor={hexToRgba(glowColor, 0.7)} />
            <stop offset="50%" stopColor="#101014" />
            <stop offset="75%" stopColor="#ffffff" />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.7)} />
          </linearGradient>
        </defs>

        {/* Structural rings */}
        <StructuralFrame cx={c} cy={c} r={outerR + 20} color={glowColor} />
        <NeonBloom cx={c} cy={c} r={outerR + 22} color={glowColor} />
        <RotatingRing cx={c} cy={c} r={outerR + 15} color={glowColor} speed={8} dash="20 4" />

        {/* Arc segments */}
        {CATEGORIES.map((cat, i) => {
          const start = i * segmentAngle + gap / 2
          const end = (i + 1) * segmentAngle - gap / 2
          const isSelected = activeId === cat.id
          const midAngle = (start + end) / 2
          const textR = (outerR + innerR) / 2
          const textPos = polarToXY(c, c, textR, midAngle)

          return (
            <g key={cat.id}>
              {/* Glow background */}
              <path d={arcPath(outerR, start, end)} fill="none"
                stroke={isSelected ? hexToRgba(glowColor, 0.12) : 'rgba(255,255,255,0.02)'}
                strokeWidth={outerR - innerR}
                style={{ filter: isSelected ? 'blur(8px)' : 'none' }} />
              {/* Liquid metal body */}
              <path d={arcPath(outerR, start, end)} fill="none"
                stroke={isSelected ? 'url(#arc-lm-active)' : 'url(#arc-lm)'}
                strokeWidth={outerR - innerR}
                style={{ cursor: 'pointer', opacity: 0.95 }}
                onClick={() => setActiveId(isSelected ? null : cat.id)} />
              {/* Edge highlight */}
              <path d={arcPath(outerR + 1, start, end)} fill="none"
                stroke={isSelected ? glowColor : 'rgba(255,255,255,0.1)'}
                strokeWidth="0.5" style={{ opacity: 0.6 }} />
              {/* Category label */}
              <text x={textPos.x} y={textPos.y}
                fill={isSelected ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.4)'}
                fontSize="9" fontWeight="600" textAnchor="middle" dominantBaseline="central"
                style={{ textTransform: 'uppercase', letterSpacing: '0.05em', pointerEvents: 'none' }}>
                {cat.label}
              </text>
            </g>
          )
        })}

        <CoreShimmer cx={c} cy={c} r={18} />
      </svg>
      {/* Orb at center */}
      <Orb glowColor={glowColor} />
    </div>
  )
}

// ── Mockup 10: Hybrid Polish ─────────────────────────────────────────
function MockupHybridPolish({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const positions = useRadialPositions(6, 108)
  const c = 160

  return (
    <div className="relative" style={{ width: 320, height: 320 }}>
      {/* SVG decorative rings between orb and nodes */}
      <svg width={320} height={320} className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
        <RotatingRing cx={c} cy={c} r={75} color={glowColor} speed={5} dash="12 6" strokeW={1.5} />
        <RotatingRing cx={c} cy={c} r={95} color={glowColor} speed={7} dash="30 10" strokeW={2} />
        <NeonBloom cx={c} cy={c} r={115} color={glowColor} />
      </svg>
      {/* Orb */}
      <Orb glowColor={glowColor} />
      {/* Hex nodes with liquid-metal visual treatment */}
      {CATEGORIES.map((cat, i) => (
        <div key={cat.id} className="absolute" style={{
          left: '50%', top: '50%',
          transform: `translate(calc(-50% + ${positions[i].x}px), calc(-50% + ${positions[i].y}px))`,
        }}>
          <LiquidHexNode glowColor={glowColor} icon={cat.icon}
            isActive={activeId === cat.id}
            onClick={() => setActiveId(activeId === cat.id ? null : cat.id)} />
        </div>
      ))}
    </div>
  )
}

/** Liquid-metal styled hex node — adds specular sheen + neon edge to the base hex */
function LiquidHexNode({
  glowColor, icon: Icon, isActive, onClick, size = 40,
}: { glowColor: string; icon: ElementType; isActive: boolean; onClick: () => void; size?: number }) {
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

// ── Mockup 11: Dock Redesign (arc-segment buttons) ───────────────────
function MockupDockRedesign({ glowColor }: { glowColor: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const btnW = 42
  const btnH = 36
  const arcPath = (w: number, h: number) => {
    const r = h * 1.8
    return `M 0 ${h} Q ${w / 2} ${-h * 0.3} ${w} ${h}`
  }

  return (
    <div className="flex flex-col items-center gap-5">
      {/* Orb */}
      <div style={{ width: ORB_SIZE, height: ORB_SIZE }}>
        <PrototypeOrbBreathing glowColor={glowColor} breathMode="D" breathLevel={0} isBreathing={false} showLabels={false} />
      </div>
      {/* Dock bar with arc-segment buttons */}
      <div className="flex items-end gap-1.5 px-4 py-3 rounded-xl" style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.06)',
      }}>
        {CATEGORIES.map((cat) => {
          const isActive = activeId === cat.id
          return (
            <button key={cat.id} onClick={() => setActiveId(isActive ? null : cat.id)}
              className="relative flex flex-col items-center gap-1 cursor-pointer"
              style={{ background: 'none', border: 'none', padding: '2px 4px' }}>
              {/* Arc segment button shape */}
              <svg width={btnW} height={btnH} viewBox={`0 0 ${btnW} ${btnH}`}>
                <defs>
                  <linearGradient id={`dock-arc-${cat.id}`} x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stopColor={isActive ? '#ffffff' : 'rgba(100,110,120,0.25)'} />
                    <stop offset="40%" stopColor={isActive ? hexToRgba(glowColor, 0.7) : 'rgba(200,210,220,0.15)'} />
                    <stop offset="100%" stopColor={isActive ? '#101014' : 'rgba(80,90,100,0.25)'} />
                  </linearGradient>
                </defs>
                {/* Glow */}
                {isActive && <path d={arcPath(btnW, btnH)} fill="none"
                  stroke={glowColor} strokeWidth="8" style={{ filter: 'blur(6px)', opacity: 0.3 }} />}
                {/* Arc body */}
                <path d={arcPath(btnW, btnH)} fill="none"
                  stroke={`url(#dock-arc-${cat.id})`} strokeWidth="6"
                  strokeLinecap="round" style={{ cursor: 'pointer' }} />
                {/* Edge highlight */}
                <path d={arcPath(btnW, btnH)} fill="none"
                  stroke={isActive ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.1)'}
                  strokeWidth="0.5" />
              </svg>
              {/* Icon centered on arc */}
              <div className="absolute" style={{ top: 4, left: '50%', transform: 'translateX(-50%)' }}>
                <cat.icon style={{ width: 14, height: 14, color: isActive ? '#ffffff' : '#64748b' }}
                  strokeWidth={1.5} />
              </div>
              {/* Label */}
              <span style={{
                fontSize: '7px', fontWeight: 600, textTransform: 'uppercase' as const,
                letterSpacing: '0.08em', color: isActive ? '#ffffff' : '#475569',
                transition: 'color 0.2s',
              }}>
                {cat.label}
              </span>
            </button>
          )
        })}
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
  { key: 'orbital', title: 'Orbital', badge: null, description: 'Nodes at varying distances with decorative rings. Depth and layered feel.', Component: MockupOrbital },
  { key: 'orbital-stacked', title: 'Orbital Stacked', badge: null, description: 'Two orbit layers — inner 3 + outer 3. Inner items feel closer, outer items recede.', Component: MockupOrbitalStacked },
  { key: 'dock', title: 'Dock', badge: null, description: 'Orb above, hex nodes in a compact dock bar below. Clean, minimal, macOS-inspired.', Component: MockupDock },
  { key: 'radial-arc', title: 'Radial Arc', badge: null, description: 'Nodes spread across the top half-circle. Leaves the bottom open for other UI.', Component: MockupRadialArc },
  { key: 'concentric', title: 'Concentric', badge: null, description: 'Two rings of 3 — inner fast-access, outer secondary. Visual hierarchy.', Component: MockupConcentric },
  { key: 'orbital-halo', title: 'Orbital + Halo', badge: 'NEW', description: 'Orbital layout with rotating dashed rings, neon edge bloom, and core shimmer engine — wheel-view language.', Component: MockupOrbitalHalo },
  { key: 'arc-segments', title: 'Arc-Segment Nodes', badge: 'NEW', description: 'SVG arc segments replacing hex nodes — liquid metal fills, selected glow, text along arcs. Direct DualRingMechanism language.', Component: MockupArcSegments },
  { key: 'hybrid-polish', title: 'Hybrid Polish', badge: 'NEW', description: 'Radial hex with liquid-metal hex nodes, specular highlights, neon edge bloom, and rotating decorative rings.', Component: MockupHybridPolish },
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
