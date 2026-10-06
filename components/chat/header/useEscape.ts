"use client"

import { useEffect } from "react"

/**
 * While `active`, Escape runs `onEscape` and goes no further. The capture phase
 * on window runs before chat-view's own Escape handler, which would close the
 * whole chat wing.
 */
export function useEscape(active: boolean, onEscape: () => void) {
  useEffect(() => {
    if (!active) return
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      e.stopPropagation()
      onEscape()
    }
    window.addEventListener("keydown", h, true)
    return () => window.removeEventListener("keydown", h, true)
  }, [active, onEscape])
}
