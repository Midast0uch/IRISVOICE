"use client"

import { useCallback, useEffect, useState } from "react"
import type { 
  NavigationConfig, 
  TransitionStyle, 
  ExitStyle, 
  SpeedMultiplier, 
  StaggerDelay 
} from "@/types/navigation"
import { DEFAULT_NAV_CONFIG, CONFIG_STORAGE_KEY } from "@/types/navigation"

interface AnimationDurations {
  entry: number
  exit: number
  stagger: number
}

interface TransitionStyleConfig {
  name: TransitionStyle
  displayName: string
  description: string
  baseDuration: number
  exitDurationRatio: number
}

export const TRANSITION_STYLES: TransitionStyleConfig[] = [
  {
    name: 'radial-spin',
    displayName: 'Radial Spin',
    description: 'Spiral out with rotations (default)',
    baseDuration: 1500,
    exitDurationRatio: 0.53,
  },
  {
    name: 'clockwork',
    displayName: 'Clockwork',
    description: 'Gear-stepped mechanical expansion',
    baseDuration: 1200,
    exitDurationRatio: 0.5,
  },
  {
    name: 'slot-machine',
    displayName: 'Slot Machine',
    description: 'Blur spin with radial lock-in',
    baseDuration: 1600,
    exitDurationRatio: 0.5,
  },
  {
    name: 'holographic',
    displayName: 'Holographic',
    description: 'Wireframe to glitch to stabilize',
    baseDuration: 1800,
    exitDurationRatio: 0.56,
  },
  {
    name: 'liquid-morph',
    displayName: 'Liquid Morph',
    description: 'Organic blob splitting',
    baseDuration: 2000,
    exitDurationRatio: 0.6,
  },
  {
    name: 'pure-fade',
    displayName: 'Pure Fade',
    description: 'Simple opacity transition (accessibility)',
    baseDuration: 300,
    exitDurationRatio: 0.67,
  },
]

export const EXIT_STYLES: { name: ExitStyle; displayName: string; description: string }[] = [
  { name: 'symmetric', displayName: 'Symmetric', description: 'Reverse of entry animation' },
  { name: 'fade-out', displayName: 'Fade Out', description: 'Quick fade regardless of entry' },
  { name: 'fast-rewind', displayName: 'Fast Rewind', description: 'Entry at 2x speed backward' },
]

export const SPEED_OPTIONS: { value: SpeedMultiplier; label: string }[] = [
  { value: 0.5, label: '0.5x (Slow)' },
  { value: 0.75, label: '0.75x' },
  { value: 1.0, label: '1.0x (Normal)' },
  { value: 1.25, label: '1.25x' },
  { value: 1.5, label: '1.5x' },
  { value: 2.0, label: '2.0x (Fast)' },
]

export const STAGGER_OPTIONS: { value: StaggerDelay; label: string }[] = [
  { value: 0, label: 'None' },
  { value: 50, label: '50ms' },
  { value: 100, label: '100ms (Default)' },
  { value: 150, label: '150ms' },
]

function getStyleConfig(style: TransitionStyle): TransitionStyleConfig {
  return TRANSITION_STYLES.find(s => s.name === style) || TRANSITION_STYLES[0]
}

export function useAnimationConfig() {
  const [config, setConfig] = useState<NavigationConfig>(DEFAULT_NAV_CONFIG)
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false)

  useEffect(() => {
    try {
      const saved = localStorage.getItem(CONFIG_STORAGE_KEY)
      if (saved) {
        setConfig({ ...DEFAULT_NAV_CONFIG, ...JSON.parse(saved) })
      }
    } catch (e) {
      console.warn('[useAnimationConfig] Failed to load config:', e)
    }

    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    setPrefersReducedMotion(mediaQuery.matches)

    const handler = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches)
    mediaQuery.addEventListener('change', handler)
    return () => mediaQuery.removeEventListener('change', handler)
  }, [])

  const saveConfig = useCallback((newConfig: NavigationConfig) => {
    setConfig(newConfig)
    try {
      localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(newConfig))
    } catch (e) {
      console.warn('[useAnimationConfig] Failed to save config:', e)
    }
  }, [])

  const updateEntryStyle = useCallback((style: TransitionStyle) => {
    saveConfig({ ...config, entryStyle: style })
  }, [config, saveConfig])

  const updateExitStyle = useCallback((style: ExitStyle) => {
    saveConfig({ ...config, exitStyle: style })
  }, [config, saveConfig])

  const updateSpeedMultiplier = useCallback((speed: SpeedMultiplier) => {
    saveConfig({ ...config, speedMultiplier: speed })
  }, [config, saveConfig])

  const updateStaggerDelay = useCallback((delay: StaggerDelay) => {
    saveConfig({ ...config, staggerDelay: delay })
  }, [config, saveConfig])

  const effectiveStyle = prefersReducedMotion ? 'pure-fade' : config.entryStyle
  const styleConfig = getStyleConfig(effectiveStyle)

  const getDurations = useCallback((): AnimationDurations => {
    const baseDuration = styleConfig.baseDuration / config.speedMultiplier
    
    let exitDuration: number
    switch (config.exitStyle) {
      case 'fade-out':
        exitDuration = 300 / config.speedMultiplier
        break
      case 'fast-rewind':
        exitDuration = baseDuration / 2
        break
      case 'symmetric':
      default:
        exitDuration = baseDuration * styleConfig.exitDurationRatio
        break
    }

    return {
      entry: baseDuration,
      exit: exitDuration,
      stagger: config.staggerDelay / config.speedMultiplier,
    }
  }, [config, styleConfig])

  const getEasing = useCallback((): readonly number[] => {
    switch (effectiveStyle) {
      case 'clockwork':
        return [0.25, 0.1, 0.25, 1] as const
      case 'slot-machine':
        return [0.68, -0.55, 0.265, 1.55] as const
      case 'holographic':
        return [0.4, 0, 0.2, 1] as const
      case 'liquid-morph':
        return [0.34, 1.56, 0.64, 1] as const
      case 'pure-fade':
        return [0.4, 0, 0.2, 1] as const
      case 'radial-spin':
      default:
        return [0.4, 0, 0.2, 1] as const
    }
  }, [effectiveStyle])

  const getRotations = useCallback((): number => {
    switch (effectiveStyle) {
      case 'radial-spin':
        return 2
      case 'clockwork':
        return 0.25
      case 'slot-machine':
        return 0
      case 'holographic':
        return 0
      case 'liquid-morph':
        return 0
      case 'pure-fade':
        return 0
      default:
        return 2
    }
  }, [effectiveStyle])

  return {
    config,
    effectiveStyle,
    prefersReducedMotion,
    durations: getDurations(),
    easing: getEasing(),
    rotations: getRotations(),
    updateEntryStyle,
    updateExitStyle,
    updateSpeedMultiplier,
    updateStaggerDelay,
    saveConfig,
  }
}

export type UseAnimationConfigReturn = ReturnType<typeof useAnimationConfig>
