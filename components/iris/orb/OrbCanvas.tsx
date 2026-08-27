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
//
// IMPORTANT: We render on a SIZE×SIZE canvas but the DOM element is always
// SIZE px wide/tall.  Previously SIZE=90 meant any bloom > 1.0 pushed
// lead-particles outside the canvas rect → visible clipping at the edges.
//
// Fix: increase SIZE to 120 (matching the orb container).  Particle coords
// are still computed relative to a 100×100 unit space and mapped to SIZE/2
// at rest, so the shell structure is visually identical but now has a full
// SIZE/2 = 60 px of headroom on every side for bloom expansion.

const DEFAULT_SIZE = 120   // was 90 — now matches the 120 px orb container

/**
 * Base period for one revolution of the speed-1.0 shell.
 *
 * The main orb keeps 28 s — a slow, ambient drift. Surfaces that render the
 * orb ALONGSIDE another moving element (the browser overlay, whose border
 * comet laps the card in ~5 s) pass their own period so the two read as one
 * system instead of two unrelated animations running at different speeds.
 */
const DEFAULT_ORBIT_PERIOD_MS = 28000

// Alphas and sizes were raised (0.55/0.40/0.85 -> 0.72/0.55/0.95) so the orb
// reads against a bright desktop wallpaper. Every particle is drawn with
// globalCompositeOperation='lighter' on a TRANSPARENT window, so its contrast
// is set by whatever sits behind the window. Additive light on a pale
// wallpaper is close to invisible. XurOrb also puts a scrim disc behind the
// canvas; the two changes are one fix and are tuned against each other.
const SHELLS = [
  { scale: 1.05, speed: 1.0, count: 80, alpha: 0.72, size: 1.0 },
  { scale: 0.70, speed: 1.45, count: 56, alpha: 0.55, size: 0.8 },
  { scale: 0.42, speed: 0.62, count: 32, alpha: 0.95, size: 0.7 },
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
  /** Central glow halo — voice active (listening STT OR TTS). Calm dot is always on. */
  glowActive?: boolean
  /** Size multiplier for the halo — TTS slightly larger than listening for consistency. */
  glowScale?: number
  /** Current animation mode from XurOrb (C/D/A) */
  animationMode?: AnimationMode | null
  /** 0-1 progress of current animation (optional, internal timing is primary) */
  animProgress?: number
  /** Is a click animation playing */
  animActive?: boolean
  /** Canvas edge length in px. Defaults to the 120 px main-orb container. */
  size?: number
  /**
   * Milliseconds for one revolution of the speed-1.0 shell. Defaults to the
   * main orb's ambient 28 s. Pass a shorter period to match a co-located
   * animation (see DEFAULT_ORBIT_PERIOD_MS). Safe to change mid-flight: shell
   * phase is INTEGRATED per frame, so a new period changes the rate without
   * moving any particle.
   */
  orbitPeriodMs?: number
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
 * - Central white inner core light — pulses with breathLevel
 * - Faint contained breath halo — Mode D cadence bloom stays inside orb
 * - Animation mode effects (bloom, scale ramp, speed ramp) when animActive
 */
export const OrbCanvas = React.memo(function OrbCanvas({
  glowColor,
  breathMode = "D",
  breathLevel = 0,
  isBreathing = false,
  animationMode = null,
  animProgress = 0,
  animActive = false,
  glowActive = false,
  glowScale = 1,
  size = DEFAULT_SIZE,
  orbitPeriodMs = DEFAULT_ORBIT_PERIOD_MS,
}: OrbCanvasProps) {
  // Shadows the former module-level constant so every SIZE reference below
  // (canvas backing store, unit-space mapping, particle radii, CSS box) scales
  // together from one number.
  const SIZE = size
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
  const glowActiveRef = useRef<boolean>(false)
  const glowScaleRef = useRef<number>(1)
  breathLevelRef.current = breathLevel
  isBreathingRef.current = isBreathing
  glowActiveRef.current = glowActive
  glowScaleRef.current = glowScale

  // Orbit pacing. Held in a ref (not an effect dep) so changing the period
  // never restarts the rAF loop — a restart would reset the clock and snap
  // every particle to a new position. Phase is integrated per frame below, so
  // the period can move continuously while the shells keep turning smoothly.
  const orbitPeriodRef = useRef<number>(orbitPeriodMs)
  orbitPeriodRef.current = orbitPeriodMs
  const shellPhasesRef = useRef<number[]>(SHELLS.map(() => 0))
  const lastFrameRef = useRef<number>(0)

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
      // coords in [0,100]² unit space — shifted to SIZE/2 center at render time
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

    // ── Mode C: big dramatic halo — spreads beyond shells like a voice aura.
    // Used for STT (listening) to show the orb is "hearing" the user.
    function drawBreathHalo(level: number, color: string) {
      if (level <= 0) return
      const center = SIZE / 2
      const maxRadius = SIZE * 1.2 * (1 + level * 0.8)
      ctx.save()
      ctx.fillStyle = color
      for (let r = 8; r > 0; r--) {
        const radius = maxRadius * (r / 8)
        ctx.globalAlpha = 0.35 * (1 - r / 8) * level
        ctx.beginPath()
        ctx.arc(center, center, radius, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.restore()
    }

    // ── Mode D: faint contained halo — stays well inside the orb boundary.
    // Max radius capped so it never exceeds the orb visual edge.
    function drawBreathHaloFaint(level: number, color: string) {
      if (level <= 0) return
      const center = SIZE / 2
      // Keep max radius comfortably inside the orb shell (~42% scale shell = ~37px)
      const maxRadius = SIZE * 0.22 * (1 + level * 0.35)
      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      ctx.fillStyle = color
      for (let r = 6; r > 0; r--) {
        const radius = maxRadius * (r / 6)
        ctx.globalAlpha = 0.18 * (1 - r / 6) * level
        ctx.beginPath()
        ctx.arc(center, center, radius, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.restore()
    }

    // ── Central white inner core — the "little white light" the user reported
    // missing.  Always visible at low base intensity; pulses brighter with
    // breathLevel when voice is active.  Uses 'lighter' blend so it adds
    // luminance on top of the dark canvas without needing a background.
    function drawCenterCore(level: number, color: string, glow: boolean, glowScale: number) {
      const center = SIZE / 2

      // ── Always-on CALM core dot (idle anchor) ──
      // The "little white light" that used to always sit at the orb's center.
      // A small, dim point with NO radiating glow, so the orb never looks
      // empty at idle but also never reads as "active".
      const idleCoreRadius = SIZE * 0.022
      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      const idleGrad = ctx.createRadialGradient(center, center, 0, center, center, idleCoreRadius)
      idleGrad.addColorStop(0, '#ffffff')
      idleGrad.addColorStop(0.6, color)
      idleGrad.addColorStop(1, 'transparent')
      ctx.globalAlpha = 0.62
      ctx.fillStyle = idleGrad
      ctx.beginPath()
      ctx.arc(center, center, idleCoreRadius, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()

      // ── Voice glow halo (listening STT OR TTS speaking) ──
      // The "voice is active" visual feedback: a contained, sized-down halo
      // that BREATHES with the cadence (level = audio envelope), so it pulses
      // with the words / user speech. TTS is rendered slightly LARGER than
      // listening (glowScale) for consistency across voice states. Off at idle
      // and during processing — the calm dot above is all you see then.
      if (!glow) return
      // Use a floor when voice is active so the listening glow is clearly
      // visible even with no incoming audio energy (silent mic / discarded
      // buffer).  Sustained "recording" feedback, not just on loud speech.
      const _lvl = glowActiveRef.current ? Math.max(level, 0.3) : level
      const intensity = 0.3 + _lvl * 0.5
      const coreRadius = SIZE * 0.035 * (1 + _lvl * 0.4) * glowScale

      ctx.save()
      ctx.globalCompositeOperation = 'lighter'

      // Outer soft halo — colored glow (sized down so it isn't oppressive)
      const haloRadius = coreRadius * 2.2
      const haloGrad = ctx.createRadialGradient(center, center, 0, center, center, haloRadius)
      haloGrad.addColorStop(0, color)
      haloGrad.addColorStop(1, 'transparent')
      ctx.globalAlpha = intensity * 0.22
      ctx.fillStyle = haloGrad
      ctx.beginPath()
      ctx.arc(center, center, haloRadius, 0, Math.PI * 2)
      ctx.fill()

      // Inner white core dot — the bright point (overlaps the calm dot, brighter)
      const coreGrad = ctx.createRadialGradient(center, center, 0, center, center, coreRadius)
      coreGrad.addColorStop(0, '#ffffff')
      coreGrad.addColorStop(0.5, color)
      coreGrad.addColorStop(1, 'transparent')
      ctx.globalAlpha = intensity * 0.9
      ctx.fillStyle = coreGrad
      ctx.beginPath()
      ctx.arc(center, center, coreRadius, 0, Math.PI * 2)
      ctx.fill()

      ctx.restore()
    }

    function drawShell(
      shell: typeof SHELLS[number],
      progress: number,
      s: number,
      scaleMul: number,
      bloom: number,
      overallAlpha: number,
      elapsed: number,
      breathColor: string,
      br: boolean,
      bl: number,
    ) {
      const currentAngle = progress * Math.PI * 2
      ctx.fillStyle = breathColor

      for (let i = 0; i < shell.count; i++) {
        const trailOffset = (i / shell.count) * Math.PI * 2
        const angle = currentAngle - trailOffset
        const pt = curvePoint(angle, s)
        const effectiveScale = shell.scale * scaleMul * bloom
        // Map from [0,100]² unit space → SIZE/2 radius at rest
        const px = ((pt.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
        const py = ((pt.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2

        const fade = 1 - i / shell.count
        const depthWave = 0.5 + 0.5 * Math.sin(angle * 0.5 + elapsed * 0.0003)
        const depthFactor = 0.9 + 0.1 * depthWave

        // Mode D cadence: sinusoidal brightness ripple along the trail
        let breathAlphaMult = 1
        if (br) {
          const waveLevel = br ? Math.max(bl, 0.28) : bl
          const wave =
            Math.sin((i / shell.count) * Math.PI * 4 - elapsed * 0.004) *
            waveLevel *
            2.5
          breathAlphaMult = Math.max(0.05, 1 + wave)
        }

        const particleSize = (0.65 + fade * 1.8) * (SIZE / 200) * shell.size
        ctx.globalAlpha = fade * 0.8 * shell.alpha * overallAlpha * depthFactor * breathAlphaMult
        ctx.beginPath()
        ctx.arc(px, py, particleSize, 0, Math.PI * 2)
        ctx.fill()
      }

      // Lead particle (brightest, front of trail)
      const lead = curvePoint(currentAngle, s)
      const effectiveScale = shell.scale * scaleMul * bloom
      const lx = ((lead.x - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
      const ly = ((lead.y - 50) / 50) * (SIZE / 2) * effectiveScale + SIZE / 2
      ctx.globalAlpha = shell.alpha * overallAlpha
      ctx.beginPath()
      ctx.arc(lx, ly, (SIZE / 72) * shell.size, 0, Math.PI * 2)
      ctx.fill()
    }

    function draw() {
      const elapsed = Date.now() - (startTimeRef.current ?? Date.now())
      const pulse = pulseRef.current
      const aPulse = pulseARef.current
      const mode = modeRef.current
      const bl = breathLevelRef.current
      const br = isBreathingRef.current
      const glow = glowActiveRef.current
      const glowScale = glowScaleRef.current

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

      // ── Cadence breathing (active whenever voice is active) ─────
      // breathMode differentiates STT (listening→"C") vs TTS (speaking→"D").
      // NOTE: previously gated on `bl > 0`, which meant a listening orb with
      // no incoming audio energy (e.g. VAD discarded the buffer, or the mic is
      // silent) looked IDENTICAL to idle — the user got zero "I'm listening"
      // feedback.  Now we drive the sustained voice-active visual off `br`
      // (isBreathing) with a minimum floor, so the orb always shows a clear
      // recording/listening state for the whole voice window, independent of
      // whether audio envelope data is flowing.  Real audio energy still
      // modulates the amplitude on top of the floor.
      const breathFloor = br ? Math.max(bl, 0.28) : bl
      if (br) {
        const breathPulse = breathFloor
        if (breathMode === 'C') {
          // STT / listening: big dramatic shell expansion + bright halo
          bloom *= 1 + breathPulse * 0.55
          scaleMul *= 1 + breathPulse * 0.38
        } else {
          // TTS / speaking (Mode D): subtle contained pulse, reduced bloom
          bloom *= 1 + breathPulse * 0.30
          scaleMul *= 1 + breathPulse * 0.14
        }
      }

      // ── Draw breath halo (behind shells) ───────────────────────
      if (br) {
        if (breathMode === 'C') {
          drawBreathHalo(breathFloor, glowColor)       // big dramatic halo for STT
        } else {
          drawBreathHaloFaint(breathFloor, glowColor)  // subtle contained for TTS
        }
      }

      // Integrate phase from the frame delta rather than deriving it from
      // absolute elapsed time. With `progress = elapsed % duration`, changing
      // the period teleports every particle to wherever the new formula puts
      // it; accumulating `dt / duration` changes only the RATE. dt is clamped
      // so a backgrounded tab resuming after seconds cannot fling the shells
      // through several revolutions in one frame.
      //
      // Session 247: the clamp MUST match BrowserNavigationOverlay's ring
      // loop (64 ms there). Both engines are pure integrators — neither ever
      // re-syncs to absolute time — so on a long frame (crawl rendering,
      // GC) each previously lost a DIFFERENT amount of advance (36 ms vs
      // 0 ms past its clamp) and the orb's cadence drifted against the
      // border comet it is supposed to keep time with. Equal clamps mean
      // equal lost time, which keeps the RATE locked even when individual
      // frames are dropped.
      const frameNow = Date.now()
      const dt = lastFrameRef.current
        ? Math.min(frameNow - lastFrameRef.current, 64)
        : 16
      lastFrameRef.current = frameNow
      const period = orbitPeriodRef.current
      const phases = shellPhasesRef.current

      for (let i = SHELLS.length - 1; i >= 0; i--) {
        const shell = SHELLS[i]
        const shellDuration = period / shell.speed
        phases[i] = (phases[i] + (dt * speedMult) / shellDuration) % 1
        drawShell(shell, phases[i], s, scaleMul, bloom, overallAlpha, elapsed, glowColor, br, bl)
      }

      // ── Central white core (drawn on top of shells) ─────────────
      drawCenterCore(bl, glowColor, glow, glowScale)

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
    // `size` re-inits the backing store; `orbitPeriodMs` deliberately does NOT
    // appear here — it is read through a ref so a period change cannot restart
    // the loop (see the note by orbitPeriodRef).
  }, [glowColor, SIZE])

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
})
