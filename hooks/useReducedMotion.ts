"use client"

import { useState, useEffect } from "react"

export function useReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false)

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)")
    setPrefersReducedMotion(mediaQuery.matches)

    const handler = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches)
    }

    mediaQuery.addEventListener("change", handler)
    return () => mediaQuery.removeEventListener("change", handler)
  }, [])

  return prefersReducedMotion
}

export function useAccessibleAnimationDuration(
  baseDuration: number,
  prefersReducedMotion: boolean
): number {
  return prefersReducedMotion ? 0 : baseDuration
}

export function getAccessibleTransitionStyle(prefersReducedMotion: boolean) {
  if (prefersReducedMotion) {
    return {
      transition: "none",
      animation: "none",
    }
  }
  return {}
}
