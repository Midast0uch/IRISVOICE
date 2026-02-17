// === CHROMASHIFT COLOR INTELLIGENCE ===
// Utilities for generating theme-specific colors from Brand Hue

export interface GeneratedColors {
  primary: string
  secondary: string
  accent: string
  glow: string
  shimmer?: string[]
  edgeGlow?: string
  metal?: string[]
}

// === AETHER THEME GENERATORS ===
// Prismatic shimmer with full vibrancy

export function generateAetherShimmers(hue: number): {
  start: string
  mid: string
  end: string
  glow: string
} {
  return {
    start: `hsl(${hue}, 90%, 60%)`,
    mid: `hsl(${(hue + 30) % 360}, 80%, 65%)`,
    end: `hsl(${(hue + 60) % 360}, 70%, 55%)`,
    glow: `hsl(${hue}, 70%, 60%, 0.3)`,
  }
}

export function generateAetherGradient(hue: number): string {
  const colors = generateAetherShimmers(hue)
  return `linear-gradient(90deg, ${colors.start}, ${colors.mid}, ${colors.end})`
}

// === EMBER THEME GENERATORS ===
// Warm industrial with saturation cap and amber shift

export function generateEmberGlow(hue: number, saturation: number): {
  edgeGlow: string
  edgeSoft: string
  interactionWash: string
  warmedHue: number
  cappedSaturation: number
} {
  // Apply warmth shift (+10° towards amber/orange)
  const warmedHue = (hue + 10) % 360
  // Cap saturation at 70% for metallic realism
  const cappedSaturation = Math.min(saturation, 70)
  
  return {
    warmedHue,
    cappedSaturation,
    edgeGlow: `hsl(${warmedHue}, ${cappedSaturation * 0.6}%, 45%)`,
    edgeSoft: `hsl(${warmedHue}, ${cappedSaturation * 0.5}%, 50%, 0.3)`,
    interactionWash: `hsl(${warmedHue}, ${cappedSaturation * 0.4}%, 50%, 0.1)`,
  }
}

export function generateEmberEdgeGradient(hue: number, saturation: number): string {
  const { warmedHue, cappedSaturation } = generateEmberGlow(hue, saturation)
  return `linear-gradient(180deg, hsl(${warmedHue}, ${cappedSaturation * 0.6}%, 45%), transparent 80%)`
}

// === AURUM THEME GENERATORS ===
// Liquid metal with heavy desaturation

export function generateAurumMetal(hue: number, saturation: number): {
  primary: string
  secondary: string
  highlight: string
  ambient: string
  desaturatedSaturation: number
} {
  // Heavy desaturation (40% of base) for metallic effect
  const desaturatedSaturation = saturation * 0.4
  
  return {
    desaturatedSaturation,
    primary: `hsl(${hue}, ${desaturatedSaturation}%, 55%)`,
    secondary: `hsl(${(hue - 20 + 360) % 360}, ${desaturatedSaturation * 1.25}%, 45%)`,
    highlight: `hsl(${hue}, ${desaturatedSaturation * 1.5}%, 70%)`,
    ambient: `hsl(${hue}, 60%, 50%, 0.15)`,
  }
}

export function generateAurumConicGradient(hue: number, saturation: number): string {
  const metal = generateAurumMetal(hue, saturation)
  return `conic-gradient(from 0deg, ${metal.primary}, ${metal.highlight}, ${metal.secondary}, ${metal.primary})`
}

// === ACCESSIBILITY UTILITIES ===

/**
 * Calculate relative luminance of a color
 * https://www.w3.org/TR/WCAG20/#relativeluminancedef
 */
export function getLuminance(r: number, g: number, b: number): number {
  const [rs, gs, bs] = [r, g, b].map(c => {
    const channel = c / 255
    return channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs
}

/**
 * Convert HSL to RGB
 */
export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  s /= 100
  l /= 100
  const k = (n: number) => (n + h / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)]
}

/**
 * Calculate contrast ratio between two luminances
 */
export function getContrastRatio(lum1: number, lum2: number): number {
  const lighter = Math.max(lum1, lum2)
  const darker = Math.min(lum1, lum2)
  return (lighter + 0.05) / (darker + 0.05)
}

/**
 * Check if a color meets WCAG AA contrast requirements
 */
export function meetsContrastRequirements(
  foregroundHue: number,
  foregroundSat: number,
  foregroundLight: number,
  backgroundLuminance: number,
  level: 'AA' | 'AAA' = 'AA',
  textSize: 'normal' | 'large' = 'normal'
): { passes: boolean; ratio: number; suggestedLightness: number } {
  const [r, g, b] = hslToRgb(foregroundHue, foregroundSat, foregroundLight)
  const luminance = getLuminance(r, g, b)
  const ratio = getContrastRatio(luminance, backgroundLuminance)
  
  const requiredRatio = level === 'AAA' ? 7 : textSize === 'large' ? 3 : 4.5
  
  // Suggest adjusted lightness if needed
  let suggestedLightness = foregroundLight
  if (ratio < requiredRatio) {
    // Binary search for better lightness
    if (backgroundLuminance < 0.5) {
      // Dark background - try lighter
      suggestedLightness = Math.min(95, foregroundLight + 20)
    } else {
      // Light background - try darker
      suggestedLightness = Math.max(5, foregroundLight - 20)
    }
  }
  
  return {
    passes: ratio >= requiredRatio,
    ratio: Math.round(ratio * 10) / 10,
    suggestedLightness: Math.round(suggestedLightness),
  }
}

// === COLOR HARMONY UTILITIES ===

export function getComplementaryHue(hue: number): number {
  return (hue + 180) % 360
}

export function getAnalogousHues(hue: number): [number, number] {
  return [(hue - 30 + 360) % 360, (hue + 30) % 360]
}

export function getTriadicHues(hue: number): [number, number] {
  return [(hue + 120) % 360, (hue + 240) % 360]
}

export function getSplitComplementary(hue: number): [number, number] {
  return [(hue + 150) % 360, (hue + 210) % 360]
}

// === PRESET BRAND COLORS ===
export const PRESET_COLORS = [
  { name: 'Cyan-Blue', hue: 210, saturation: 80, lightness: 55, theme: 'aether' as const },
  { name: 'Ember Orange', hue: 24, saturation: 85, lightness: 55, theme: 'ember' as const },
  { name: 'Aurum Gold', hue: 45, saturation: 90, lightness: 55, theme: 'aurum' as const },
  { name: 'Corporate Blue', hue: 220, saturation: 70, lightness: 50, theme: 'aether' as const },
  { name: 'Forest Green', hue: 150, saturation: 60, lightness: 45, theme: 'ember' as const },
  { name: 'Royal Purple', hue: 270, saturation: 65, lightness: 50, theme: 'aurum' as const },
  { name: 'Ruby Red', hue: 350, saturation: 75, lightness: 50, theme: 'ember' as const },
  { name: 'Teal', hue: 180, saturation: 70, lightness: 45, theme: 'aether' as const },
  { name: 'Coral', hue: 15, saturation: 80, lightness: 60, theme: 'ember' as const },
  { name: 'Slate', hue: 210, saturation: 30, lightness: 50, theme: 'aurum' as const },
  { name: 'Magenta', hue: 300, saturation: 70, lightness: 55, theme: 'aether' as const },
  { name: 'Lime', hue: 90, saturation: 75, lightness: 50, theme: 'ember' as const },
]

// === SMOOTH TRANSITION UTILITIES ===

/**
 * Interpolate between two hue values, taking the shortest path around the color wheel
 */
export function interpolateHue(from: number, to: number, progress: number): number {
  const diff = to - from
  let adjustedDiff = diff
  
  // Take the shortest path around the wheel
  if (diff > 180) adjustedDiff = diff - 360
  if (diff < -180) adjustedDiff = diff + 360
  
  const result = from + adjustedDiff * progress
  return ((result % 360) + 360) % 360
}

/**
 * Interpolate between two numeric values
 */
export function interpolateValue(from: number, to: number, progress: number): number {
  return from + (to - from) * progress
}

/**
 * Generate transition keyframes for hue animation
 */
export function generateHueTransition(from: number, to: number, steps: number = 30): number[] {
  return Array.from({ length: steps }, (_, i) => interpolateHue(from, to, i / (steps - 1)))
}
