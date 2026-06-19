"use client"

import React, { useEffect, useRef } from "react"
import type { AnimationMode } from "./animationModes"
import {
  C_OPENING_MS,
  C_SETTLING_MS,
  C_TOTAL_MS,
  D_DECAY_PER_FRAME,
  D_BLOOM_AMPLITUDE,
  D_SPEED_MULTIPLIER,
  A_DECAY_PER_FRAME,
  A_BLOOM_AMPLITUDE,
  A_SPEED_MULTIPLIER,
} from "./animationModes"

// ── Shell configuration (same as PrototypeOrbShellsRotating) ──────────

const SIZE = 90

const SHELLS = [
  { scale: 1.05, speed: 1.0, count: 80, alpha: 0.55, size: 1.0 },
  { scale: 0.70, speed: 1.45, count: 56, alpha: 0.40, size: 0.8 },
  { scale: 0.42, speed: 0.62, count: 32, alpha: 0.85, size: 0.7 },
]

const PULSE_DURATION = 4200

// ── Props ────────────────────────────────────────────────────────────

export interface OrbCanvasProps {
  glowColor: string
  /** Cadence breathing — always "D" (the winner) */
  breathMode?: string
  /** 0-1 audio level from backend cadence detection */
  breathLevel?: number
  /** Is voice active (listening/speaking/processing) */
  isBreathing?: boolean
  /** Current animation mode from XurOrb (C/D/A) */
  animationMode?: AnimationMode | null
  /** 0-1 progress of current animation (optional, internal timing is primary) */
  animProgress?: number
  /** Is a click animation playing */
  animActive?: boolean
}

/**
 * OrbCanvas — pure visual canvas rendering for XurOrb.
 *
 * Extracted from PrototypeOrbShellsRotating.tsx. This is the 3-shell
 * particle system WITHOUT:
 * - Click handlers / state machine (handled by XurOrb)
 * - Built-in labels (handled by GlitchText)
 * - Animation mode cycling (handled by XurOrb via animationModes)
 *
 * The canvas draws:
 * - 3 concentric particle shells (105% / 70% / 42% scale)
 * - Depth-aware alpha
 * - Per-shell rotation speed
 * - Cadence-driven scale pulsing (from breathLevel)
 * - Animation mode effects (bloom, scale ramp, speed ramp) when animActive
 */
export function OrbCanvas({
  glowColor,
  breathMode = "D",
  breathLevel = 0,
  isBreathing = false,
  animationMode = null,
  animProgress = 0,
  animActive = false,
}: OrbCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const startTimeRef = useRef<number>(0)
  const animStartRef = useRef<number>(0)
  const pulseRef = useRef<number>(0)
  const pulseARef = useRef<number>(0)
  const modeRef = useRef<AnimationMode | null>(null)
  const animActiveRef = useRef<boolean>(false)

  // Breath level ref — updated every render so the rAF loop reads fresh values
  const breathLevelRef = useRef<number>(0)
  const isBreathingRef = useRef<boolean>(false)
  breathLevelRef.current = breathLevel
  isBreathingRef.current = isBreathing

  // Trigger animation when mode changes and animActive is true
  useEffect(() => {
    if (animActive && animationMode) {
      modeRef.current = animationMode
      animActiveRef.current = true
      if (animationMode === 'C') {
        animStartRef.current = Date.now()
      } else if (animationMode === 'D') {
        pulseRef.current = 1
      } else if (animationMode === 'A') {
        pulseARef.current = 1
      }
    }
  }, [animationMode, animActive])

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
      if (elapsed < C_OPENING_MS) {
        const t = elapsed / C_OPENING_MS
        const sin = Math.sin(t * Math.PI)
        const ease = 1 - Math.pow(1 - t, 2)
        return {
          shellScale: 0.7 + 0.35 * ease,
          bloom: 1 + 0.18 * sin,
          speedMult: 1 + 1.5 * sin,
          overallAlpha: 0.55 + 0.45 * ease,
        }
      } else if (elapsed < C_TOTAL_MS) {
        const t = (elapsed - C_OPENING_MS) / C_SETTLING_MS
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
        const px = ((pt.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
        const py = ((pt.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2

        const fade = 1 - i / shell.count
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
      const aPulse = pulseARef.current
      const mode = modeRef.current
      ctx.clearRect(0, 0, SIZE, SIZE)
      ctx.globalCompositeOperation = 'lighter'
      const s = detailScale(elapsed)

      let scaleMul = 1
      let bloom = 1
      let speedMult = 1
      let overallAlpha = 1

      // ── Click animation modes ──────────────────────────────────
      if (mode === 'C') {
        const transitionElapsed = Date.now() - animStartRef.current
        const state = getTransitionState(transitionElapsed)
        scaleMul = state.shellScale
        bloom = state.bloom
        speedMult = state.speedMult
        overallAlpha = state.overallAlpha
        // Clear mode when transition completes
        if (transitionElapsed > C_TOTAL_MS) {
          modeRef.current = null
        }
      } else if (mode === 'D') {
        speedMult = 1 + pulse * D_SPEED_MULTIPLIER
        bloom = 1 + pulse * D_BLOOM_AMPLITUDE
      } else if (mode === 'A') {
        speedMult = 1 + aPulse * A_SPEED_MULTIPLIER
        bloom = 1 + aPulse * A_BLOOM_AMPLITUDE
      }

      // ── Cadence breathing (always active when isBreathing) ─────
      // Breath level drives a gentle scale pulse on top of any
      // click animation. This ensures the orb "breathes" with the
      // user's speech rhythm at all navigation levels.
      if (isBreathingRef.current && breathLevelRef.current > 0) {
        const breathPulse = breathLevelRef.current
        bloom *= 1 + breathPulse * 0.15
        scaleMul *= 1 + breathPulse * 0.08
      }

      for (let i = SHELLS.length - 1; i >= 0; i--) {
        const shell = SHELLS[i]
        const shellDuration = 28000 / shell.speed
        const progress = ((elapsed * speedMult) % shellDuration) / shellDuration
        drawShell(shell, progress, s, scaleMul, bloom, overallAlpha, elapsed)
      }

      // ── Pulse decay ────────────────────────────────────────────
      if (pulseRef.current > 0) {
        pulseRef.current = Math.max(0, pulseRef.current - D_DECAY_PER_FRAME)
      }
      if (pulseARef.current > 0) {
        pulseARef.current = Math.max(0, pulseARef.current - A_DECAY_PER_FRAME)
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [glowColor])

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: `${SIZE}px`,
        height: `${SIZE}px`,
        display: 'block',
      }}
    />
  )
}
