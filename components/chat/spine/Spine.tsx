"use client"

/**
 * The living spine (owner-approved concept 2 rev 3,
 * docs/design/chatview-2026-10-06/iris-strands.html: measure / xAt / drawSpine).
 *
 * ONE canvas overlay over the timeline's scroll area (a sibling of the scroll
 * element, pointer-events none, never scrolls the content). It draws:
 *   - the Xur's particle trail down the left gutter: dense, flowing down, faster while a turn runs;
 *   - the agent Xur riding the spine to the step that runs
 *       developer: the matrix row   [data-state="running"]   (components/chat/matrix/LiveMatrix.tsx)
 *       personal:  the task-card step [data-task-step="working"] (components/chat/TaskListCard.tsx)
 *       else:      the streaming reply (#msg-<running turn id>)
 *     several running rows -> a wider loop and a faint light line to each row;
 *   - personal mode: the spine bends into the card's step line (dots measured via DOM);
 *   - knots: a small Xur loop ONLY where something entered from outside the strand
 *     (turn refs, `data-knot="<kind>"` on an entry);
 *   - the gutter (hover list / click jump / drag scrub) from SpineGutter.
 *
 * Performance: the DOM is measured on change (observers, coalesced), never per frame;
 * a frame reads scrollTop and draws only what is in the visible range. The rAF loop is
 * paused while the page is hidden; under prefers-reduced-motion one static frame is drawn
 * on demand (scroll, new measurement) and nothing animates.
 */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { SpineGutter } from "./SpineGutter"
import {
  SPINE_X0,
  brandFromPalette,
  dominantDetour,
  brandColors,
  hash01,
  knotCardInfo,
  knotColor,
  normKnotKind,
  pickTarget,
  scrubTop,
  trailColor,
  wobbleAt,
  xAt,
  xurPoint,
  type Brand,
  type Detour,
  type KnotKind,
  type KnotTurn,
  type SpineChip,
} from "./spineModel"
import type { ConversationChip } from "@/types/iris"
import type { TurnRecord } from "@/lib/turns/turnStore"
import { useBrandPalette } from "@/hooks/useBrandPalette"

const RUN_LIGHT = "rgba(242,193,78,0.55)"
const MEASURE_MIN_MS = 80

interface Run {
  y: number
  x: number
}
interface Knot {
  id: string
  y: number
  kind: KnotKind
  /** The entry the knot sits on (id without the "msg-" prefix); the jump goes there. */
  msgId?: string
  /** Optional `data-knot-from` of the entry (the strand / author a helper or author knot names). */
  from?: string
  /** First words of the entry when no turn record is known. */
  text: string
}

/** What a ref address in a knot card opens. */
export interface KnotRefTarget {
  kind: "card" | "artifact" | "strand"
  open: () => void
}

interface Scene {
  brand: Brand
  running: boolean
  reduced: boolean
  detours: Detour[]
  runs: Run[]
  knots: Knot[]
  chipYs: number[]
  target: number | null
  contentH: number
  born: Map<string, number>
}

export interface SpineProps {
  /** The timeline's scroll element. */
  containerRef: React.RefObject<HTMLDivElement | null>
  glowColor: string
  isDeveloper: boolean
  prefersReducedMotion: boolean
  /** A turn is running (typing, steps running, a live turn). */
  running: boolean
  /** The running live turn, when there is one: the agent rides to its reply when no row runs. */
  streamingId: string | null
  conversationChips: ConversationChip[]
  onChipClick: (messageId: string) => void
  /** Turns that brought something in from outside (see turnKnots). */
  knotTurns: KnotTurn[]
  /** The live turns: the knot card reads the turn's author, refs, first words and time. */
  turns?: TurnRecord[]
  /** A ref address ("#T-38") -> what opens it; null (or no resolver) -> the card shows the address only. */
  resolveRef?: (address: string) => KnotRefTarget | null
}

function drawXur(c: CanvasRenderingContext2D, brand: Brand, cx: number, cy: number, R: number, now: number, o: { s: number; n?: number; speed?: number; alpha?: number; rot?: number }) {
  const sc = R / 10
  const n = o.n || 64
  const rot = o.rot !== undefined ? o.rot : ((now * (o.speed || 1)) / 30000) * Math.PI * 12
  for (let i = 0; i < n; i++) {
    const a = rot - (i / n) * Math.PI * 2
    const [x, y] = xurPoint(a, o.s)
    const f = 1 - i / n
    c.fillStyle = trailColor(brand, f, (o.alpha || 1) * (0.15 + f * 0.75))
    c.beginPath()
    c.arc(cx + x * sc, cy + y * sc, Math.max(0.5, (0.35 + f * 1.4) * (R / 12)), 0, 6.283)
    c.fill()
  }
}

export function Spine({
  containerRef,
  glowColor,
  isDeveloper,
  prefersReducedMotion,
  running,
  streamingId,
  conversationChips,
  onChipClick,
  knotTurns,
  turns,
  resolveRef,
}: SpineProps) {
  const palette = useBrandPalette()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<Scene>({
    brand: brandFromPalette(palette, glowColor),
    running,
    reduced: prefersReducedMotion,
    detours: [],
    runs: [],
    knots: [],
    chipYs: [],
    target: null,
    contentH: 0,
    born: new Map(),
  })
  const requestRef = useRef<() => void>(() => {})
  const measureRef = useRef<() => void>(() => {})
  const [chips, setChips] = useState<SpineChip[]>(() => conversationChips.map((c) => ({ messageId: c.messageId, label: c.label })))
  const chipSig = useRef("")
  // Knots as real hit targets: one button per knot, placed (not re-rendered) as the timeline scrolls.
  const [hits, setHits] = useState<Knot[]>([])
  const hitSig = useRef("")
  const hitEls = useRef(new Map<string, HTMLElement>())
  const [openKnot, setOpenKnot] = useState<string | null>(null)
  const placeRef = useRef<() => void>(() => {})

  // Latest inputs for the measure pass (read by the observers, which are set up once).
  const inputs = useRef({ isDeveloper, streamingId, running, conversationChips, knotTurns })
  inputs.current = { isDeveloper, streamingId, running, conversationChips, knotTurns }

  const brand = useMemo(() => brandFromPalette(palette, glowColor), [palette, glowColor])

  // ── props -> scene, then redraw (static frame under reduced motion) ──────────
  useEffect(() => {
    const s = sceneRef.current
    s.brand = brand
    s.running = running
    s.reduced = prefersReducedMotion
    measureRef.current()
    requestRef.current()
  }, [brand, running, prefersReducedMotion, isDeveloper, streamingId, conversationChips, knotTurns])

  // ── measure the DOM (on change only) ─────────────────────────────────────────
  useEffect(() => {
    const cont = containerRef.current
    const root = rootRef.current
    if (!cont || !root) return
    let timer: ReturnType<typeof setTimeout> | null = null
    let lastAt = 0

    const measure = () => {
      timer = null
      lastAt = performance.now()
      const inp = inputs.current
      const s = sceneRef.current
      const cr = cont.getBoundingClientRect()
      const st = cont.scrollTop
      const topOf = (el: Element) => el.getBoundingClientRect().top - cr.top + st
      const midOf = (el: Element) => {
        const r = el.getBoundingClientRect()
        return r.top - cr.top + st + r.height / 2
      }
      const rr = root.getBoundingClientRect()
      s.contentH = cont.scrollHeight

      // entries by their message id
      const byId = new Map<string, Element>()
      cont.querySelectorAll('[id^="msg-"]').forEach((el) => byId.set(el.id.slice(4), el))

      // knots: the data-knot contract on an entry + the turns whose refs / author came from outside
      const knotEls = new Map<Element, KnotKind>()
      cont.querySelectorAll("[data-knot]").forEach((el) => knotEls.set(el, normKnotKind((el as HTMLElement).dataset.knot)))
      for (const kt of inp.knotTurns) {
        const el = kt.ids.map((id) => byId.get(id)).find(Boolean)
        if (el && !knotEls.has(el)) knotEls.set(el, kt.kind)
      }
      const prevBorn = s.born
      s.born = new Map()
      let idx = 0
      s.knots = []
      knotEls.forEach((kind, el) => {
        const anchor = el.closest('[id^="msg-"]')
        const id = `${kind}:${anchor ? anchor.id : idx}`
        idx++
        s.born.set(id, prevBorn.get(id) ?? performance.now())
        s.knots.push({
          id,
          y: topOf(el) + 11,
          kind,
          msgId: anchor ? anchor.id.slice(4) : undefined,
          from: (el as HTMLElement).dataset.knotFrom,
          text: (el.textContent || "").trim().slice(0, 160),
        })
      })
      const knotSig = s.knots.map((k) => `${k.id}|${k.kind}|${k.msgId ?? ""}|${k.from ?? ""}|${k.text}`).join("\n")
      if (knotSig !== hitSig.current) {
        hitSig.current = knotSig
        const seen = new Set<string>()
        setHits(s.knots.filter((k) => (seen.has(k.id) ? false : (seen.add(k.id), true))))
      }
      placeRef.current()

      // chips: where each turn sits, and whether a knot is on it
      const nextChips: SpineChip[] = inp.conversationChips.map((c) => {
        const el = byId.get(c.messageId)
        if (!el) return { messageId: c.messageId, label: c.label }
        let knot: KnotKind | undefined
        knotEls.forEach((kind, k) => {
          if (!knot && (el === k || el.contains(k))) knot = kind
        })
        return { messageId: c.messageId, label: c.label, y: topOf(el) + 11, knot }
      })
      s.chipYs = nextChips.filter((c) => c.y !== undefined).map((c) => c.y as number)
      const sig = nextChips.map((c) => `${c.messageId}|${c.label}|${c.y !== undefined ? Math.round(c.y) : ""}|${c.knot ?? ""}`).join("\n")
      if (sig !== chipSig.current) {
        chipSig.current = sig
        setChips(nextChips)
      }

      // personal mode: the spine bends into each task card's step line
      s.detours = []
      s.runs = []
      if (!inp.isDeveloper) {
        cont.querySelectorAll("[data-task-steps]").forEach((steps) => {
          const dots = steps.querySelectorAll("[data-task-step] > button > :first-child")
          if (!dots.length) return
          const r0 = dots[0].getBoundingClientRect()
          s.detours.push({ x: r0.left + r0.width / 2 - rr.left, y0: midOf(dots[0]), y1: midOf(dots[dots.length - 1]) })
        })
        cont.querySelectorAll('[data-task-step="working"] > button > :first-child').forEach((dot) => {
          const r = dot.getBoundingClientRect()
          s.runs.push({ y: midOf(dot), x: r.left + r.width / 2 - rr.left })
        })
      } else {
        cont.querySelectorAll('[data-state="running"]').forEach((row) => {
          s.runs.push({ y: midOf(row), x: row.getBoundingClientRect().left - rr.left - 2 })
        })
      }

      // the agent's target: running rows, else the streaming reply, else the turn's own prompt while it runs
      let replyY: number | null = null
      if (inp.streamingId && byId.has(inp.streamingId)) replyY = topOf(byId.get(inp.streamingId) as Element) + 11
      else if (inp.running && s.runs.length === 0) {
        const all = cont.querySelectorAll('[id^="msg-"]')
        if (all.length) replyY = topOf(all[all.length - 1]) + 11
      }
      s.target = inp.running || s.runs.length ? pickTarget(s.runs.map((r) => r.y), replyY) : null
      requestRef.current()
    }

    // coalesce bursts (streaming text) to one measure per MEASURE_MIN_MS
    const schedule = () => {
      if (timer) return
      timer = setTimeout(measure, Math.max(0, MEASURE_MIN_MS - (performance.now() - lastAt)))
    }
    measureRef.current = schedule
    measure()

    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null
    ro?.observe(cont)
    if (cont.firstElementChild) ro?.observe(cont.firstElementChild)
    const mo = typeof MutationObserver !== "undefined" ? new MutationObserver(schedule) : null
    mo?.observe(cont, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["data-state", "data-task-step", "data-knot"] })
    // rows animate in (born); one slow re-measure while a turn runs catches the settled positions
    const iv = setInterval(() => {
      if (inputs.current.running) schedule()
    }, 500)
    return () => {
      if (timer) clearTimeout(timer)
      clearInterval(iv)
      ro?.disconnect()
      mo?.disconnect()
      measureRef.current = () => {}
    }
  }, [containerRef])

  // Place each knot's hit target at its knot (no React render per scroll); a knot out of view is hidden,
  // so it cannot take focus.
  const place = () => {
    const cont = containerRef.current
    if (!cont) return
    const sc = sceneRef.current
    const top = cont.scrollTop
    const h = cont.clientHeight
    for (const k of sc.knots) {
      const el = hitEls.current.get(k.id)
      if (!el) continue
      const y = k.y - top
      el.style.transform = `translate(${Math.round(xAt(k.y, sc.detours) - 10)}px, ${Math.round(y - 10)}px)`
      el.style.visibility = h <= 0 || (y > -12 && y < h + 12) ? "visible" : "hidden"
    }
  }
  placeRef.current = place
  useLayoutEffect(() => place(), [hits]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── the frame loop ───────────────────────────────────────────────────────────
  useEffect(() => {
    const cv = canvasRef.current
    const cont = containerRef.current
    if (!cv || !cont) return
    const ctx = cv.getContext("2d")
    if (!ctx) return
    const c: CanvasRenderingContext2D = ctx
    let raf = 0
    let alive = true
    let last = performance.now()
    let flow = 0
    let agentY: number | null = null

    function fit(): [number, number] | null {
      const r = cv!.getBoundingClientRect()
      if (r.width < 1 || r.height < 1) return null
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      const w = Math.round(r.width * dpr)
      const h = Math.round(r.height * dpr)
      if (cv!.width !== w || cv!.height !== h) {
        cv!.width = w
        cv!.height = h
      }
      c.setTransform(dpr, 0, 0, dpr, 0, 0)
      return [r.width, r.height]
    }

    function draw(now: number) {
      const size = fit()
      if (!size) return
      placeRef.current()
      const [w, h] = size
      const s = sceneRef.current
      const b = s.brand
      const reduced = s.reduced
      const dt = Math.min(64, now - last)
      last = now
      const t = reduced ? 0 : now
      c.clearRect(0, 0, w, h)
      const top = cont!.scrollTop
      const busy = s.running
      if (!reduced) flow += dt * (busy ? 0.05 : 0.012)
      const gap = busy ? 3.6 : 4.5

      // the agent eases toward its target (it never teleports; reduced motion snaps)
      if (s.target !== null) agentY = agentY === null || reduced ? s.target : agentY + (s.target - agentY) * (1 - Math.pow(0.9, dt / 16.7))
      else agentY = null
      const ay = agentY !== null ? agentY - top : null
      const ax = agentY !== null ? xAt(agentY, s.detours) : SPINE_X0

      const first = s.chipYs.length ? Math.min(...s.chipYs) - 18 : 0
      const startY = Math.max(-30, first - top - 10)
      const endY = Math.min(h, s.contentH - top)

      // core filament (visible range only)
      if (endY > startY) {
        const g = c.createLinearGradient(0, Math.max(0, startY), 0, Math.max(1, endY))
        g.addColorStop(0, trailColor(b, 1, 0))
        g.addColorStop(0.08, trailColor(b, 0.9, 0.25))
        g.addColorStop(0.6, trailColor(b, 0.5, 0.16))
        g.addColorStop(1, trailColor(b, 0.1, 0.05))
        c.strokeStyle = g
        c.lineWidth = 1
        c.beginPath()
        let fst = true
        for (let y = Math.max(-30, startY); y <= endY; y += 4) {
          const yc = y + top
          const x = xAt(yc, s.detours) + Math.sin(yc / 41 + t / 1700) * 2.4 * wobbleAt(yc, s.detours)
          if (fst) c.moveTo(x, y)
          else c.lineTo(x, y)
          fst = false
        }
        c.stroke()
      }

      // particles (visible range only)
      const i0 = Math.floor((top - flow) / gap) - 1
      for (let i = i0, n = 0; n < 900; i++, n++) {
        const yc = i * gap + flow
        const y = yc - top
        if (y > endY) break
        if (y < -30 || y < startY - 30) continue
        const r = hash01(i)
        const bx = xAt(yc, s.detours)
        const inCard = 1 - wobbleAt(yc, s.detours)
        let x = bx + (Math.sin(yc / 41 + t / 1700) * 2.4 + (r - 0.5) * 3.2) * (1 - inCard * 0.7)
        let a = (0.22 + r * 0.45) * (1 - inCard * 0.25)
        const size = (0.5 + r * 1.5) * (1 - inCard * 0.3)
        if (y < startY + 30) a *= Math.max(0, (y - startY + 30) / 60)
        if (ay !== null) {
          const d = y - ay
          if (Math.abs(d) < 60) {
            const k = 1 - Math.abs(d) / 60
            x += (ax - x) * k
            a *= 1 - k * 0.85
          }
        }
        const f = 0.5 + 0.5 * Math.sin(yc / 260 - t / 5000)
        c.fillStyle = trailColor(b, f, a)
        c.beginPath()
        c.arc(x, y, size, 0, 6.283)
        c.fill()
      }

      // a tick at each turn
      c.strokeStyle = trailColor(b, 0.9, 0.55)
      c.lineWidth = 1
      for (const cy of s.chipYs) {
        const y = cy - top
        if (y < -10 || y > h + 10) continue
        const x = xAt(cy, s.detours)
        c.beginPath()
        c.moveTo(x + 5, y)
        c.lineTo(x + 10, y)
        c.stroke()
      }

      // knots: a small Xur loop, only where something came in from outside
      for (const k of s.knots) {
        const y = k.y - top
        if (y < -20 || y > h + 20) continue
        const age = reduced ? 9 : (now - (s.born.get(k.id) ?? now)) / 1000
        const R = 8 * Math.min(1, age / 0.8) + (age < 2 ? Math.sin(age * 6) * 1.5 * (1 - age / 2) : 0)
        const kx = xAt(k.y, s.detours)
        c.fillStyle = knotColor(b, k.kind)
        for (let j = 0; j < 30; j++) {
          const aa = t / 2400 - (j / 30) * 6.283
          const [px, py] = xurPoint(aa, 1)
          c.globalAlpha = 0.25 + 0.7 * (1 - j / 30)
          c.beginPath()
          c.arc(kx + (px * R) / 10, y + (py * R) / 10, 0.9, 0, 6.283)
          c.fill()
        }
        c.globalAlpha = 1
      }

      // the agent Xur at the running step; parallel rows: wider loops + a faint light line to each
      if (ay !== null && ay > -30 && ay < h + 30) {
        const parallel = s.runs.length > 1
        const inCard = dominantDetour(s.detours, agentY as number).k > 0.5
        drawXur(c, b, ax, ay, inCard ? 10 : 13, t, { s: parallel ? 1.25 : 0.9, n: 60, speed: 2.4, rot: reduced ? 1 : undefined })
        if (parallel && !reduced) {
          c.strokeStyle = RUN_LIGHT
          c.lineWidth = 1
          c.setLineDash([3, 5])
          for (const run of s.runs) {
            const y = run.y - top
            if (y < -30 || y > h + 30) continue
            c.lineDashOffset = -now / 40
            c.beginPath()
            c.moveTo(ax + 12, ay)
            c.bezierCurveTo(ax + 20, ay, ax + 14, y, Math.max(ax + 20, run.x), y)
            c.stroke()
          }
          c.setLineDash([])
        } else if (parallel) {
          c.strokeStyle = RUN_LIGHT
          c.lineWidth = 1
          for (const run of s.runs) {
            const y = run.y - top
            c.beginPath()
            c.moveTo(ax + 12, ay)
            c.lineTo(Math.max(ax + 20, run.x), y)
            c.stroke()
          }
        }
      }
    }

    const tick = (now: number) => {
      raf = 0
      if (!alive || document.hidden) return
      draw(now)
      if (!sceneRef.current.reduced) raf = requestAnimationFrame(tick)
    }
    const request = () => {
      if (!raf && alive && !document.hidden) raf = requestAnimationFrame(tick)
    }
    requestRef.current = request

    const onVis = () => {
      if (document.hidden) {
        if (raf) cancelAnimationFrame(raf)
        raf = 0
      } else {
        last = performance.now()
        request()
      }
    }
    document.addEventListener("visibilitychange", onVis)
    cont.addEventListener("scroll", request, { passive: true })
    window.addEventListener("resize", request)
    request()
    return () => {
      alive = false
      if (raf) cancelAnimationFrame(raf)
      document.removeEventListener("visibilitychange", onVis)
      cont.removeEventListener("scroll", request)
      window.removeEventListener("resize", request)
      requestRef.current = () => {}
    }
  }, [containerRef])

  const onScrub = (fraction: number) => {
    const el = containerRef.current
    if (!el) return
    const prev = el.style.scrollBehavior
    el.style.scrollBehavior = "auto"
    el.scrollTop = scrubTop(fraction, el.scrollHeight, el.clientHeight)
    el.style.scrollBehavior = prev
  }

  const jumpTo = (k: Knot) => {
    setOpenKnot(null)
    if (k.msgId) {
      onChipClick(k.msgId)
      return
    }
    const el = containerRef.current
    if (el) el.scrollTo?.({ top: Math.max(0, k.y - 60), behavior: prefersReducedMotion ? "auto" : "smooth" })
  }
  const [c1] = brandColors(brand)

  return (
    <div
      ref={rootRef}
      data-spine
      style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 11 }}
    >
      <canvas ref={canvasRef} aria-hidden data-spine-canvas style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />
      <SpineGutter chips={chips} glowColor={glowColor} containerRef={containerRef} onChipClick={onChipClick} onScrub={onScrub} />
      {hits.map((k) => {
        const turn = turns?.find((t) => t.id === k.msgId || t.clientRef === k.msgId)
        const info = knotCardInfo(k.kind, turn, { from: k.from, fallbackText: k.text })
        const col = knotColor(brand, k.kind)
        const open = openKnot === k.id
        const cont = containerRef.current
        const flip = !!cont && k.y - cont.scrollTop > cont.clientHeight - 170 && cont.clientHeight > 0
        const cardId = `knot-card-${k.id}`
        return (
          <div
            key={k.id}
            ref={(el) => {
              if (el) hitEls.current.set(k.id, el)
              else hitEls.current.delete(k.id)
            }}
            data-knot-hit={k.id}
            onMouseEnter={() => setOpenKnot(k.id)}
            onMouseLeave={() => setOpenKnot((cur) => (cur === k.id ? null : cur))}
            onFocus={() => setOpenKnot(k.id)}
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpenKnot((cur) => (cur === k.id ? null : cur))
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape" && open) {
                e.stopPropagation()
                setOpenKnot(null)
              }
            }}
            style={{ position: "absolute", left: 0, top: 0, width: 20, height: 20, pointerEvents: "none", zIndex: open ? 40 : 12 }}
          >
            <button
              type="button"
              data-testid="spine-knot"
              data-knot-kind={k.kind}
              aria-label={`${info.title}${info.first ? `: ${info.first}` : ""}. Jump to it.`}
              aria-describedby={open ? cardId : undefined}
              onClick={() => jumpTo(k)}
              style={{ position: "absolute", inset: 0, width: 20, height: 20, padding: 0, border: 0, borderRadius: "50%", background: "transparent", cursor: "pointer", pointerEvents: "auto" }}
            />
            {open && (
              <div
                id={cardId}
                role="group"
                aria-label="Where this came from"
                data-testid="spine-knot-card"
                style={{
                  position: "absolute",
                  left: 30,
                  ...(flip ? { bottom: -4 } : { top: -6 }),
                  width: 236,
                  padding: "8px 10px",
                  borderRadius: 10,
                  background: "rgba(8,9,18,0.96)",
                  border: `1px solid ${col.replace(/,[\d.]+\)$/, ",0.35)")}`,
                  boxShadow: "0 16px 40px rgba(0,0,0,0.6)",
                  backdropFilter: "blur(8px)",
                  WebkitBackdropFilter: "blur(8px)",
                  pointerEvents: "auto",
                }}
              >
                <div className="font-mono text-[11px] leading-snug flex gap-1.5 items-baseline" style={{ color: col }}>
                  <span aria-hidden style={{ opacity: 0.8 }}>⟜</span>
                  <span data-knot-title>{info.title}</span>
                </div>
                {info.refs.length > 0 && (
                  <ul className="mt-1 flex flex-col gap-0.5" style={{ listStyle: "none", margin: "4px 0 0", padding: 0 }}>
                    {info.refs.map((addr) => {
                      const target = resolveRef?.(addr) ?? null
                      return (
                        <li key={addr} className="font-mono text-[11px] min-w-0">
                          {target ? (
                            <button
                              type="button"
                              data-knot-ref={addr}
                              onClick={() => {
                                setOpenKnot(null)
                                target.open()
                              }}
                              className="truncate max-w-full text-left"
                              style={{ background: "none", border: 0, padding: 0, color: c1, cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 2 }}
                              title={`Open ${target.kind}`}
                            >
                              {addr}
                              <span style={{ opacity: 0.55 }}> · {target.kind}</span>
                            </button>
                          ) : (
                            <span data-knot-ref={addr} style={{ color: "rgba(255,255,255,0.7)" }}>
                              {addr}
                            </span>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
                {(info.first || info.time) && (
                  <div className="mt-1.5 text-[11px] leading-snug flex gap-2 min-w-0" style={{ color: "rgba(255,255,255,0.6)" }}>
                    <span className="flex-1 min-w-0 truncate italic" data-knot-first>{info.first}</span>
                    {info.time && <span className="flex-none tabular-nums" style={{ color: "rgba(255,255,255,0.4)" }}>{info.time}</span>}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default Spine
