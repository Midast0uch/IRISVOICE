/**
 * Brand palette: three neighbouring hues (head, body, tail) for the Xur's
 * trail and the wing edge chrome. Design: docs/design/chatview-2026-10-06
 * (iris-strands.html `setBrand` / `trailColor`).
 *
 * The rule, per active theme:
 *   - the theme's shimmer triple (primary, secondary, accent) when its three
 *     hues really differ (>= MIN_SPREAD degrees). Aether does (hue, +30, +60).
 *   - otherwise (Ember, Aurum, Verdant shimmer are one hue at three
 *     lightnesses, which would draw one flat colour) the concept's neighbour
 *     hues around the brand hue: THEME_OFFSETS below.
 *   - no theme (no provider): brand hue 190 with the concept's +25 / -40.
 */

export type Palette = readonly [string, string, string]

export interface Hsl { h: number; s: number; l: number }

const MIN_SPREAD = 20

/** Concept THEMES table: [second hue offset, third hue offset]. */
const THEME_OFFSETS: Record<string, readonly [number, number]> = {
  aether: [25, -40],
  ember: [-35, -55],
  aurum: [15, -25],
  verdant: [45, -55],
}
const DEFAULT_OFFSETS: readonly [number, number] = [25, -40]

const norm = (h: number) => ((h % 360) + 360) % 360
const hslStr = (h: number, s: number, l: number, a?: number) =>
  a === undefined
    ? `hsl(${norm(h).toFixed(1)}, ${s.toFixed(1)}%, ${l.toFixed(1)}%)`
    : `hsla(${norm(h).toFixed(1)}, ${s.toFixed(1)}%, ${l.toFixed(1)}%, ${a})`

function rgbToHsl(r: number, g: number, b: number): Hsl {
  r /= 255; g /= 255; b /= 255
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min
  const l = (max + min) / 2
  if (d === 0) return { h: 0, s: 0, l: l * 100 }
  const s = d / (1 - Math.abs(2 * l - 1))
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return { h: norm(h * 60), s: s * 100, l: l * 100 }
}

/** Parse #hex, hsl()/hsla() and rgb()/rgba(). Null when it is none of these. */
export function parseColor(c: string): Hsl | null {
  const s = c.trim()
  if (s.startsWith('#')) {
    let x = s.slice(1)
    if (x.length === 3 || x.length === 4) x = x.split('').map((ch) => ch + ch).join('')
    if (x.length !== 6 && x.length !== 8) return null
    const n = parseInt(x.slice(0, 6), 16)
    if (Number.isNaN(n)) return null
    return rgbToHsl((n >> 16) & 255, (n >> 8) & 255, n & 255)
  }
  const hsl = s.match(/^hsla?\(\s*([\d.+-]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%/i)
  if (hsl) return { h: norm(+hsl[1]), s: +hsl[2], l: +hsl[3] }
  const rgb = s.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i)
  if (rgb) return rgbToHsl(+rgb[1], +rgb[2], +rgb[3])
  return null
}

/** The colour with an alpha. Unparseable input comes back unchanged. */
export function withAlpha(color: string, a: number): string {
  const p = parseColor(color)
  return p ? hslStr(p.h, p.s, p.l, a) : color
}

/** Neighbouring hues around one brand hue (concept `setBrand`). */
export function paletteFromHue(hue: number, d2 = DEFAULT_OFFSETS[0], d3 = DEFAULT_OFFSETS[1]): Palette {
  return [hslStr(hue, 100, 64), hslStr(hue + d2, 92, 68), hslStr(hue + d3, 85, 60)]
}

function hueSpread(p: Palette): number | null {
  const hs = p.map(parseColor)
  if (hs.some((x) => x === null)) return null
  const base = (hs[0] as Hsl).h
  return Math.max(...hs.map((x) => {
    const d = Math.abs((x as Hsl).h - base)
    return Math.min(d, 360 - d)
  }))
}

/**
 * The palette for the active theme. `shimmer` is ThemeConfig.shimmer, `hue` the
 * brand hue, `theme` the ThemeType name. All optional: no arguments gives the
 * concept default (hue 190).
 */
export function brandPalette(opts: {
  theme?: string
  hue?: number
  shimmer?: { primary: string; secondary: string; accent: string }
} = {}): Palette {
  const { theme, hue = 190, shimmer } = opts
  if (shimmer) {
    const triple: Palette = [shimmer.primary, shimmer.secondary, shimmer.accent]
    const spread = hueSpread(triple)
    if (spread !== null && spread >= MIN_SPREAD) return triple
  }
  const [d2, d3] = (theme && THEME_OFFSETS[theme]) || DEFAULT_OFFSETS
  return paletteFromHue(hue, d2, d3)
}

/**
 * A colour along the trail. `t` runs 0 (head) -> 1 (tail): head -> body for
 * 0..0.5, body -> tail for 0.5..1, hue by the shortest way round.
 */
export function makePaletteSampler(palette: Palette): (t: number, a?: number) => string {
  const fallback: Hsl = { h: 190, s: 90, l: 60 }
  const [a, b, c] = palette.map((x) => parseColor(x) ?? fallback)
  const mix = (p: Hsl, q: Hsl, k: number): Hsl => {
    let dh = q.h - p.h
    if (dh > 180) dh -= 360
    if (dh < -180) dh += 360
    return { h: norm(p.h + dh * k), s: p.s + (q.s - p.s) * k, l: p.l + (q.l - p.l) * k }
  }
  return (t, alpha) => {
    const k = Math.min(1, Math.max(0, t))
    const x = k < 0.5 ? mix(a, b, k * 2) : mix(b, c, (k - 0.5) * 2)
    return hslStr(x.h, x.s, x.l, alpha)
  }
}
