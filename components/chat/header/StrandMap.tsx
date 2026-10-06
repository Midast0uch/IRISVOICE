"use client"

/**
 * The strand map (concept iris-strands.html, "map = the strand switcher").
 * Each strand of the current thread is a stream; its label shows the name, the
 * tags and a working dot. Click a strand to open it (a strand IS a conversation
 * id). A helper strand shows "reports to <name>". The foot makes a new strand:
 * a name, the preset tags, your own tags.
 *
 * Data: GET /api/threads/{id}/strands.
 */

import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { createStrand, fetchStrands, PRESET_STRAND_TAGS, type Strand } from "@/lib/strands/api"
import type { Palette } from "@/lib/brandPalette"
import { useCanvasLoop } from "@/components/chrome/useCanvasLoop"
import { useEscape } from "./useEscape"
import { brandVars } from "./brandVars"
import { strandLabel } from "./useThreadContext"

export interface StrandMapProps {
  threadId: string
  palette: Palette
  activeId: string | null
  /** Conversation ids with a turn running now. */
  running: ReadonlySet<string>
  /** Open a strand (the conversation id). */
  onSwitch: (strandId: string) => void
  /** A strand was made; the header refreshes its own list. */
  onCreated: (strand: Strand) => void
  onClose: () => void
  /** Space kept free above the map: the header's height. */
  top: number
}

const SWARM = "#ff9a76"
const RUN = "#f2c14e"
const COL_MIN = 100 // narrowest column; more strands than fit scroll sideways
const MAX_TAGS = 8 // backend bound
const MAX_TAG_LEN = 24

const isHelper = (s: Strand) => !!s.reports_to || s.tags.includes("swarm")

export function StrandMap({ threadId, palette, activeId, running, onSwitch, onCreated, onClose, top }: StrandMapProps) {
  const [strands, setStrands] = useState<Strand[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [name, setName] = useState("")
  const [tags, setTags] = useState<string[]>([])
  const [own, setOwn] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [width, setWidth] = useState(480)
  const rootRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEscape(true, onClose)

  useEffect(() => {
    let alive = true
    fetchStrands(threadId)
      .then((list) => { if (alive) setStrands(list) })
      .catch((e) => { console.warn("[StrandMap] fetchStrands failed:", e); if (alive) setFailed(true) })
    return () => { alive = false }
  }, [threadId])

  useLayoutEffect(() => {
    const el = rootRef.current
    if (!el) return
    const measure = () => { if (el.clientWidth > 0) setWidth(el.clientWidth) }
    measure()
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const list = strands ?? []
  const innerW = Math.max(width, (list.length + 1) * COL_MIN)
  const colOf = (i: number) => (innerW * (i + 1)) / (list.length + 1)
  const colour = (s: Strand, i: number) => (isHelper(s) ? SWARM : palette[i % 3])
  const byId = useMemo(() => new Map(list.map((s) => [s.id, s])), [list])

  // The streams: one column of drifting dots per strand, faster and brighter while it works.
  useCanvasLoop(canvasRef, (c, w, h, now) => {
    const y0 = 80, y1 = h - 130
    const n = list.length
    const X = (ci: number, y: number) => (w * (ci + 1)) / (n + 1) + Math.sin(y / 50 + ci * 1.7) * 7
    const rnd = (i: number) => { const x = Math.sin(i * 127.1) * 43758.5453; return x - Math.floor(x) }
    list.forEach((s, ci) => {
      const live = running.has(s.id)
      c.fillStyle = colour(s, ci)
      const off = (now / (live ? 18 : 40)) % 6
      for (let y = y0; y < y1; y += 6) {
        const yy = y + off, r = rnd(ci * 999 + y)
        c.globalAlpha = (live ? 0.35 : 0.2) + r * 0.4
        c.beginPath(); c.arc(X(ci, yy) + (r - 0.5) * 2, yy, 0.6 + r * 1.1, 0, Math.PI * 2); c.fill()
      }
    })
    // A helper strand is tied to the strand it reports to.
    c.setLineDash([2, 4]); c.lineWidth = 1
    list.forEach((s, ci) => {
      const pi = s.reports_to ? list.findIndex((p) => p.id === s.reports_to) : -1
      if (pi < 0) return
      const ya = y0 + 40, xa = X(pi, ya), xb = X(ci, ya + 24), mid = (xa + xb) / 2
      c.strokeStyle = colour(s, ci); c.globalAlpha = 0.6; c.lineDashOffset = -now / 50
      c.beginPath(); c.moveTo(xa, ya); c.bezierCurveTo(mid, ya, mid, ya + 24, xb, ya + 24); c.stroke()
    })
    c.setLineDash([]); c.globalAlpha = 1
  }, `${list.map((s) => s.id).join(",")}|${[...running].join(",")}|${palette.join("|")}`)

  const toggleTag = (t: string) => setTags((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  const addOwnTag = () => {
    const t = own.trim().toLowerCase().slice(0, MAX_TAG_LEN)
    setOwn("")
    if (t && !tags.includes(t) && tags.length < MAX_TAGS) setTags((prev) => [...prev, t])
  }
  const shownTags = [...PRESET_STRAND_TAGS, ...tags.filter((t) => !(PRESET_STRAND_TAGS as readonly string[]).includes(t))]

  const make = async () => {
    if (busy) return
    setBusy(true); setError(null)
    try {
      const s = await createStrand(threadId, { name: name.trim() || "new strand", tags })
      setName(""); setTags([])
      setStrands((prev) => [...(prev ?? []), s])
      onCreated(s)
    } catch (e) {
      console.warn("[StrandMap] createStrand failed:", e)
      setError("Could not make the strand.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div ref={rootRef} className="iris-hd-map" role="dialog" aria-label="Strands of this thread" style={{ ...brandVars(palette), top }}>
      <div className="iris-hd-mapscroll">
        <div style={{ position: "relative", width: innerW, height: "100%" }}>
          <canvas ref={canvasRef} role="img" aria-label="Strands of this thread as streams" />
          {list.map((s, i) => {
            const parent = s.reports_to ? byId.get(s.reports_to) : undefined
            return (
              <button
                key={s.id}
                type="button"
                className="iris-hd-slbl"
                data-strand-id={s.id}
                aria-current={s.id === activeId ? "true" : undefined}
                style={{ left: Math.round(colOf(i)), ["--c" as string]: colour(s, i) }}
                onClick={() => onSwitch(s.id)}
              >
                <b>{strandLabel(s, threadId)}</b>
                <span>{s.tags.join(" · ") || "no tag"}</span>
                {parent && <span>reports to “{strandLabel(parent, threadId)}”</span>}
                {running.has(s.id) && <i className="iris-hd-act" role="img" aria-label="working" style={{ background: RUN }} />}
              </button>
            )
          })}
        </div>
      </div>
      <div className="iris-hd-mapfoot">
        <div className="iris-hd-cap">
          {failed ? "Could not load the strands." : strands === null ? "Loading the strands…" : "Click a strand to open it. All strands of a thread share one memory."}
        </div>
        <form className="iris-hd-newrow" onSubmit={(e) => { e.preventDefault(); void make() }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="+ new strand: name it" aria-label="New strand name" maxLength={120} />
          {shownTags.map((t) => (
            <button key={t} type="button" className="iris-hd-tagpick" aria-pressed={tags.includes(t)} onClick={() => toggleTag(t)}>{t}</button>
          ))}
          <input
            className="own"
            value={own}
            onChange={(e) => setOwn(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addOwnTag() } }}
            placeholder="your own tag ↵"
            aria-label="Your own tag"
          />
          <button type="submit" className="iris-hd-small" disabled={busy}>Add</button>
        </form>
        {error && <div className="iris-hd-cap" role="alert" style={{ color: "#ff7a6e" }}>{error}</div>}
      </div>
    </div>
  )
}

export default StrandMap
