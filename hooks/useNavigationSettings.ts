"use client"

import { useCallback, useEffect } from "react"
import { useAnimationConfig } from "./useAnimationConfig"
import type { TransitionStyle, ExitStyle, SpeedMultiplier, StaggerDelay } from "@/types/navigation"

const STYLE_MAP: Record<string, TransitionStyle> = {
  "Radial Spin": "radial-spin",
  "Clockwork": "clockwork",
  "Slot Machine": "slot-machine",
  "Holographic": "holographic",
  "Liquid Morph": "liquid-morph",
  "Pure Fade": "pure-fade",
}

const EXIT_STYLE_MAP: Record<string, ExitStyle> = {
  "Symmetric": "symmetric",
  "Fade Out": "fade-out",
  "Fast Rewind": "fast-rewind",
}

const SPEED_MAP: Record<string, SpeedMultiplier> = {
  "0.5x (Slow)": 0.5,
  "0.75x": 0.75,
  "1.0x (Normal)": 1.0,
  "1.25x": 1.25,
  "1.5x": 1.5,
  "2.0x (Fast)": 2.0,
}

const STAGGER_MAP: Record<string, StaggerDelay> = {
  "None": 0,
  "50ms": 50,
  "100ms (Default)": 100,
  "150ms": 150,
}

export function useNavigationSettings() {
  const animConfig = useAnimationConfig()

  const handleFieldUpdate = useCallback((
    category: string,
    fieldId: string,
    value: string | number | boolean
  ) => {
    if (category !== "customize") return

    switch (fieldId) {
      case "nav_entry_style":
        if (typeof value === "string" && STYLE_MAP[value]) {
          animConfig.updateEntryStyle(STYLE_MAP[value])
        }
        break

      case "nav_exit_style":
        if (typeof value === "string" && EXIT_STYLE_MAP[value]) {
          animConfig.updateExitStyle(EXIT_STYLE_MAP[value])
        }
        break

      case "nav_speed":
        if (typeof value === "string" && SPEED_MAP[value]) {
          animConfig.updateSpeedMultiplier(SPEED_MAP[value])
        }
        break

      case "nav_stagger":
        if (typeof value === "string" && STAGGER_MAP[value]) {
          animConfig.updateStaggerDelay(STAGGER_MAP[value])
        }
        break
    }
  }, [animConfig])

  const getCurrentValues = useCallback(() => {
    const styleLabel = Object.entries(STYLE_MAP).find(
      ([, v]) => v === animConfig.config.entryStyle
    )?.[0] || "Radial Spin"

    const exitLabel = Object.entries(EXIT_STYLE_MAP).find(
      ([, v]) => v === animConfig.config.exitStyle
    )?.[0] || "Symmetric"

    const speedLabel = Object.entries(SPEED_MAP).find(
      ([, v]) => v === animConfig.config.speedMultiplier
    )?.[0] || "1.0x (Normal)"

    const staggerLabel = Object.entries(STAGGER_MAP).find(
      ([, v]) => v === animConfig.config.staggerDelay
    )?.[0] || "100ms (Default)"

    return {
      nav_entry_style: styleLabel,
      nav_exit_style: exitLabel,
      nav_speed: speedLabel,
      nav_stagger: staggerLabel,
    }
  }, [animConfig.config])

  return {
    handleFieldUpdate,
    getCurrentValues,
    config: animConfig.config,
    effectiveStyle: animConfig.effectiveStyle,
    prefersReducedMotion: animConfig.prefersReducedMotion,
    durations: animConfig.durations,
    easing: animConfig.easing,
    rotations: animConfig.rotations,
  }
}

export type UseNavigationSettingsReturn = ReturnType<typeof useNavigationSettings>
