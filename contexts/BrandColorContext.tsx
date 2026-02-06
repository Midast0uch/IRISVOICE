'use client'

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'

// === TYPES ===
export type ThemeType = 'aether' | 'ember' | 'aurum' | 'verdant'

// Floating orb configuration
export interface FloatingOrb {
  color: string
  size: number
  blur: number
  x: number
  y: number
}

// Complete theme configuration for Prism Glass UI
export interface ThemeConfig {
  name: string
  description: string
  mood: string
  // Base HSL
  hue: number
  saturation: number
  lightness: number
  // Gradient backgrounds
  gradient: {
    from: string
    to: string
    angle: number
  }
  // Shimmer border colors
  shimmer: {
    primary: string
    secondary: string
    accent: string
  }
  // Floating orbs (null for Verdant)
  orbs: FloatingOrb[] | null
  // Typography
  text: {
    primary: string
    secondary: string
  }
  // Glass specifications
  glass: {
    opacity: number
    blur: number
    borderOpacity: number
  }
  // Outer glow
  glow: {
    color: string
    opacity: number
    blur: number
  }
}

export interface BrandColorState {
  hue: number
  saturation: number
  lightness: number
}

export interface BrandColorContextType {
  brandColor: BrandColorState
  theme: ThemeType
  isMounted: boolean
  setHue: (hue: number) => void
  setSaturation: (saturation: number) => void
  setLightness: (lightness: number) => void
  setTheme: (theme: ThemeType) => void
  resetToThemeDefault: () => void
  getHSLString: () => string
  getAccessibleLightness: (backgroundLuminance: number) => number
  getThemeConfig: () => ThemeConfig
}

// === DEFAULT VALUES ===
const DEFAULT_THEME: ThemeType = 'aether'

// Basic HSL defaults (kept for backwards compatibility)
const THEME_DEFAULTS: Record<ThemeType, BrandColorState> = {
  aether: { hue: 210, saturation: 40, lightness: 55 }, // Cyan-Blue (reduced saturation)
  ember: { hue: 30, saturation: 70, lightness: 50 },   // Copper/Orange
  aurum: { hue: 45, saturation: 90, lightness: 55 },   // Gold
  verdant: { hue: 145, saturation: 80, lightness: 45 }, // Forest Green
}

// Complete Prism Glass theme specifications
export const PRISM_THEMES: Record<ThemeType, ThemeConfig> = {
  aether: {
    name: 'Aether',
    description: 'Cool, ethereal blues/purples',
    mood: 'Calm, airy, futuristic',
    hue: 210,
    saturation: 40,
    lightness: 55,
    gradient: {
      from: 'hsl(220, 40%, 15%)',
      to: 'hsl(190, 40%, 55%)',
      angle: 135
    },
    shimmer: {
      primary: 'hsl(200, 40%, 70%)',
      secondary: 'hsl(260, 40%, 65%)',
      accent: 'hsl(180, 40%, 60%)'
    },
    orbs: [
      { color: 'hsl(200, 100%, 60%)', size: 80, blur: 40, x: -30, y: -20 },
      { color: 'hsl(260, 80%, 65%)', size: 60, blur: 30, x: 40, y: 30 },
      { color: 'hsl(180, 90%, 55%)', size: 50, blur: 25, x: -20, y: 40 }
    ],
    text: {
      primary: 'rgba(255, 255, 255, 0.95)',
      secondary: 'rgba(255, 255, 255, 0.70)'
    },
    glass: {
      opacity: 0.18,
      blur: 24,
      borderOpacity: 0.15
    },
    glow: {
      color: '#00c8ff',
      opacity: 0.3,
      blur: 12
    }
  },
  ember: {
    name: 'Ember',
    description: 'Warm oranges/reds/pinks',
    mood: 'Energetic, sunset, passionate',
    hue: 30,
    saturation: 70,
    lightness: 50,
    gradient: {
      from: 'hsl(350, 70%, 20%)',
      to: 'hsl(25, 90%, 55%)',
      angle: 135
    },
    shimmer: {
      primary: 'hsl(25, 100%, 60%)',
      secondary: 'hsl(350, 80%, 55%)',
      accent: 'hsl(15, 100%, 65%)'
    },
    orbs: [
      { color: 'hsl(25, 100%, 55%)', size: 70, blur: 35, x: -25, y: -15 },
      { color: 'hsl(350, 80%, 60%)', size: 55, blur: 28, x: 35, y: 25 },
      { color: 'hsl(15, 100%, 60%)', size: 45, blur: 22, x: -15, y: 35 }
    ],
    text: {
      primary: 'rgba(255, 255, 255, 0.95)',
      secondary: 'rgba(255, 255, 255, 0.70)'
    },
    glass: {
      opacity: 0.17,
      blur: 24,
      borderOpacity: 0.15
    },
    glow: {
      color: '#ff6432',
      opacity: 0.35,
      blur: 12
    }
  },
  aurum: {
    name: 'Aurum',
    description: 'Rich golds/ambers/yellows',
    mood: 'Luxurious, warm, premium',
    hue: 45,
    saturation: 90,
    lightness: 55,
    gradient: {
      from: '#523a15', // Converted from hsl(35, 60%, 20%)
      to: '#d4a31c',   // Converted from hsl(50, 95%, 60%)
      angle: 135
    },
    shimmer: {
      primary: '#f5c842',   // Converted from hsl(45, 100%, 65%) - brighter for visibility
      secondary: '#f0e62e', // Converted from hsl(55, 90%, 70%) - brighter for visibility
      accent: '#d9a31a'     // Converted from hsl(35, 80%, 60%)
    },
    orbs: [
      { color: '#f0c020', size: 75, blur: 38, x: -20, y: -25 }, // Brighter gold
      { color: '#ebe026', size: 58, blur: 32, x: 30, y: 20 },  // Brighter yellow
      { color: '#e6c228', size: 48, blur: 24, x: -25, y: 30 }  // Brighter amber
    ],
    text: {
      primary: 'rgba(255, 255, 255, 0.95)',
      secondary: 'rgba(255, 255, 255, 0.75)'
    },
    glass: {
      opacity: 0.20,  // Increased from 0.16 for better visibility
      blur: 24,
      borderOpacity: 0.18 // Increased from 0.12
    },
    glow: {
      color: '#ffc832',
      opacity: 0.40, // Increased from 0.32 for better visibility
      blur: 12
    }
  },
  verdant: {
    name: 'Verdant',
    description: 'Vibrant emerald green with glass feel',
    mood: 'Natural, fresh, organic',
    hue: 145,
    saturation: 100,
    lightness: 55,
    gradient: {
      from: '#064d1a',  // Deep forest green
      to: '#0d8f2e',    // Bright emerald
      angle: 135
    },
    shimmer: {
      primary: '#00ff77',   // Bright neon green
      secondary: '#00dd55', // Vivid green
      accent: '#00ff99'     // Light mint
    },
    orbs: null, // No floating orbs for Verdant - clean glass only
    text: {
      primary: 'rgba(255, 255, 255, 0.95)',
      secondary: 'rgba(255, 255, 255, 0.85)'
    },
    glass: {
      opacity: 0.25,  // More visible
      blur: 24,
      borderOpacity: 0.30 // Stronger border
    },
    glow: {
      color: '#00ff77', // Bright green glow
      opacity: 0.60,    // Stronger glow
      blur: 18
    }
  }
}

const STORAGE_KEY_BRAND = 'iris-brand-color'
const STORAGE_KEY_THEME = 'iris-preferred-theme'

// === CONTEXT ===
const BrandColorContext = createContext<BrandColorContextType | undefined>(undefined)

// === PROVIDER ===
export function BrandColorProvider({ children }: { children: React.ReactNode }) {
  // Start with default values for SSR consistency
  const [brandColor, setBrandColor] = useState<BrandColorState>(THEME_DEFAULTS[DEFAULT_THEME])
  const [theme, setThemeState] = useState<ThemeType>(DEFAULT_THEME)
  const [isMounted, setIsMounted] = useState(false)

  // After mount, load from localStorage to avoid hydration mismatch
  useEffect(() => {
    const storedBrand = localStorage.getItem(STORAGE_KEY_BRAND)
    const storedTheme = localStorage.getItem(STORAGE_KEY_THEME)
    
    // Determine which theme to use
    const themeToUse = (storedTheme && ['aether', 'ember', 'aurum', 'verdant'].includes(storedTheme)) 
      ? storedTheme as ThemeType 
      : DEFAULT_THEME
    
    // Get expected defaults for this theme
    const expectedDefaults = THEME_DEFAULTS[themeToUse]
    
    if (storedBrand) {
      try {
        const parsed = JSON.parse(storedBrand)
        
        // Validate: Check if stored values match expected theme defaults (within tolerance)
        const hueDiff = Math.abs(parsed.hue - expectedDefaults.hue)
        const satDiff = Math.abs(parsed.saturation - expectedDefaults.saturation)
        const lightDiff = Math.abs(parsed.lightness - expectedDefaults.lightness)
        
        // If values are very different from expected, use defaults instead
        if (hueDiff > 30 || satDiff > 20 || lightDiff > 20) {
          setBrandColor(expectedDefaults)
        } else {
          setBrandColor(parsed)
        }
      } catch {
        // Keep default if parsing fails
        setBrandColor(expectedDefaults)
      }
    }
    
    if (storedTheme && ['aether', 'ember', 'aurum', 'verdant'].includes(storedTheme)) {
      setThemeState(storedTheme as ThemeType)
    }
    
    setIsMounted(true)
  }, [])

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
    // Update brand color to theme default so colors actually change
    setBrandColor(THEME_DEFAULTS[newTheme])
    // Clear localStorage for brand color to prevent override
    localStorage.removeItem(STORAGE_KEY_BRAND)
  }, [])

  const resetToThemeDefault = useCallback(() => {
    setBrandColor(THEME_DEFAULTS[theme])
    localStorage.removeItem(STORAGE_KEY_BRAND)
  }, [theme])

  const getHSLString = useCallback(() => {
    return `hsl(${brandColor.hue}, ${brandColor.saturation}%, ${brandColor.lightness}%)`
  }, [brandColor])

  const getThemeConfig = useCallback(() => {
    return PRISM_THEMES[theme]
  }, [theme])
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
    isMounted,
    setHue,
    setSaturation,
    setLightness,
    setTheme,
    resetToThemeDefault,
    getHSLString,
    getAccessibleLightness,
    getThemeConfig,
  }), [brandColor, theme, isMounted, setHue, setSaturation, setLightness, setTheme, resetToThemeDefault, getHSLString, getAccessibleLightness, getThemeConfig])

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
