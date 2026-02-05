'use client'

import { useEffect, useRef } from 'react'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'
import { interpolateHue, interpolateValue } from '@/lib/brand-colors'

interface ThemeTransition {
  from: ThemeType
  to: ThemeType
  progress: number
}

export function useThemeTransition(duration: number = 300) {
  const { theme, brandColor } = useBrandColor()
  const previousTheme = useRef<ThemeType>(theme)
  const transitionRef = useRef<ThemeTransition | null>(null)
  const animationRef = useRef<number | null>(null)

  useEffect(() => {
    if (previousTheme.current !== theme) {
      // Start transition
      const from = previousTheme.current
      const to = theme
      const startTime = performance.now()

      const animate = (currentTime: number) => {
        const elapsed = currentTime - startTime
        const progress = Math.min(elapsed / duration, 1)

        transitionRef.current = { from, to, progress }

        // Apply animated CSS variables during transition
        const root = document.documentElement
        
        // Get hue values for both themes (using stored defaults)
        const themeDefaults = {
          aether: 210,
          ember: 30,
          aurum: 45,
        }

        const fromHue = themeDefaults[from]
        const toHue = themeDefaults[to]
        const currentHue = interpolateHue(fromHue, toHue, progress)

        // Set transition variable
        root.style.setProperty('--theme-transition-progress', String(progress))
        root.style.setProperty('--theme-transition-hue', String(currentHue))

        if (progress < 1) {
          animationRef.current = requestAnimationFrame(animate)
        } else {
          // Transition complete
          transitionRef.current = null
          previousTheme.current = theme
          root.style.removeProperty('--theme-transition-progress')
          root.style.removeProperty('--theme-transition-hue')
        }
      }

      animationRef.current = requestAnimationFrame(animate)

      return () => {
        if (animationRef.current) {
          cancelAnimationFrame(animationRef.current)
        }
      }
    }
  }, [theme, duration, brandColor.hue])

  return {
    isTransitioning: transitionRef.current !== null,
    transitionProgress: transitionRef.current?.progress ?? 0,
  }
}

// Hook for smooth hue animation (for micro-adjustments)
export function useSmoothHue(targetHue: number, duration: number = 150) {
  const { brandColor, setHue } = useBrandColor()
  const startHueRef = useRef(brandColor.hue)
  const animationRef = useRef<number | null>(null)

  useEffect(() => {
    if (brandColor.hue !== targetHue && Math.abs(brandColor.hue - targetHue) < 180) {
      startHueRef.current = brandColor.hue
      const startTime = performance.now()

      const animate = (currentTime: number) => {
        const elapsed = currentTime - startTime
        const progress = Math.min(elapsed / duration, 1)
        
        // Easing function
        const eased = 1 - Math.pow(1 - progress, 3)
        
        const currentHue = interpolateHue(startHueRef.current, targetHue, eased)
        setHue(Math.round(currentHue))

        if (progress < 1) {
          animationRef.current = requestAnimationFrame(animate)
        }
      }

      animationRef.current = requestAnimationFrame(animate)

      return () => {
        if (animationRef.current) {
          cancelAnimationFrame(animationRef.current)
        }
      }
    }
  }, [targetHue, duration, setHue])
}

// CSS class generator for transition states
export function getTransitionClasses(isTransitioning: boolean): string {
  return isTransitioning 
    ? 'transition-colors duration-300 ease-out'
    : ''
}
