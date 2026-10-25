"use client"

/**
 * The Memory surface of the dashboard (docs/Design/Memory-Cortex/MEMORY-SURFACE-BUILD.md): the cortex, the
 * timeline, the artifacts and the Oracle of IRIS's memory (data/memory.db), drawn by the scene engine ported from
 * the validated mockup (lib/memory/scene/engine.ts).
 *
 * The engine owns its canvas and HUD inside the host box. This component decides WHAT it draws and WHEN:
 *   - the memory model comes from the read API (GET /api/memory/snapshot, read-only); while it loads the surface
 *     says so, and when the backend does not answer it says "the memory is resting" with a retry - never a blank
 *     or black box, and never invented data (the synthetic memory is a development aid: ?memory=demo);
 *   - the engine is created once per model (three.js loads only when Memory opens) and disposed on unmount;
 *   - it draws only while it is the active surface and the page is visible (a hidden memory costs nothing);
 *   - its keys act only while it is active (the engine also ignores keys typed into any other field);
 *   - in the tilted, balanced wing the pointer cannot pick through the CSS 3D transform, so the surface shows a
 *     glance and one click asks for the dashboard spotlight (flat, full size) instead of picking wrongly.
 */

import React, { useCallback, useEffect, useRef, useState } from "react"
import type { MemoryEngine } from "@/lib/memory/scene/engine"
import { fetchMemorySnapshot, MemoryResting, searchMemory, takeMemoryFocus, type MemoryModel } from "@/lib/memory/api"

export interface MemorySurfaceProps {
  /** Memory is the surface on screen (and the dashboard is open). */
  isActive: boolean
  /** The wing is flat: spotlit, detached or on the phone. Picking is only exact when it is. */
  isFlat: boolean
  /** Ask for the dashboard spotlight (the wing becomes flat and full size). */
  onRequestSpotlight?: () => void
}

type Load = { kind: "loading" } | { kind: "ready"; model: MemoryModel | null } | { kind: "resting"; why: string }

const INK = "#d4ecf6", DIM = "#6c8796"
const LIVE_TYPES = new Set(["memory_event", "landmark_update", "oracle_decision"])
const LINE: React.CSSProperties = { fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 11, letterSpacing: ".22em", textTransform: "lowercase" }

/** The synthetic memory draws only on request, in development (?memory=demo). */
const wantsDemo = () =>
  process.env.NODE_ENV !== "production" && typeof window !== "undefined" && new URLSearchParams(window.location.search).get("memory") === "demo"

export function MemorySurface({ isActive, isFlat, onRequestSpotlight }: MemorySurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<MemoryEngine | null>(null)
  const [load, setLoad] = useState<Load>(() => (wantsDemo() ? { kind: "ready", model: null } : { kind: "loading" }))
  const [failed, setFailed] = useState<string | null>(null)
  const [hidden, setHidden] = useState(false)
  const [ready, setReady] = useState(false)
  const [attempt, setAttempt] = useState(0)

  // The model: read once per attempt. A cold store on the hard disk can take many seconds on the first read.
  useEffect(() => {
    if (wantsDemo()) return
    const ac = new AbortController()
    setLoad({ kind: "loading" })
    fetchMemorySnapshot({ signal: ac.signal })
      .then((model) => setLoad({ kind: "ready", model }))
      .catch((e) => {
        if (ac.signal.aborted) return
        console.warn("[MemorySurface] the memory did not answer:", e)
        setLoad({ kind: "resting", why: e instanceof MemoryResting ? e.message : "the memory could not be read" })
      })
    return () => ac.abort()
  }, [attempt])

  // The scene: created once the model is here; disposed on unmount or when a new model replaces it.
  const model = load.kind === "ready" ? load.model : undefined
  useEffect(() => {
    if (model === undefined) return
    let cancelled = false
    ;(async () => {
      try {
        const { createMemoryEngine } = await import("@/lib/memory/scene/engine")
        if (cancelled || !hostRef.current) return
        const t0 = performance.now()
        engineRef.current = createMemoryEngine(hostRef.current, {
          data: model ?? undefined,
          search: model ? searchMemory : undefined, // the demo searches its own model
          reload: () => setAttempt((n) => n + 1),   // follow mode lost live messages: read the model again
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
      setReady(false)
    }
  }, [model])

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
    e.setFocus(isFlat)
    if (on) e.resume()
    else e.pause()
  }, [ready, isActive, hidden, isFlat, failed])

  // Deep links ("claim:<id>", "strand:<id>", "turn:<conv>:<turn>"): one that waited for the scene, then any that
  // arrive while the surface is on screen. A link to a thing not in this memory leaves the view where it is.
  useEffect(() => {
    if (!ready) return
    const go = (ref: string | null) => {
      if (ref && engineRef.current && !engineRef.current.focus(ref)) console.info(`[MemorySurface] not in this memory: ${ref}`)
    }
    go(takeMemoryFocus())
    const onFocus = () => go(takeMemoryFocus())
    window.addEventListener("iris:memory_focus", onFocus)
    return () => window.removeEventListener("iris:memory_focus", onFocus)
  }, [ready])

  // Follow mode: the backend's live memory taps (memory_event, landmark_update, oracle_decision) reach the engine,
  // which plays them on the real memory only, and only while follow is on (the engine keeps that toggle).
  useEffect(() => {
    if (!ready) return
    const onWs = (ev: Event) => {
      const d = (ev as CustomEvent).detail
      if (d && LIVE_TYPES.has(d.type)) engineRef.current?.live(d)
    }
    window.addEventListener("iris:ws_message", onWs)
    return () => window.removeEventListener("iris:ws_message", onWs)
  }, [ready])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  const centre: React.CSSProperties = { position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", background: "#020306" }}>
      <div ref={hostRef} style={{ position: "absolute", inset: 0 }} />
      {load.kind === "loading" && (
        <div style={centre} aria-live="polite">
          <span style={{ ...LINE, color: INK, textShadow: "0 0 12px rgba(0,212,255,.45)" }}>the memory is assembling</span>
          <span style={{ ...LINE, color: DIM, fontSize: 10, letterSpacing: ".08em" }}>reading data/memory.db — the first read after a start can take a while</span>
        </div>
      )}
      {load.kind === "resting" && (
        <div style={centre} role="status">
          <span style={{ ...LINE, color: INK }}>the memory is resting</span>
          <span style={{ ...LINE, color: DIM, fontSize: 10, letterSpacing: ".08em" }}>{load.why}</span>
          <button type="button" onClick={retry} style={{ ...LINE, color: INK, background: "transparent", border: `1px solid rgba(212,236,246,.25)`, borderRadius: 4, padding: "6px 14px", cursor: "pointer" }}>
            try again
          </button>
        </div>
      )}
      {failed && (
        <div style={{ ...centre, color: DIM, fontSize: 12 }}>{failed}</div>
      )}
      {load.kind === "ready" && !isFlat && !failed && (
        // The tilted wing: a glance only. One click flattens the wing so every hover and click lands where it looks.
        <button
          type="button"
          onClick={onRequestSpotlight}
          style={{ position: "absolute", inset: 0, display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 64, background: "transparent", border: 0, cursor: "pointer" }}
          aria-label="Open the memory"
          title="Open the memory"
        >
          <span style={{ ...LINE, color: INK, textShadow: "0 0 12px rgba(0,212,255,.6)" }}>open the memory</span>
        </button>
      )}
    </div>
  )
}

export default MemorySurface
