"use client"

/**
 * The thread orbit (concept iris-strands.html, "thread orbit"). An overlay inside
 * the chat wing, not a dropdown: the Xur is drawn large and the threads sit on
 * its loops. Recent threads turn on the upper loops (wheel, scroll or arrow keys
 * turn them); pinned threads keep the lower loops. Typing filters, Enter opens
 * the front thread, Esc closes.
 *
 * Data: GET /api/threads, a summary list - never the message bodies.
 */

import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { fetchThreads, patchThread, type ThreadSummary } from "@/lib/strands/api"
import { makePaletteSampler, type Palette } from "@/lib/brandPalette"
import { useCanvasLoop } from "@/components/chrome/useCanvasLoop"
import { useEscape } from "./useEscape"
import { brandVars } from "./brandVars"

export interface ThreadOrbitProps {
  palette: Palette
  /** The thread on screen (marked current). */
  activeThreadId: string | null
  onOpen: (thread: ThreadSummary) => void
  onNew: () => void
  onClose: () => void
}

const STEP = Math.PI / 4 // angle between neighbours on a loop
const PINNED_SLOTS = 3
const WHEEL_NOTCH = 40 // wheel delta that turns the orbit by one thread
const DEFAULT_SIZE = { w: 480, h: 640 }

export function ago(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ""
  const m = Math.max(0, Math.round((now - t) / 60000))
  if (m < 1) return "now"
  if (m < 60) return `${m} min`
  if (m < 24 * 60) return `${Math.round(m / 60)} h`
  return new Date(t).toLocaleDateString("en", { month: "short", day: "numeric" })
}

const meta = (t: ThreadSummary) =>
  `${t.strand_count} strand${t.strand_count === 1 ? "" : "s"}${t.updated_at ? ` · ${ago(t.updated_at)}` : ""}`

const mod = (n: number, m: number) => ((n % m) + m) % m

/** Geometry of the loops for a container size. */
export function orbitGeometry(w: number, h: number) {
  const cx = w / 2, cy = h * 0.47, R = Math.min(w, h) * 0.25
  const rr = R * 1.18 + 18
  const at = (ang: number): [number, number] => [
    Math.max(64, Math.min(w - 64, cx + Math.cos(ang) * rr * 1.12)),
    cy + Math.sin(ang) * rr,
  ]
  return { cx, cy, R, rr, at }
}

export function ThreadOrbit({ palette, activeThreadId, onOpen, onNew, onClose }: ThreadOrbitProps) {
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [q, setQ] = useState("")
  const [target, setTarget] = useState(0)
  const [rot, setRot] = useState(0)
  const [size, setSize] = useState(DEFAULT_SIZE)
  const rootRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rotRef = useRef(0)
  const targetRef = useRef(0)
  const wheelAcc = useRef(0)

  useEscape(true, onClose)

  useEffect(() => {
    let alive = true
    fetchThreads()
      .then((list) => { if (alive) setThreads(list) })
      .catch((e) => { console.warn("[ThreadOrbit] fetchThreads failed:", e); if (alive) setFailed(true) })
    return () => { alive = false }
  }, [])

  // Container size (the loops scale with the wing).
  useLayoutEffect(() => {
    const el = rootRef.current
    if (!el) return
    const measure = () => {
      if (el.clientWidth > 0 && el.clientHeight > 0) setSize({ w: el.clientWidth, h: el.clientHeight })
    }
    measure()
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Ease the shown rotation to the target; reduced motion jumps.
  useEffect(() => {
    targetRef.current = target
    const still = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    if (still) { rotRef.current = target; setRot(target); return }
    let raf = 0
    const step = () => {
      raf = 0
      const d = targetRef.current - rotRef.current
      if (Math.abs(d) < 0.002) { rotRef.current = targetRef.current; setRot(rotRef.current); return }
      rotRef.current += d * 0.15
      setRot(rotRef.current)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => { if (raf) cancelAnimationFrame(raf) }
  }, [target])

  const turn = useCallback((by: number) => setTarget((t) => t + by), [])

  // Wheel turns the orbit. A native listener: React's onWheel is passive and cannot stop the page scroll.
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      wheelAcc.current += e.deltaY
      if (Math.abs(wheelAcc.current) >= WHEEL_NOTCH) {
        turn(Math.sign(wheelAcc.current))
        wheelAcc.current = 0
      }
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => el.removeEventListener("wheel", onWheel)
  }, [turn])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (threads ?? []).filter((t) => !needle || t.title.toLowerCase().includes(needle))
  }, [threads, q])
  const pinned = useMemo(() => filtered.filter((t) => t.pinned), [filtered])
  const lower = pinned.slice(0, PINNED_SLOTS)
  // The turning list: recent threads, then pinned threads that do not fit the lower loops.
  const upper = useMemo(() => [...filtered.filter((t) => !t.pinned), ...pinned.slice(PINNED_SLOTS)], [filtered, pinned])
  const frontIdx = upper.length ? mod(Math.round(target), upper.length) : -1

  const onQuery = (v: string) => {
    setQ(v)
    rotRef.current = 0; targetRef.current = 0
    setTarget(0); setRot(0)
  }

  const togglePin = (t: ThreadSummary) => {
    patchThread(t.id, { pinned: !t.pinned })
      .then((u) => setThreads((prev) => (prev ? prev.map((x) => (x.id === t.id ? { ...x, ...u } : x)) : prev)))
      .catch((e) => console.warn("[ThreadOrbit] patchThread failed:", t.id, e))
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && frontIdx >= 0) { e.preventDefault(); onOpen(upper[frontIdx]) }
    else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); turn(1) }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); turn(-1) }
  }

  const { cx, cy, R, rr, at } = orbitGeometry(size.w, size.h)

  // The Xur, large, turning with the list (concept drawXur with rot).
  const sampler = useMemo(() => makePaletteSampler(palette), [palette])
  useCanvasLoop(canvasRef, (c, w, h, now) => {
    const g = orbitGeometry(w, h)
    const n = 260, sc = g.R / 10
    for (let i = 0; i < n; i++) {
      const a = -Math.PI / 2 - rotRef.current * STEP + now / 9000 - (i / n) * Math.PI * 2
      const x = 7 * Math.cos(a) - 3 * Math.cos(9 * a), y = 7 * Math.sin(a) - 3 * Math.sin(9 * a)
      const f = 1 - i / n
      c.fillStyle = sampler(i / n, 0.15 + f * 0.75)
      c.beginPath()
      c.arc(g.cx + x * sc, g.cy + y * sc, Math.max(0.5, (0.35 + f * 1.4) * 2.6), 0, Math.PI * 2)
      c.fill()
    }
  }, palette.join("|"))

  const labels: React.ReactNode[] = []
  lower.forEach((t, k) => {
    const [x, y] = at(Math.PI / 2 + (k - 1) * STEP)
    labels.push(<OrbitLabel key={t.id} t={t} x={x} y={y} loop="lower" current={t.id === activeThreadId} onOpen={onOpen} onPin={togglePin} />)
  })
  if (upper.length) {
    for (let k = -2; k <= 2; k++) {
      if (upper.length < 5 && Math.abs(k) > Math.floor((upper.length - 1) / 2) + (k > 0 && upper.length % 2 === 0 ? 1 : 0)) continue
      const raw = Math.round(target) + k
      const rel = raw - rot
      if (Math.abs(rel) > 2.4) continue
      const t = upper[mod(raw, upper.length)]
      const [x, y] = at(-Math.PI / 2 + rel * STEP)
      labels.push(
        <OrbitLabel key={t.id} t={t} x={x} y={y} loop="upper" front={k === 0} current={t.id === activeThreadId}
          opacity={Math.max(0.25, 1 - Math.abs(rel) * 0.22)} onOpen={onOpen} onPin={togglePin} />,
      )
    }
  }

  const note = failed ? "Could not load your threads."
    : threads === null ? "Loading your threads…"
    : threads.length === 0 ? "No threads yet."
    : filtered.length === 0 ? "No thread matches."
    : null

  return (
    <div ref={rootRef} className="iris-hd-orbit" role="dialog" aria-label="Your threads" style={brandVars(palette)}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="iris-hd-ocap">Your threads · ◆ pinned keep the lower loops</div>
      {note && <div className="iris-hd-olbl iris-hd-onote" style={{ left: cx, top: cy - rr }}>{note}</div>}
      {labels}
      <div className="iris-hd-ofoot">
        <input
          autoFocus
          value={q}
          onChange={(e) => onQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Find a thread · scroll to turn · Enter opens"
          aria-label="Find a thread"
        />
        <button type="button" className="iris-hd-small" onClick={onNew}>+ New thread</button>
        <button type="button" className="iris-hd-small" onClick={onClose} aria-label="Close the thread orbit">Esc</button>
      </div>
    </div>
  )
}

function OrbitLabel({ t, x, y, loop, front, current, opacity, onOpen, onPin }: {
  t: ThreadSummary
  x: number
  y: number
  loop: "upper" | "lower"
  front?: boolean
  current: boolean
  opacity?: number
  onOpen: (t: ThreadSummary) => void
  onPin: (t: ThreadSummary) => void
}) {
  return (
    <div
      className={`iris-hd-olbl${front ? " front" : ""}${t.pinned ? " pinned" : ""}`}
      data-thread-id={t.id}
      data-loop={loop}
      data-front={front ? "true" : "false"}
      aria-current={current ? "true" : undefined}
      style={{ left: Math.round(x), top: Math.round(y), opacity }}
    >
      <button type="button" className="iris-hd-oopen" onClick={() => onOpen(t)} title={t.last_preview || t.title}>
        <span className="iris-hd-otitle">{t.title}</span>
        <small>{meta(t)}</small>
      </button>
      <button
        type="button"
        className="iris-hd-pin"
        aria-pressed={t.pinned}
        aria-label={t.pinned ? `Unpin ${t.title}` : `Pin ${t.title}`}
        title={t.pinned ? "Unpin" : "Pin to the lower loops"}
        onClick={() => onPin(t)}
      >
        {t.pinned ? "◆" : "◇"}
      </button>
    </div>
  )
}

export default ThreadOrbit
