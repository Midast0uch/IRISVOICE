"use client"

import { useState, useEffect } from "react"

const OVERRIDE_KEY = "iris_mode_override"

interface LauncherMode {
  mode: string
  isDeveloper: boolean
}

export function useLauncherMode(): LauncherMode {
  const [mode, setMode] = useState<string>(() => {
    // Allow localStorage override for testing/dev verification
    if (typeof window !== "undefined") {
      const override = localStorage.getItem(OVERRIDE_KEY)
      if (override) return override
    }
    return "personal"
  })

  useEffect(() => {
    fetch("/api/mode")
      .then((res) => res.json())
      .then((data) => setMode(data.mode || "personal"))
      .catch(() => setMode("personal"))
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
