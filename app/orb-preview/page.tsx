'use client'

import React, { useState } from 'react'
import { PrototypeOrb } from '@/components/preview/PrototypeOrb'
import { PrototypeOrbDepthAlpha } from '@/components/preview/PrototypeOrbDepthAlpha'
import { PrototypeOrbShellsRotating } from '@/components/preview/PrototypeOrbShellsRotating'
import { PrototypeOrbShells } from '@/components/preview/PrototypeOrbShells'
import { PrototypeOrbShellsDepth } from '@/components/preview/PrototypeOrbShellsDepth'
import { PrototypeOrbBreathing } from '@/components/preview/PrototypeOrbBreathing'
import { CadenceBreathDemo } from '@/components/preview/CadenceBreathDemo'
import { HexGridPreview } from '@/components/preview/HexGridPreview'
import { MenuMockups } from '@/components/preview/MenuMockups'
import { WheelRingStyles } from '@/components/preview/WheelRingStyles'

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

// Four breath-effect options for the voice breath glow area. Each option
// uses Mockup B (the winning rotating variant) underneath and applies a
// different audio-reactive visual on top of the shell structure.
type BreathKey = 'A' | 'B' | 'C' | 'D'

const BREATH_OPTIONS: { key: BreathKey; title: string; description: string }[] = [
  {
    key: 'A',
    title: 'Shell breathing',
    description: 'The 3 shells expand outward with audio. The whole orb visibly inhales/exhales. Most integrated, least distracting — the breath IS the orb.',
  },
  {
    key: 'B',
    title: 'Audio-reactive particle wave',
    description: 'A bright sine wave ripples along the spiral trail with audio. Peaks and troughs sweep through like a VU meter on the Xur signature. Most dynamic, most "alive".',
  },
  {
    key: 'C',
    title: 'Inner halo + shell breathing',
    description: 'A combined: shells expand up to 2× AND a soft additive halo radiates from the center. The most visually dramatic of all four options.',
  },
  {
    key: 'D',
    title: 'Combined — wave + pulse + halo',
    description: 'All three effects at once: particle wave ripples along the trail, shells pulse gently with audio, and a faint inner halo stays contained within the orb. The most layered but never overwhelming.',
  },
]

// Sub-component for each breath option — holds its own Start Breath
// and audio level state so the user can compare the four independently.
function BreathOption({
  label,
  title,
  description,
  glowColor,
  isWinner = false,
}: {
  label: BreathKey
  title: string
  description: string
  glowColor: string
  isWinner?: boolean
}) {
  const [isBreathing, setIsBreathing] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0.4)

  return (
    <div
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
              : glowColor,
            color: isWinner ? '#0a0a0e' : '#0a0a0e',
            boxShadow: isWinner ? '0 0 14px rgba(251, 191, 36, 0.5)' : 'none',
          }}
        >
          {isWinner ? '★ WINNER' : label}
        </span>
        <h3 className="text-sm font-semibold text-white tracking-wide">
          {title}
        </h3>
      </div>

      {/* Orb with the breath effect */}
      <div
        className="relative flex items-center justify-center"
        style={{ width: 240, height: 240 }}
      >
        <PrototypeOrbBreathing
          glowColor={glowColor}
          breathMode={label}
          breathLevel={audioLevel}
          isBreathing={isBreathing}
        />
      </div>

      {/* Description */}
      <p className="text-xs text-slate-400 text-center leading-relaxed max-w-xs">
        {description}
      </p>

      {/* Audio level meter */}
      <div className="flex flex-col gap-1 w-full max-w-xs">
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
            Audio Level
          </span>
          <span className="text-[10px] font-mono text-slate-400">
            {audioLevel.toFixed(2)}
          </span>
        </div>
        <div
          className="w-full h-1.5 rounded-full overflow-hidden"
          style={{ background: '#1a1a1f', border: '1px solid #1f2937' }}
        >
          <div
            style={{
              width: `${audioLevel * 100}%`,
              height: '100%',
              background: `linear-gradient(90deg, ${glowColor}88, ${glowColor})`,
              transition: 'width 0.1s ease-out',
            }}
          />
        </div>
        <input
          type="range"
          min={0}
          max={1}
          step={0.02}
          value={audioLevel}
          onChange={(e) => setAudioLevel(Number(e.target.value))}
          className="w-full"
        />
      </div>

      {/* Start Breath button */}
      <button
        onClick={() => setIsBreathing(!isBreathing)}
        className="px-4 py-2 rounded-lg text-sm font-semibold transition-all"
        style={{
          background: isBreathing ? glowColor : '#1a1a1f',
          color: isBreathing ? '#0a0a0e' : '#e2e8f0',
          border: `1px solid ${isBreathing ? glowColor : '#334155'}`,
        }}
      >
        {isBreathing ? 'Stop Breath' : 'Start Breath'}
      </button>
    </div>
  )
}

export default function OrbPreviewPage() {
  const [themeIndex, setThemeIndex] = useState(0)
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
            const isWinner = v.key === 'rotating' || v.key === 'radial-arc-web'
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

      {/* Section 2: Voice Breath Glow — 4 breath options for Mockup B */}
      <section className="flex flex-col items-center gap-8 mt-12 px-6 w-full max-w-6xl">
        <div className="flex flex-col items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
            Voice Breath Glow — 4 Options for Mockup B
          </h2>
          <p className="text-xs text-slate-500 text-center max-w-xl">
            Each option pairs Mockup B (the winning rotating variant) with a different audio-reactive breath.
            Toggle Start Breath, then drag the Audio Level slider to see how the orb responds.
            Click the orb itself to cycle through the C / D / A click behaviors.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 w-full">
          {BREATH_OPTIONS.map((opt) => (
            <BreathOption
              key={opt.key}
              label={opt.key}
              title={opt.title}
              description={opt.description}
              glowColor={theme.color}
              isWinner={opt.key === 'D'}
            />
          ))}
        </div>
      </section>

      {/* Section 3: Cadence Detection Demo */}
      <section id="cadence-section" className="flex flex-col items-center gap-8 mt-12 px-6 w-full max-w-6xl">
        <div className="flex flex-col items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
            Cadence Detection — Live Microphone Demo
          </h2>
          <p className="text-xs text-slate-500 text-center max-w-xl">
            Speech rhythm drives the orb, not volume. Click Start Listening, then speak —
            the orb breathes with your syllable cadence. Whisper to see cadence beats without volume.
          </p>
        </div>

        <CadenceBreathDemo glowColor={theme.color} />
      </section>

      {/* Section 4: Category Menu Mockups */}
      <section className="flex flex-col items-center gap-4 mt-12">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
          Category Menu Mockups — Pick a Winner
        </h2>
        <MenuMockups glowColor={theme.color} />
      </section>

      {/* Section 4.5: Wheel Ring Surface Styles — hex node aesthetic on interactive rings */}
      <section className="flex flex-col items-center gap-4 mt-12 px-6 w-full max-w-6xl">
        <div className="flex flex-col items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-widest">
            Wheel Ring Surface Styles — Hex Node Aesthetic
          </h2>
          <p className="text-xs text-slate-500 text-center max-w-xl">
            4 surface treatments for the outer + inner interactive rings, matching the hex node styling from the menu mockups.
            The wheel structure (decorative rings, ticks, energy beams) stays the same — only the segment surface changes.
            Click a segment to select it.
          </p>
        </div>
        <WheelRingStyles glowColor={theme.color} />
      </section>

      {/* Section 5: Hex Grid Preview (unchanged) */}
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
