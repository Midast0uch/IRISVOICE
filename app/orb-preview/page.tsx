'use client'

import React, { useState } from 'react'
import { PrototypeOrb } from '@/components/preview/PrototypeOrb'
import { PrototypeOrbDepthAlpha } from '@/components/preview/PrototypeOrbDepthAlpha'
import { PrototypeOrbShellsRotating } from '@/components/preview/PrototypeOrbShellsRotating'
import { PrototypeOrbShells } from '@/components/preview/PrototypeOrbShells'
import { PrototypeOrbShellsDepth } from '@/components/preview/PrototypeOrbShellsDepth'
import { VoiceBreathGlow } from '@/components/preview/VoiceBreathGlow'
import { HexGridPreview } from '@/components/preview/HexGridPreview'

const THEMES = [
  { name: 'Cyan', color: '#00d4ff' },
  { name: 'Amber', color: '#f59e0b' },
  { name: 'Purple', color: '#a855f7' },
  { name: 'White', color: '#f0f8ff' },
]

// The root layout pins <html>/<body> to position:fixed + overflow:hidden so the
// main Tauri shell can't scroll. We can't undo that from a sub-route without
// touching globals.css, so instead this page scopes its own scroll container.
// <main> becomes a fixed-position scrollable region — body stays untouched, the
// main app keeps its constraint, and this preview gets a real scroll.
const MAIN_STYLE: React.CSSProperties = {
  position: 'absolute',
  top: 0,
  left: 0,
  width: '100vw',
  height: '100vh',
  overflowY: 'auto',
  overflowX: 'hidden',
  background: '#0a0a0e',
  WebkitOverflowScrolling: 'touch',
}

interface VariantCard {
  key: string
  badge: string
  title: string
  description: string
  clickHint: string
  render: (color: string) => React.ReactNode
}

const VARIANTS: VariantCard[] = [
  {
    key: 'reference',
    badge: 'Reference',
    title: 'Original PrototypeOrb',
    description: 'Starting point. 68 particles, 2D Lissajous. Click triggers a separate ripple + spin + invert — feedback lives OUTSIDE the spiral.',
    clickHint: 'Click → spin 360° + ripple canvas + invert flash (no text animation)',
    render: (color) => <PrototypeOrb glowColor={color} />,
  },
  {
    key: 'depth-alpha',
    badge: 'A',
    title: 'Density + depth-aware alpha',
    description: 'Same 2D curve, but ~3.2× more particles. A slow wave along the spiral drives per-particle alpha + size so the front of the sphere pops and the back recedes.',
    clickHint: 'Click → particle bloom + speed burst · Text: spiral outward 540°',
    render: (color) => <PrototypeOrbDepthAlpha glowColor={color} />,
  },
  {
    key: 'rotating',
    badge: 'B',
    title: 'Shells with paired click behaviors',
    description: "A copy of C's shells, but each click randomly picks one of three PAIRED combos: C's opening transition + C's iris-shutter text, D's gentle burst + D's magnetic-pull text, or A's bigger bloom + A's fade-out text. Use this to feel all three complete feels in one orb.",
    clickHint: 'Click → random pair: C (transition+iris) / D (burst+pull) / A (bloom+fade)',
    render: (color) => <PrototypeOrbShellsRotating glowColor={color} />,
  },
  {
    key: 'shells',
    badge: 'C',
    title: 'Layered concentric shells',
    description: 'Three nested copies of the spiral at 105% / 70% / 42% scale, each rotating at a different speed. Now with one-shot opening transition (1.7s opening, 0.6s settling, then rest) and iris shutter text disappearance.',
    clickHint: 'Click → opening transition · Text: iris shutter (axis-specific collapse)',
    render: (color) => <PrototypeOrbShells glowColor={color} />,
  },
  {
    key: 'shells-depth',
    badge: 'D',
    title: 'Shells + depth + burst',
    description: 'Three nested shells (180/130/80 particles) with depth-aware alpha. Now with continuous burst feedback (gentle 0.9× amplitude, ~0.75s decay) and magnetic-pull text spiraling into the orb center.',
    clickHint: 'Click → softer burst · Text: magnetic pull to orb center, spiraling inward',
    render: (color) => <PrototypeOrbShellsDepth glowColor={color} />,
  },
]

export default function OrbPreviewPage() {
  const [themeIndex, setThemeIndex] = useState(0)
  const [breathActive, setBreathActive] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0.3)
  const theme = THEMES[themeIndex]

  return (
    <main style={MAIN_STYLE}>
      {/* Header */}
      <div className="flex flex-col items-center gap-4">
        <h1 className="text-2xl font-bold text-white tracking-wider">
          IRIS Orb Redesign Mockups
        </h1>

        {/* Theme toggle */}
        <div className="flex gap-2">
          {THEMES.map((t, i) => (
            <button
              key={t.name}
              onClick={() => setThemeIndex(i)}
              className="px-4 py-2 rounded-lg text-sm font-semibold transition-all"
              style={{
                background: i === themeIndex ? t.color : '#1a1a1f',
                color: i === themeIndex ? '#0a0a0e' : '#e2e8f0',
                border: `1px solid ${i === themeIndex ? t.color : '#334155'}`,
              }}
            >
              {t.name}
            </button>
          ))}
        </div>
      </div>

      {/* Section 1: Spiral Variants Comparison (2x2 grid) */}
      <section className="flex flex-col items-center gap-8">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest mt-8">
          Spiral Variants — Click each to compare response
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-6xl w-full px-6">
          {VARIANTS.map((v) => {
            const isWinner = v.key === 'rotating'
            return (
            <div
              key={v.key}
              className="flex flex-col items-center gap-4 p-6 rounded-2xl"
              style={{
                background: isWinner
                  ? 'linear-gradient(180deg, rgba(251, 191, 36, 0.06) 0%, rgba(255, 255, 255, 0.02) 100%)'
                  : 'rgba(255, 255, 255, 0.02)',
                border: isWinner
                  ? '1px solid rgba(251, 191, 36, 0.35)'
                  : '1px solid rgba(255, 255, 255, 0.06)',
                boxShadow: isWinner
                  ? '0 0 32px rgba(251, 191, 36, 0.08)'
                  : 'none',
              }}
            >
              {/* Badge + Title */}
              <div className="flex items-center gap-2">
                <span
                  className="px-2 py-0.5 rounded text-xs font-bold tracking-wider"
                  style={{
                    background: isWinner
                      ? 'linear-gradient(135deg, #fde68a 0%, #fbbf24 50%, #f59e0b 100%)'
                      : v.key === 'reference' ? '#1a1a1f' : theme.color,
                    color: isWinner ? '#0a0a0e' : v.key === 'reference' ? '#e2e8f0' : '#0a0a0e',
                    boxShadow: isWinner ? '0 0 14px rgba(251, 191, 36, 0.5)' : 'none',
                  }}
                >
                  {isWinner ? '★ WINNER' : v.badge.toUpperCase()}
                </span>
                <h3 className="text-sm font-semibold text-white tracking-wide">
                  {v.title}
                </h3>
              </div>

              {/* Orb */}
              <div
                className="relative flex items-center justify-center"
                style={{ width: 280, height: 280 }}
              >
                {v.render(theme.color)}
              </div>

              {/* Description */}
              <p className="text-xs text-slate-400 text-center leading-relaxed max-w-xs">
                {v.description}
              </p>

              {/* Click hint */}
              <p
                className="text-[10px] uppercase tracking-widest font-semibold"
                style={{ color: v.key === 'reference' ? '#94a3b8' : theme.color }}
              >
                {v.clickHint}
              </p>
            </div>
            )
          })}
        </div>
      </section>

      {/* Section 2: Prototype Orb + Voice Breath Glow (unchanged) */}
      <section className="flex flex-col items-center gap-4 mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
          Voice Breath Glow — overlay applied to the Reference orb
        </h2>
        <div
          className="relative"
          style={{ width: 400, height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <VoiceBreathGlow glowColor={theme.color} isActive={breathActive} audioLevel={audioLevel} />
          <PrototypeOrb glowColor={theme.color} />
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setBreathActive(!breathActive)}
            className="px-4 py-2 rounded-lg text-sm font-semibold transition-all"
            style={{
              background: breathActive ? theme.color : '#1a1a1f',
              color: breathActive ? '#0a0a0e' : '#e2e8f0',
              border: `1px solid ${breathActive ? theme.color : '#334155'}`,
            }}
          >
            {breathActive ? 'Stop Breath' : 'Start Breath'}
          </button>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Audio Level (0–1)</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={audioLevel}
              onChange={(e) => setAudioLevel(Number(e.target.value))}
              className="w-32"
            />
          </div>
        </div>
      </section>

      {/* Section 3: Hex Grid Preview (unchanged) */}
      <section className="flex flex-col items-center gap-4 mt-8">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
          Honeycomb Category Nodes — Hex Grid
        </h2>
        <HexGridPreview glowColor={theme.color} />
        <p className="text-xs text-slate-500">Click a node to toggle active state</p>
      </section>

      {/* Footer */}
      <div className="text-xs text-slate-600 mt-12 mb-8">
        Mockup preview — 3D spiral variants for iteration. Reference preserved for fallback.
      </div>
    </main>
  )
}
