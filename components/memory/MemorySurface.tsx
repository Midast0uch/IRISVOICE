"use client"

/**
 * The Memory surface of the dashboard (docs/Design/Memory-Cortex/MEMORY-SURFACE-BUILD.md): the cortex, the
 * timeline, the artifacts and the Oracle of IRIS's memory (data/memory.db), drawn by the scene engine ported from
 * the validated mockup (lib/memory/scene/engine.ts).
 *
 * The engine owns its canvas and HUD inside the host box. This component only decides WHEN it draws:
 *   - it is created once per mount (dynamic import: three.js never runs on the server) and disposed on unmount;
 *   - it draws only while it is the active surface and the page is visible (a hidden memory costs nothing);
 *   - its keys act only while it is active (the engine also ignores keys typed into any other field);
 *   - in the tilted, balanced wing the pointer cannot pick through the CSS 3D transform, so the surface shows a
 *     glance and one click asks for the dashboard spotlight (flat, full size) instead of picking wrongly.
 */

import React, { useEffect, useRef, useState } from "react"
import type { MemoryEngine } from "@/lib/memory/scene/engine"

export interface MemorySurfaceProps {
  /** Memory is the surface on screen (and the dashboard is open). */
  isActive: boolean
  /** The wing is flat: spotlit, detached or on the phone. Picking is only exact when it is. */
  isFlat: boolean
  /** Ask for the dashboard spotlight (the wing becomes flat and full size). */
  onRequestSpotlight?: () => void
}

export function MemorySurface({ isActive, isFlat, onRequestSpotlight }: MemorySurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<MemoryEngine | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [hidden, setHidden] = useState(false)
  const [ready, setReady] = useState(false)

  // Create once; dispose on unmount (every GPU resource, every window listener).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const { createMemoryEngine } = await import("@/lib/memory/scene/engine")
        if (cancelled || !hostRef.current) return
        const t0 = performance.now()
        engineRef.current = createMemoryEngine(hostRef.current, {
          onError: (e) => {
            console.warn("[MemorySurface] the scene stopped:", e)
            setFailed("The memory view needs WebGL2, and it is not available here.")
          },
        })
        console.info(`[MemorySurface] scene built in ${Math.round(performance.now() - t0)} ms`)
        if (process.env.NODE_ENV !== "production") (window as any).__irisMemory = engineRef.current // inspection in development only
        setReady(true)
      } catch (e) {
        console.warn("[MemorySurface] the scene could not start:", e)
        if (!cancelled) setFailed("The memory view could not start.")
      }
    })()
    return () => {
      cancelled = true
      engineRef.current?.dispose()
      engineRef.current = null
    }
  }, [])

  // The page's own visibility (a minimised window, another app in front).
  useEffect(() => {
    const onVis = () => setHidden(document.hidden)
    onVis()
    document.addEventListener("visibilitychange", onVis)
    return () => document.removeEventListener("visibilitychange", onVis)
  }, [])

  // Draw and listen only while it is the surface on screen.
  useEffect(() => {
    const e = engineRef.current
    if (!e) return
    const on = isActive && !hidden
    e.setActive(on && isFlat)
    if (on) e.resume()
    else e.pause()
  }, [ready, isActive, hidden, isFlat, failed])

  return (
    <div className="relative w-full h-full" style={{ background: "#020306" }}>
      <div ref={hostRef} className="absolute inset-0" />
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center text-xs" style={{ color: "#6c8796" }}>
          {failed}
        </div>
      )}
      {!isFlat && !failed && (
        // The tilted wing: a glance only. One click flattens the wing so every hover and click lands where it looks.
        <button
          type="button"
          onClick={onRequestSpotlight}
          className="absolute inset-0 flex items-end justify-center pb-16"
          style={{ background: "transparent", border: 0, cursor: "pointer" }}
          aria-label="Open the memory"
          title="Open the memory"
        >
          <span
            className="text-[11px] tracking-[.22em] lowercase"
            style={{ color: "#d4ecf6", textShadow: "0 0 12px rgba(0,212,255,.6)" }}
          >
            open the memory
          </span>
        </button>
      )}
    </div>
  )
}

export default MemorySurface
