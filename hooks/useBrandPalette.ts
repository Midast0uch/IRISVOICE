'use client'

import { createContext, useContext, useMemo, type ContextType } from 'react'
import { BrandColorContext } from '@/contexts/BrandColorContext'
import { brandPalette, type Palette } from '@/lib/brandPalette'

// Module level, so a stand-in of BrandColorContext that binds only useBrandColor
// (many component tests mock the module that way) still renders the default.
const NoBrand = createContext<ContextType<typeof BrandColorContext> | undefined>(undefined)

/**
 * The three brand hues (head, body, tail) for the active theme. Works without a
 * BrandColorProvider (tests, detached panes): it then returns the concept default.
 */
export function useBrandPalette(): Palette {
  const ctx = useContext(BrandColorContext ?? NoBrand)
  const cfg = ctx?.getThemeConfig()
  const theme = ctx?.theme
  const hue = cfg?.hue
  const p = cfg?.shimmer?.primary, s = cfg?.shimmer?.secondary, a = cfg?.shimmer?.accent
  return useMemo(
    () => brandPalette({ theme, hue, shimmer: p && s && a ? { primary: p, secondary: s, accent: a } : undefined }),
    [theme, hue, p, s, a],
  )
}
