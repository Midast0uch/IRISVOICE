"use client"

import { useState, useEffect, useRef } from "react"

const OVERRIDE_KEY = "iris_mode_override"
const WIDGET_MODE_KEY = "iris-widget-mode"

interface LauncherMode {
  mode: string
  isDeveloper: boolean
}

export function useLauncherMode(): LauncherMode {
  const [mode, setMode] = useState<string>(() => {
    if (typeof window === "undefined") return "personal"

    const params = new URLSearchParams(window.location.search)

    // Priority 1: URL param (?mode=personal|developer) — set by launcher
    // Check BEFORE ?remote=1 so explicit ?mode=developer can override remote default
    const urlMode = params.get("mode")
    if (urlMode === "developer" || urlMode === "personal") return urlMode

    // Priority 1b: Force personal mode for remote/mobile access (?remote=1)
    // when no explicit ?mode= is set — prevents backend from overriding to developer
    if (params.get("remote") === "1") return "personal"

    // Priority 2: localStorage override (for testing/developer console)
    const override = localStorage.getItem(OVERRIDE_KEY)
    if (override) return override

    // Priority 3: widget mode key (set by launcher via URL on first load)
    const widgetMode = localStorage.getItem(WIDGET_MODE_KEY)
    if (widgetMode === "developer" || widgetMode === "personal") return widgetMode

    return "personal"
  })

  // Track whether the mode was explicitly set via URL param — if so,
  // don't allow the async backend fetch to override it.
  const urlModeRef = useRef<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const urlMode = params.get("mode")
    if (urlMode === "developer" || urlMode === "personal") {
      // Explicit ?mode= param — backend should never override
      urlModeRef.current = urlMode
    } else if (params.get("remote") === "1") {
      // ?remote=1 without explicit mode — force personal, prevent backend override
      urlModeRef.current = "personal"
    } else {
      urlModeRef.current = null
    }
  }, [])

  useEffect(() => {
    // If mode was explicitly set via URL param, don't override with backend value
    if (urlModeRef.current) return

    // Try fetching from backend API as authoritative source
    fetch("/api/mode")
      .then((res) => res.json())
      .then((data) => {
        if (data.mode === "developer" || data.mode === "personal") {
          setMode(data.mode)
        }
      })
      .catch(() => {
        // Backend unavailable — keep the URL/localStorage mode
      })
  }, [])

  return { mode, isDeveloper: mode === "developer" }
}

/** Call `setModeOverride("developer")` in browser console to force developer mode. */
export function setModeOverride(m: string) {
  localStorage.setItem(OVERRIDE_KEY, m)
}

/** Call `clearModeOverride()` to remove the override. */
export function clearModeOverride() {
  localStorage.removeItem(OVERRIDE_KEY)
}
