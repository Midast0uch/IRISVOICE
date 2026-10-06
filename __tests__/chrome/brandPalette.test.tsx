import React from 'react'
import { renderHook, act } from '@testing-library/react'
import { brandPalette, paletteFromHue, makePaletteSampler, parseColor, withAlpha } from '@/lib/brandPalette'
import { BrandColorProvider, BrandColorContext, useBrandColor } from '@/contexts/BrandColorContext'
import { generateAetherShimmers } from '@/lib/brand-colors'
import { useBrandPalette } from '@/hooks/useBrandPalette'

const hueOf = (c: string) => (parseColor(c) as { h: number }).h
const spread = (p: readonly string[]) => {
  const base = hueOf(p[0])
  return Math.max(...p.map((c) => { const d = Math.abs(hueOf(c) - base); return Math.min(d, 360 - d) }))
}

describe('brandPalette', () => {
  it('no arguments gives the concept default around hue 190 (+25, -40)', () => {
    const p = brandPalette()
    expect(hueOf(p[0])).toBeCloseTo(190, 0)
    expect(hueOf(p[1])).toBeCloseTo(215, 0)
    expect(hueOf(p[2])).toBeCloseTo(150, 0)
    expect(p).toEqual(paletteFromHue(190))
  })

  it('uses the theme shimmer when its three hues differ (aether: hue, +30, +60)', () => {
    const g = generateAetherShimmers(190)
    const shimmer = { primary: g.start, secondary: g.mid, accent: g.end }
    expect(brandPalette({ theme: 'aether', hue: 190, shimmer })).toEqual([g.start, g.mid, g.end])
  })

  it('falls back to the concept offsets when the shimmer is one hue (verdant)', () => {
    const shimmer = { primary: 'hsl(145, 100%, 60%)', secondary: 'hsl(145, 80%, 50%)', accent: 'hsl(145, 90%, 70%)' }
    const p = brandPalette({ theme: 'verdant', hue: 145, shimmer })
    expect(hueOf(p[1])).toBeCloseTo(190, 0) // 145 + 45
    expect(hueOf(p[2])).toBeCloseTo(90, 0)  // 145 - 55
  })

  // The real provider, every theme: the palette is never one flat hue.
  it.each(['aether', 'ember', 'aurum', 'verdant'] as const)('%s palette from the real provider has three hues', (theme) => {
    const { result } = renderHook(() => ({ p: useBrandPalette(), c: useBrandColor() }), { wrapper: BrandColorProvider })
    act(() => result.current.c.setTheme(theme))
    expect(result.current.c.theme).toBe(theme)
    expect(spread(result.current.p)).toBeGreaterThanOrEqual(20)
  })

  it('the sampler runs head -> body -> tail and parses hex, hsl and rgb', () => {
    const s = makePaletteSampler(['#ff0000', 'hsl(120, 100%, 50%)', 'rgb(0, 0, 255)'])
    expect(hueOf(s(0))).toBeCloseTo(0, 0)
    expect(hueOf(s(0.5))).toBeCloseTo(120, 0)
    expect(hueOf(s(1))).toBeCloseTo(240, 0)
    expect(s(0.25, 0.5)).toMatch(/^hsla\(/)
    expect(withAlpha('#00ff77', 0.2)).toMatch(/^hsla\(.*0\.2\)$/)
  })

  it('useBrandPalette returns the default without a provider and the shimmer with one', () => {
    expect(renderHook(() => useBrandPalette()).result.current).toEqual(brandPalette())
    const g = generateAetherShimmers(190)
    const cfg = { hue: 190, shimmer: { primary: g.start, secondary: g.mid, accent: g.end } }
    const ctx = { theme: 'aether', getThemeConfig: () => cfg } as never
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <BrandColorContext.Provider value={ctx}>{children}</BrandColorContext.Provider>
    )
    expect(renderHook(() => useBrandPalette(), { wrapper }).result.current).toEqual([g.start, g.mid, g.end])
  })
})
