/**
 * animationModes.ts — C/D/A animation parameter bundles for XurOrb.
 *
 * Extracted from PrototypeOrbShellsRotating.tsx. The 3 click animation
 * modes are now separate, individually tweakable parameter bundles so
 * each mode's speed/timing can be adjusted independently.
 *
 * Timing adjustments from original prototype values:
 *   C-pair: OPENING_MS 1700→1400, SETTLING_MS 600→500 (user wants shorter)
 *   D-pair: DECAY_PER_FRAME 0.022→0.025 (slightly faster decay)
 *   A-pair: unchanged (0.008)
 */

export type AnimationMode = 'C' | 'D' | 'A'

/**
 * Cycle to the next animation mode: C → D → A → C.
 * This ensures every third click is the C-pair (opening transition).
 */
export function nextAnimationMode(current: AnimationMode): AnimationMode {
  const order: AnimationMode[] = ['C', 'D', 'A']
  const idx = order.indexOf(current)
  return order[(idx + 1) % order.length]
}

// ── C-pair: Opening transition ───────────────────────────────────────
// Shells expand outward (0.7→1.05 scale), bloom 1→1.18, speed ramps
// 1→2.5→1. Time-based state machine with opening + settling phases.

export const C_OPENING_MS = 1400  // reduced from 1700
export const C_SETTLING_MS = 500  // reduced from 600
export const C_TOTAL_MS = C_OPENING_MS + C_SETTLING_MS

export interface COpeningParams {
  shellScale: [number, number]     // [0.7, 1.05] — min to peak
  bloom: [number, number]          // [1, 1.18] — min to peak
  speedMult: [number, number]      // [1, 2.5] — ramp up then down
}

export const C_PARAMS: COpeningParams = {
  shellScale: [0.7, 1.05],
  bloom: [1, 1.18],
  speedMult: [1, 2.5],
}

// ── D-pair: Gentle burst ─────────────────────────────────────────────
// Fast pulse decay. Pulse + 0.9× speed, 0.25 bloom amplitude.

export const D_DECAY_PER_FRAME = 0.025  // was 0.022 (slightly faster)
export const D_BLOOM_AMPLITUDE = 0.25
export const D_SPEED_MULTIPLIER = 0.9

export interface DGentleBurstParams {
  bloomAmplitude: number           // 0.25
  speedMultiplier: number          // 0.9
}

export const D_PARAMS: DGentleBurstParams = {
  bloomAmplitude: D_BLOOM_AMPLITUDE,
  speedMultiplier: D_SPEED_MULTIPLIER,
}

// ── A-pair: Big bloom ────────────────────────────────────────────────
// Slow deliberate bloom. 0.7× speed, 0.25 bloom, ~2s decay.

export const A_DECAY_PER_FRAME = 0.008
export const A_BLOOM_AMPLITUDE = 0.25
export const A_SPEED_MULTIPLIER = 0.7

export interface ABigBloomParams {
  bloomAmplitude: number           // 0.25
  speedMultiplier: number          // 0.7
}

export const A_PARAMS: ABigBloomParams = {
  bloomAmplitude: A_BLOOM_AMPLITUDE,
  speedMultiplier: A_SPEED_MULTIPLIER,
}

// ── Duration map (used by XurOrb to time its animActive state) ────────

export const ANIM_DURATION_MS: Record<AnimationMode, number> = {
  C: C_TOTAL_MS,   // 1900ms (1400 + 500)
  D: 750,          // ~0.75s decay
  A: 2000,         // ~2s decay
}
