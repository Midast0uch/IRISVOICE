/**
 * WinTransitionEngine — transition logic for RadialArcNodes enter/exit.
 *
 * The orb's own click animations (C/D/A modes) are handled separately
 * by animationModes.ts. This file is kept for the RadialArcNodes only —
 * it provides the random transition picker and the Photon Burst flash
 * helper used during node enter/exit animations.
 */

export type WinTransition = 'spiral' | 'gravity' | 'magnet'

export const WIN_DURATION_MS = 700
export const ENTER_DURATION_MS = 600

/**
 * Pick a random transition that differs from the current one,
 * so consecutive menu opens always feel different.
 */
export function pickRandomTransition(current: WinTransition): WinTransition {
  const options: WinTransition[] = ['spiral', 'gravity', 'magnet']
  const filtered = options.filter(t => t !== current)
  return filtered[Math.floor(Math.random() * filtered.length)]
}

/**
 * Photon Burst flash — a brightness/scale curve used for the
 * "winner" enter animation. First 15% is a rapid flash up,
 * remaining 85% settles back down.
 *
 * @param t  Normalized time 0–1
 */
export function photonFlash(t: number): { brightness: number; scale: number } {
  if (t < 0.15) {
    const flash = t / 0.15
    return { brightness: 1 + flash * 2, scale: 1 + flash * 0.25 }
  }
  const settle = (t - 0.15) / 0.85
  return { brightness: 3 - settle * 2, scale: 1.25 - settle * 0.25 }
}
