"use client"

/**
 * Vision Stage Simulator — /dev/vision-stage (specs/vision-browser-stage
 * REQ-12, T13). Developer-mode only surface that runs scripted agent-action
 * scenarios through the REAL iris:* event contract so the user can visually
 * sign off every animation/effect (AC4 checklist, persisted to localStorage).
 *
 * Guards: hidden behind useLauncherMode().isDeveloper; scenario buttons are
 * disabled while a LIVE crawl is active (REQ-12 edge case).
 */

import { useEffect, useMemo, useState } from "react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useLauncherMode } from "@/hooks/useLauncherMode"
import { useCrawlContext } from "@/hooks/CrawlProvider"
import { SCENARIOS, WIDE_FIXTURE_HTML } from "../../../simulator/scenarios"
import { runScenario, resetToIdle, type RunningScenario } from "../../../simulator/runner"
import {
  MESH_PREF_KEY,
  MESH_PREF_EVENT,
} from "../browser/BrowserNavigationOverlay"

const SIGNOFF_KEY = "iris-vision-stage-signoff-v1"

function loadSignoff(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(SIGNOFF_KEY) || "{}")
  } catch {
    return {}
  }
}

export function VisionStagePanel({
  collapsed = false,
  onToggleCollapse,
}: {
  /** Compact rail mode: chat stays interactive, RUN buttons stay clickable. */
  collapsed?: boolean
  onToggleCollapse?: () => void
}) {
  const { isDeveloper } = useLauncherMode()
  const { getThemeConfig } = useBrandColor()
  const { state: crawl } = useCrawlContext()
  const glowColor = getThemeConfig().glow.color || "#00d4ff"

  const [running, setRunning] = useState<string | null>(null)
  const [current, setCurrent] = useState<RunningScenario | null>(null)
  const [signoff, setSignoff] = useState<Record<string, boolean>>({})
  const [showFixture, setShowFixture] = useState(false)
  const [mesh, setMesh] = useState(true) // opt-out; the effect below confirms

  useEffect(() => setSignoff(loadSignoff()), [])

  useEffect(() => {
    try {
      // Opt-OUT, matching the overlay: absent key means ON.
      setMesh(localStorage.getItem(MESH_PREF_KEY) !== "0")
    } catch {
      setMesh(true)
    }
  }, [])

  /** Write the preference and tell the overlay in THIS tab to re-read it. */
  function setMeshPref(on: boolean) {
    setMesh(on)
    try {
      localStorage.setItem(MESH_PREF_KEY, on ? "1" : "0")
    } catch {
      /* non-fatal: the toggle simply will not persist */
    }
    window.dispatchEvent(new CustomEvent(MESH_PREF_EVENT))
  }

  // Live-crawl guard: block scenarios while a REAL crawl is in flight.
  const liveBlocked = crawl.active

  const toggleSignoff = (id: string) => {
    setSignoff((prev) => {
      const next = { ...prev, [id]: !prev[id] }
      try {
        localStorage.setItem(SIGNOFF_KEY, JSON.stringify(next))
      } catch {}
      return next
    })
  }

  const run = (id: string) => {
    if (running || liveBlocked) return
    current?.cancel()
    const scenario = SCENARIOS.find((s) => s.id === id)
    if (!scenario) return
    resetToIdle()
    setShowFixture(id === "k")
    const handle = runScenario(scenario)
    setCurrent(handle)
    setRunning(id)
    handle.done.then(() => {
      if (running === id) setRunning(null)
      setRunning((r) => (r === id ? null : r))
    })
  }

  const signedCount = useMemo(
    () => SCENARIOS.filter((s) => signoff[s.id]).length,
    [signoff],
  )

  if (!isDeveloper) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-[#06070e] text-white/60 text-sm">
        Developer mode only. Toggle mode via the launcher.
      </main>
    )
  }

  // ── COLLAPSED RAIL ────────────────────────────────────────────────────────
  // Slim strip: one RUN button + short label per scenario, sign-off ticks
  // still live. No descriptions, no fixture — full panel expands for those.
  if (collapsed) {
    return (
      <main className="min-h-screen bg-[#06070e] text-white px-2.5 py-3">
        <div className="flex items-center gap-1.5 mb-3 pr-9">
          <button
            onClick={onToggleCollapse}
            className="px-2 h-6 rounded border border-white/15 text-white/70 hover:bg-white/5 transition-colors text-[10px]"
            aria-label="Expand simulator"
            title="Expand simulator"
          >
            »
          </button>
          <span className="text-[9px] font-mono" style={{ color: glowColor }}>
            {signedCount}/{SCENARIOS.length}
          </span>
          {liveBlocked && <span className="text-amber-400 text-[9px]" title="LIVE CRAWL — scenarios blocked">●</span>}
          <button
            onClick={() => {
              resetToIdle()
              current?.cancel()
              setRunning(null)
              setShowFixture(false)
            }}
            className="ml-auto w-6 h-6 rounded border border-white/15 text-white/60 hover:bg-white/5 transition-colors text-[10px]"
            aria-label="Reset to idle"
            title="Reset to idle"
          >
            ⟲
          </button>
        </div>
        <div className="space-y-1.5">
          {SCENARIOS.map((s) => {
            const isRunning = running === s.id
            const disabled = (!!running && !isRunning) || liveBlocked
            return (
              <div key={s.id} className="flex items-center gap-1.5">
                <button
                  onClick={() => run(s.id)}
                  disabled={disabled}
                  className="px-2 h-6 rounded text-[9px] font-bold tracking-wider transition-all disabled:opacity-30 shrink-0"
                  style={{
                    background: isRunning ? `${glowColor}25` : `${glowColor}12`,
                    border: `1px solid ${isRunning ? glowColor : `${glowColor}44`}`,
                    color: glowColor,
                  }}
                >
                  {isRunning ? "···" : "RUN"}
                </button>
                <span
                  className="text-[10px] truncate flex-1"
                  style={{ color: isRunning ? glowColor : "rgba(255,255,255,0.55)" }}
                  title={`${s.label} — ${s.expect}`}
                >
                  {s.label}
                </span>
                <input
                  type="checkbox"
                  checked={!!signoff[s.id]}
                  onChange={() => toggleSignoff(s.id)}
                  className="accent-emerald-400 w-3 h-3 shrink-0"
                  aria-label={`Sign off ${s.label}`}
                />
              </div>
            )
          })}
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-[#06070e] text-white px-6 py-8 max-w-3xl mx-auto">
      <header className="mb-6">
        <div className="flex items-start gap-2">
          <h1 className="text-lg font-bold tracking-wide" style={{ color: glowColor }}>
            VISION STAGE SIMULATOR
          </h1>
          {onToggleCollapse && (
            <button
              onClick={onToggleCollapse}
              className="ml-auto mr-9 px-2 h-7 rounded border border-white/15 text-white/70 hover:bg-white/5 transition-colors text-xs"
              aria-label="Collapse simulator"
              title="Collapse to rail (chat stays interactive, RUN stays clickable)"
            >
              «
            </button>
          )}
        </div>
        <p className="text-xs text-white/50 mt-1">
          Specs/vision-browser-stage REQ-12 · scripted agent-action events through the real
          contract · zero backend involvement.
        </p>
        <div className="mt-2 flex items-center gap-3 text-[11px] font-mono">
          <span style={{ color: glowColor }}>
            SIGNED OFF {signedCount}/{SCENARIOS.length}
          </span>
          {liveBlocked && (
            <span className="text-amber-400">LIVE CRAWL IN PROGRESS — scenarios blocked</span>
          )}
          {/* MESH FILM — under evaluation (user-directed 2026-08-24).
              Toggles the SAME localStorage preference the overlay reads, so
              there is no simulator-only rendering path: whatever is judged
              here is literally what the panel does in a real crawl. */}
          <label className="ml-auto flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={mesh}
              onChange={(e) => setMeshPref(e.target.checked)}
              className="accent-cyan-400 w-3.5 h-3.5"
            />
            <span style={{ color: mesh ? glowColor : "rgba(255,255,255,0.45)" }}>
              MESH FILM
            </span>
          </label>
          <button
            onClick={() => {
              resetToIdle()
              current?.cancel()
              setRunning(null)
              setShowFixture(false)
            }}
            className="px-3 h-7 rounded border border-white/15 text-white/70 hover:bg-white/5 transition-colors"
          >
            RESET TO IDLE
          </button>
        </div>
      </header>

      <div className="space-y-3">
        {SCENARIOS.map((s) => {
          const isRunning = running === s.id
          const disabled = (!!running && !isRunning) || liveBlocked
          return (
            <section
              key={s.id}
              className="rounded-xl border p-4 transition-colors"
              style={{
                borderColor: isRunning ? `${glowColor}66` : "rgba(255,255,255,0.08)",
                background: isRunning ? `${glowColor}0a` : "rgba(255,255,255,0.02)",
              }}
            >
              <div className="flex items-center gap-3">
                <button
                  onClick={() => run(s.id)}
                  disabled={disabled}
                  className="px-4 h-8 rounded-lg text-[11px] font-bold tracking-wider transition-all disabled:opacity-30"
                  style={{
                    background: isRunning ? `${glowColor}25` : `${glowColor}12`,
                    border: `1px solid ${isRunning ? glowColor : `${glowColor}44`}`,
                    color: glowColor,
                  }}
                >
                  {isRunning ? "RUNNING…" : "RUN"}
                </button>
                <span className="text-sm font-medium">{s.label}</span>
                <label className="ml-auto flex items-center gap-1.5 text-[11px] cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={!!signoff[s.id]}
                    onChange={() => toggleSignoff(s.id)}
                    className="accent-emerald-400 w-3.5 h-3.5"
                  />
                  <span style={{ color: signoff[s.id] ? "#22c55e" : "rgba(255,255,255,0.4)" }}>
                    SIGNED
                  </span>
                </label>
              </div>
              {s.setup && (
                <p className="mt-2 text-[11px] text-amber-300/80">SETUP: {s.setup}</p>
              )}
              <p className="mt-1.5 text-[11px] leading-relaxed text-white/55">
                EXPECT: {s.expect}
              </p>

              {/* Scenario k renders its fixture frame inline. */}
              {s.id === "k" && showFixture && (
                <iframe
                  title="wide-fixture"
                  srcDoc={WIDE_FIXTURE_HTML}
                  sandbox="allow-scripts"
                  className="mt-3 w-full h-72 rounded-lg border border-white/10 bg-white"
                />
              )}
            </section>
          )
        })}
      </div>

      <footer className="mt-8 text-[10px] text-white/30 leading-relaxed">
        Sign-off persists in localStorage ({SIGNOFF_KEY}). Scenario i stays ACTIVE by design —
        press RESET when done. Scenarios dispatch the same CustomEvents production emits; no
        mock renderer exists anywhere in this page.
      </footer>
    </main>
  )
}

