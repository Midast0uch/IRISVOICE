/**
 * useLauncherMode — reads the launch mode set by iris-launcher.
 *
 * iris-launcher POSTs to /api/mode before the user opens IRIS.
 * This hook fetches the current mode so the UI can show/hide
 * developer-only panels (git integration, rebuild pipeline, diff review).
 *
 * Mode values:
 *   "personal"  — standard agent, curated skills
 *   "developer" — full source access, git integration, rebuild pipeline
 *   null        — not yet configured (launcher hasn't run)
 */

import { useState, useEffect } from "react"

export type LauncherMode = "personal" | "developer" | null

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

export function useLauncherMode(): {
  mode: LauncherMode
  isDeveloper: boolean
  isLoading: boolean
} {
  const [mode, setMode] = useState<LauncherMode>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Fetch once on mount
  useEffect(() => {
    let cancelled = false

    async function fetchMode() {
      try {
        const res = await fetch(`${BACKEND_URL}/api/mode`, {
          signal: AbortSignal.timeout(3000),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!cancelled) {
          setMode((data.mode as LauncherMode) ?? null)
        }
      } catch {
        // Backend not reachable or no mode set — default to personal
        if (!cancelled) setMode("personal")
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    fetchMode()
    return () => { cancelled = true }
  }, [])

  // React to real-time mode_changed WS events (broadcast from /api/mode POST)
  // so the UI updates instantly when the launcher switches modes mid-session.
  useEffect(() => {
    function onModeChanged(e: Event) {
      const detail = (e as CustomEvent<{ mode: string }>).detail
      if (detail?.mode === "personal" || detail?.mode === "developer") {
        setMode(detail.mode as LauncherMode)
        setIsLoading(false)
      }
    }
    window.addEventListener('iris:mode_changed', onModeChanged)
    return () => window.removeEventListener('iris:mode_changed', onModeChanged)
  }, [])

  return {
    mode,
    isDeveloper: mode === "developer",
    isLoading,
  }
}
