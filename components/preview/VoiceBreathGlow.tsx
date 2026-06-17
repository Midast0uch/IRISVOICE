'use client'

import React, { useEffect, useRef, useState } from 'react'

interface VoiceBreathGlowProps {
  glowColor: string
  isActive: boolean
  audioLevel?: number // 0–1
}

/**
 * VoiceBreathGlow — Biological breathing animation overlay for voice-active states.
 *
 * Breathing cycle (~3.5s):
 *   - Inhale (0–1.5s): glow opacity 0.2 → 0.8, scale 1.0 → 1.06, halo expands
 *   - Hold (1.5–2.5s): plateau + micro heartbeat flutter every 1.2s
 *   - Exhale (2.5–3.5s): contracts and dims back to rest
 *
 * Three stacked fluorescent glow layers:
 *   - Inner core: white → glowColor at mix-blend-mode: screen
 *   - Middle body: glowColor at 40% opacity, blur 30px
 *   - Outer atmosphere: glowColor at 10% opacity, blur 80px, expands with breath
 *
 * Audio reactivity: exhale speed increases with audioLevel.
 * Chromatic aberration at peak inhale (hue-shifted +15deg, 2px offset).
 */
export function VoiceBreathGlow({ glowColor, isActive, audioLevel = 0 }: VoiceBreathGlowProps) {
  const rafRef = useRef<number>(0)
  const [opacity, setOpacity] = useState(0.2)
  const [scale, setScale] = useState(1)
  const [haloInset, setHaloInset] = useState(-40)
  const [aberrationOffset, setAberrationOffset] = useState(0)
  const cycleStartRef = useRef<number>(0)

  // Compute hue-shifted color for chromatic aberration
  const hueShiftedColor = React.useMemo(() => {
    // Simple hex → HSL shift approximation
    // For mockup, we'll use a CSS filter approach instead
    return glowColor
  }, [glowColor])

  useEffect(() => {
    if (!isActive) {
      setOpacity(0.2)
      setScale(1)
      setHaloInset(-40)
      setAberrationOffset(0)
      return
    }

    cycleStartRef.current = Date.now()

    function tick() {
      const now = Date.now()
      const elapsed = now - cycleStartRef.current
      const cycleMs = 3500
      const t = (elapsed % cycleMs) / cycleMs

      // Breathing phases
      let phaseOpacity: number
      let phaseScale: number
      let phaseHalo: number
      let phaseAberration: number

      if (t < 0.428) {
        // Inhale: 0 → 0.428 (0–1.5s of 3.5s)
        const inhaleT = t / 0.428
        phaseOpacity = 0.2 + (0.6 * inhaleT)
        phaseScale = 1.0 + (0.06 * inhaleT)
        phaseHalo = -40 + (-50 * inhaleT) // -40 → -90
        phaseAberration = inhaleT > 0.85 ? (inhaleT - 0.85) / 0.15 : 0 // peak at end of inhale
      } else if (t < 0.714) {
        // Hold: 0.428 → 0.714 (1.5–2.5s)
        const holdT = (t - 0.428) / 0.286
        // Micro heartbeat: 1.03 → 1.0 → 1.03 every 1.2s
        const heartbeat = Math.sin(holdT * Math.PI * 2 * (1.2 / 0.286)) * 0.015
        phaseOpacity = 0.8
        phaseScale = 1.06 + heartbeat
        phaseHalo = -90
        phaseAberration = 0
      } else {
        // Exhale: 0.714 → 1.0 (2.5–3.5s)
        const exhaleT = (t - 0.714) / 0.286
        // Audio reactivity: faster exhale with louder input
        const audioFactor = 1 + audioLevel * 0.5
        const accelerated = Math.min(exhaleT * audioFactor, 1)
        phaseOpacity = 0.8 - (0.6 * accelerated)
        phaseScale = 1.06 - (0.06 * accelerated)
        phaseHalo = -90 + (50 * accelerated)
        phaseAberration = 0
      }

      setOpacity(phaseOpacity)
      setScale(phaseScale)
      setHaloInset(phaseHalo)
      setAberrationOffset(phaseAberration)

      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [isActive, audioLevel])

  if (!isActive) return null

  return (
    <div
      className="absolute inset-0 flex items-center justify-center pointer-events-none"
      style={{ transform: `scale(${scale})` }}
    >
      {/* 1. Outer atmosphere glow — expands/contracts with breath */}
      <div
        className="absolute rounded-full"
        style={{
          inset: `${haloInset}px`,
          background: `radial-gradient(circle, ${glowColor}10 0%, transparent 70%)`,
          filter: 'blur(80px)',
          opacity: opacity * 0.4,
          transition: 'none',
        }}
      />

      {/* 2. Middle body glow */}
      <div
        className="absolute rounded-full"
        style={{
          inset: '-30px',
          background: `radial-gradient(circle, ${glowColor}40 0%, transparent 70%)`,
          filter: 'blur(30px)',
          opacity: opacity * 0.8,
          transition: 'none',
        }}
      />

      {/* 3. Inner fluorescent core — screen blend for tube brightness */}
      <div
        className="absolute rounded-full"
        style={{
          inset: '-8px',
          background: `radial-gradient(circle, #ffffff 0%, ${glowColor} 40%, transparent 100%)`,
          mixBlendMode: 'screen',
          opacity: opacity,
          transition: 'none',
        }}
      />

      {/* 4. Chromatic aberration at peak inhale */}
      {aberrationOffset > 0 && (
        <>
          <div
            className="absolute rounded-full"
            style={{
              inset: '-8px',
              background: `radial-gradient(circle, #ffffff 0%, ${glowColor} 40%, transparent 100%)`,
              mixBlendMode: 'screen',
              opacity: aberrationOffset * 0.5,
              transform: `translateX(2px)`,
              filter: 'hue-rotate(15deg)',
              transition: 'none',
            }}
          />
          <div
            className="absolute rounded-full"
            style={{
              inset: '-8px',
              background: `radial-gradient(circle, #ffffff 0%, ${glowColor} 40%, transparent 100%)`,
              mixBlendMode: 'screen',
              opacity: aberrationOffset * 0.3,
              transform: `translateX(-2px)`,
              filter: 'hue-rotate(-15deg)',
              transition: 'none',
            }}
          />
        </>
      )}
    </div>
  )
}
