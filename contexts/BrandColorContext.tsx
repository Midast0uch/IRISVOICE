'use client'

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'

// === TYPES ===
export type ThemeType = 'aether' | 'ember' | 'aurum'

export interface BrandColorState {
  hue: number
  saturation: number
  lightness: number
}

export interface BrandColorContextType {
  brandColor: BrandColorState
  theme: ThemeType
  setHue: (hue: number) => void
  setSaturation: (saturation: number) => void
  setLightness: (lightness: number) => void
  setTheme: (theme: ThemeType) => void
  resetToThemeDefault: () => void
  getHSLString: () => string
  getAccessibleLightness: (backgroundLuminance: number) => number
}

// === DEFAULT VALUES ===
const DEFAULT_THEME: ThemeType = 'aether'

const THEME_DEFAULTS: Record<ThemeType, BrandColorState> = {
  aether: { hue: 210, saturation: 80, lightness: 55 }, // Cyan-Blue
  ember: { hue: 30, saturation: 70, lightness: 50 },   // Copper
  aurum: { hue: 45, saturation: 90, lightness: 55 },   // Gold
}

const STORAGE_KEY_BRAND = 'iris-brand-color'
const STORAGE_KEY_THEME = 'iris-preferred-theme'

// === CONTEXT ===
const BrandColorContext = createContext<BrandColorContextType | undefined>(undefined)

// === PROVIDER ===
export function BrandColorProvider({ children }: { children: React.ReactNode }) {
  // Initialize state from localStorage or defaults
  const [brandColor, setBrandColor] = useState<BrandColorState>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(STORAGE_KEY_BRAND)
      if (stored) {
        try {
          return JSON.parse(stored)
        } catch {
          // Fallback to default if parsing fails
        }
      }
    }
    return THEME_DEFAULTS[DEFAULT_THEME]
  })

  const [theme, setThemeState] = useState<ThemeType>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(STORAGE_KEY_THEME)
      if (stored && ['aether', 'ember', 'aurum'].includes(stored)) {
        return stored as ThemeType
      }
    }
    return DEFAULT_THEME
  })

  // Persist brand color to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_BRAND, JSON.stringify(brandColor))
  }, [brandColor])

  // Persist theme to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_THEME, theme)
  }, [theme])

  // Apply CSS variables when brand color changes
  useEffect(() => {
    const root = document.documentElement
    root.style.setProperty('--brand-hue', brandColor.hue.toString())
    root.style.setProperty('--brand-saturation', `${brandColor.saturation}%`)
    root.style.setProperty('--brand-lightness', `${brandColor.lightness}%`)
    
    // Apply theme-specific adjustments
    applyThemeAdjustments(theme, brandColor)
  }, [brandColor, theme])

  // Apply theme data attribute
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const setHue = useCallback((hue: number) => {
    setBrandColor(prev => ({ ...prev, hue: Math.max(0, Math.min(360, hue)) }))
  }, [])

  const setSaturation = useCallback((saturation: number) => {
    setBrandColor(prev => ({ ...prev, saturation: Math.max(0, Math.min(100, saturation)) }))
  }, [])

  const setLightness = useCallback((lightness: number) => {
    setBrandColor(prev => ({ ...prev, lightness: Math.max(0, Math.min(100, lightness)) }))
  }, [])

  const setTheme = useCallback((newTheme: ThemeType) => {
    setThemeState(newTheme)
    // Optionally adjust brand color to theme default (user preference)
    // For now, we keep the hue but may adjust saturation/lightness
  }, [])

  const resetToThemeDefault = useCallback(() => {
    setBrandColor(THEME_DEFAULTS[theme])
  }, [theme])

  const getHSLString = useCallback(() => {
    return `hsl(${brandColor.hue}, ${brandColor.saturation}%, ${brandColor.lightness}%)`
  }, [brandColor])

  // Calculate accessible lightness based on contrast requirements
  const getAccessibleLightness = useCallback((backgroundLuminance: number): number => {
    // WCAG AA requires 4.5:1 for normal text, 3:1 for large text
    // Simplified calculation - ensure sufficient contrast
    const targetContrast = 4.5
    const currentLightness = brandColor.lightness
    
    // If background is dark (low luminance), we need lighter text
    // If background is light (high luminance), we need darker text
    if (backgroundLuminance < 0.5) {
      // Dark background - ensure lightness is high enough
      return Math.max(currentLightness, 60)
    } else {
      // Light background - ensure lightness is low enough
      return Math.min(currentLightness, 40)
    }
  }, [brandColor.lightness])

  const value = useMemo(() => ({
    brandColor,
    theme,
    setHue,
    setSaturation,
    setLightness,
    setTheme,
    resetToThemeDefault,
    getHSLString,
    getAccessibleLightness,
  }), [brandColor, theme, setHue, setSaturation, setLightness, setTheme, resetToThemeDefault, getHSLString, getAccessibleLightness])

  return (
    <BrandColorContext.Provider value={value}>
      {children}
    </BrandColorContext.Provider>
  )
}

// === THEME-SPECIFIC ADJUSTMENTS ===
function applyThemeAdjustments(theme: ThemeType, brandColor: BrandColorState) {
  const root = document.documentElement
  
  switch (theme) {
    case 'aether':
      // Aether: Full vibrancy allowed
      root.style.setProperty('--aether-shimmer-start', `hsl(${brandColor.hue}, 90%, 60%)`)
      root.style.setProperty('--aether-shimmer-mid', `hsl(${(brandColor.hue + 30) % 360}, 80%, 65%)`)
      root.style.setProperty('--aether-shimmer-end', `hsl(${(brandColor.hue + 60) % 360}, 70%, 55%)`)
      break
      
    case 'ember':
      // Ember: Cap saturation at 70%, add warmth shift (+10°)
      const emberSat = Math.min(brandColor.saturation, 70)
      const emberHue = (brandColor.hue + 10) % 360
      root.style.setProperty('--ember-edge-glow', `hsl(${emberHue}, ${emberSat * 0.6}%, 45%)`)
      root.style.setProperty('--ember-edge-soft', `hsl(${emberHue}, ${emberSat * 0.5}%, 50%, 0.3)`)
      break
      
    case 'aurum':
      // Aurum: Heavy desaturation (40% of base) for metallic effect
      const aurumSat = brandColor.saturation * 0.4
      root.style.setProperty('--aurum-metal-primary', `hsl(${brandColor.hue}, ${aurumSat}%, 55%)`)
      root.style.setProperty('--aurum-metal-secondary', `hsl(${(brandColor.hue - 20 + 360) % 360}, ${aurumSat * 1.25}%, 45%)`)
      root.style.setProperty('--aurum-metal-highlight', `hsl(${brandColor.hue}, ${aurumSat * 1.5}%, 70%)`)
      break
  }
}

// === HOOK ===
export function useBrandColor() {
  const context = useContext(BrandColorContext)
  if (context === undefined) {
    throw new Error('useBrandColor must be used within a BrandColorProvider')
  }
  return context
}
