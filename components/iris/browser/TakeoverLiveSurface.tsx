"use client"

import React, { useEffect, useRef, useState } from "react"
import { getLiveRun } from "@/lib/liveBrowser"

/**
 * TakeoverLiveSurface — the LIVE CDP screencast surface for a takeover
 * (REQ-13, REQ-14, REQ-16; this spec's T16/T17).
 *
 * Design D5: the user acts INSIDE the agent's own headless session, not a
 * static replay. This component renders the ack-paced frame stream and
 * forwards the user's page-level pointer / keyboard / text input back over the
 * grant-gated channel.
 *
 * TRANSPORT-AGNOSTIC + CT-6-SAFE BY CONSTRUCTION:
 *   - It renders NO interactive element tags (a button, an input, or an anchor
 *     with href) — CT-6 forbids those in the overlay tree; it captures
 *     pointer/key events on its own surface div and echoes text through the
 *     window event bus. (Wording note: the tags are described, not spelled, so
 *     the CT-6b guard's source scan stays clean — the same convention the
 *     server-side takeover docstring uses for its transport token.)
 *   - It never talks to the backend directly: it emits `iris:takeover_input`
 *     CustomEvents, which `useIRISWebSocket` forwards over the WS (the WS
 *     layer also acks the frames). So this component stays transport-agnostic
 *     and the one WS owner is unchanged.
 *
 * REQ-16 AC3 (bounded, latest-wins): the WebSocket layer acks each frame on
 * receipt (one in flight backend-side) and keeps the newest one in
 * lib/liveBrowser, so this surface starts from the current page when it
 * mounts late and renders the newest frame after that. REQ-16 edge: outside
 * watch mode a frame with no `question_id` is dropped.
 */

export interface TakeoverFrame {
  run_id?: string
  question_id?: string
  seq?: number
  frame_seq?: number
  ts?: number
  viewport_w?: number
  viewport_h?: number
  format?: string
  bytes?: string
}

interface Props {
  /** The active takeover's run id + question id (from the overlay state). */
  runId: string
  questionId?: string
  /** Size of the LIVE frame box (CSS px, or a CSS length such as "100%").
   * Input is scaled from the rendered box, so any size maps correctly. */
  width?: number | string
  height?: number | string
  className?: string
  /** Watch mode: the agent drives and the user watches its live page, so
   * frames with no question_id (no hand-over open) are shown too, matched by
   * runId. Off: only a hand-over's frames (the original contract). */
  watch?: boolean
  /** Forward the user's pointer/keys to the page. The backend still gates
   * input on an open grant; this only stops a watch-only view from sending. */
  interactive?: boolean
  /** Watch mode: the rect the frame image actually covers (letterbox bars
   * excluded), in px from the browser card's padding-box origin - the overlay's
   * own coordinate space - so the agent's cursor lands ON the page. null when
   * it cannot be measured or the surface unmounts. */
  onImageRect?: (rect: ImageRect | null) => void
}

export interface ImageRect {
  x: number
  y: number
  w: number
  h: number
}

/** Where an object-fit: contain image of the source viewport sits in a box. With
 * no source size the image is taken to fill the box. */
export function containedRect(boxW: number, boxH: number, vw?: number, vh?: number): ImageRect {
  if (!vw || !vh || boxW <= 0 || boxH <= 0) return { x: 0, y: 0, w: boxW, h: boxH }
  const scale = Math.min(boxW / vw, boxH / vh)
  const w = vw * scale
  const h = vh * scale
  return { x: (boxW - w) / 2, y: (boxH - h) / 2, w, h }
}

/** Offset of `el` from the browser card's padding-box origin (the nearest
 * ancestor marked data-browser-card), by summing layout offsets. Layout offsets,
 * not getBoundingClientRect: the wing view applies a 3D transform, and a
 * projected rect would not share the overlay's coordinate space. */
function offsetWithinCard(el: HTMLElement): { x: number; y: number } | null {
  let x = 0
  let y = 0
  let n: HTMLElement | null = el
  while (n && !n.hasAttribute("data-browser-card")) {
    x += n.offsetLeft
    y += n.offsetTop
    n = n.offsetParent as HTMLElement | null
  }
  return n ? { x, y } : null
}

/** A box-size change smaller than this (px, per axis) is not worth resizing the
 * agent's browser for. */
const VIEWPORT_MIN_DELTA = 8
const VIEWPORT_DEBOUNCE_MS = 400

export function TakeoverLiveSurface({
  runId,
  questionId,
  width = 640,
  height = 360,
  className,
  watch = false,
  interactive = true,
  onImageRect,
}: Props) {
  // Watch mode starts from the newest frame the WebSocket already received,
  // so a panel opened mid-run shows the page at once.
  const [frame, setFrame] = useState<TakeoverFrame | null>(() => {
    return watch && runId ? getLiveRun(runId)?.frame ?? null : null
  })
  const surfaceRef = useRef<HTMLDivElement | null>(null)

  // The run changed: show THAT run's newest frame from the store. Live
  // 2026-10-12: a new run's first frame arrived ~100 ms before the panel
  // switched to it, so the frame filter dropped it; a static page sends no
  // other, and the previous run's page stayed on screen.
  useEffect(() => {
    setFrame(watch && runId ? getLiveRun(runId)?.frame ?? null : null)
  }, [runId, watch])

  const emitInput =(payload: Record<string, unknown>) => {
    if (typeof window === "undefined" || !interactive) return
    window.dispatchEvent(
      new CustomEvent("iris:takeover_input", {
        detail: { run_id: runId, question_id: questionId, ...payload },
      })
    )
  }

  useEffect(() => {
    if (typeof window === "undefined") return
    const onFrame = (e: Event) => {
      const d = (e as CustomEvent<TakeoverFrame>).detail
      if (!d) return
      if (watch) {
        // Watch mode: the run is the owner; any frame of THIS run is shown,
        // whether or not a hand-over is open.
        if (!runId || d.run_id !== runId) return
      } else {
        // REQ-16 edge: a frame without an owner (question_id) is unattributable.
        if (!d.question_id) return
        // Only frames for THIS takeover's run/question.
        if (runId && d.run_id && d.run_id !== runId) return
        if (questionId && d.question_id !== questionId) return
      }
      setFrame(d)
    }
    window.addEventListener("iris:takeover_frame", onFrame)
    return () => window.removeEventListener("iris:takeover_frame", onFrame)
  }, [runId, questionId, watch])

  // Watch mode tells the backend the size of this box (CSS px) so the agent's
  // browser viewport takes the panel's aspect and its frames fill the surface
  // instead of sitting letterboxed. Once on mount, then only when the box moved
  // by VIEWPORT_MIN_DELTA, debounced - a drag-resize must not resize the page
  // on every pixel. useIRISWebSocket forwards the event.
  useEffect(() => {
    const el = surfaceRef.current
    if (!watch || !runId || !el || typeof ResizeObserver === "undefined") return
    let sent: { w: number; h: number } | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    const send = (w: number, h: number) => {
      sent = { w, h }
      window.dispatchEvent(
        new CustomEvent("iris:browser_viewport", { detail: { run_id: runId, width: w, height: h } })
      )
    }
    const measure = () => {
      const w = Math.round(el.offsetWidth)
      const h = Math.round(el.offsetHeight)
      if (w <= 0 || h <= 0) return
      if (!sent) { send(w, h); return }
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        if (sent && Math.abs(w - sent.w) < VIEWPORT_MIN_DELTA && Math.abs(h - sent.h) < VIEWPORT_MIN_DELTA) return
        send(w, h)
      }, VIEWPORT_DEBOUNCE_MS)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => {
      ro.disconnect()
      if (timer) clearTimeout(timer)
    }
  }, [watch, runId])

  // Report the area the image really covers, for the overlay's cursor.
  const imgVw = frame?.viewport_w
  const imgVh = frame?.viewport_h
  const lastRectRef = useRef<ImageRect | null>(null)
  useEffect(() => {
    const el = surfaceRef.current
    if (!onImageRect || !el) return
    const report = () => {
      const off = offsetWithinCard(el)
      const c = containedRect(el.offsetWidth, el.offsetHeight, imgVw, imgVh)
      const next = off ? { x: off.x + c.x, y: off.y + c.y, w: c.w, h: c.h } : null
      const prev = lastRectRef.current
      if (next && prev && next.x === prev.x && next.y === prev.y && next.w === prev.w && next.h === prev.h) return
      lastRectRef.current = next
      onImageRect(next)
    }
    report()
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(report)
    ro.observe(el)
    return () => ro.disconnect()
  }, [onImageRect, imgVw, imgVh])
  useEffect(() => () => {
    lastRectRef.current = null
    onImageRect?.(null)
  }, [onImageRect])

  // The frame is drawn object-fit: contain, so it is letterboxed inside the
  // surface. The fraction must be of the IMAGE box, not the surface box, or a
  // click lands offset by the bars.
  const toFraction = (e: { clientX: number; clientY: number }) => {
    const el = surfaceRef.current
    if (!el) return { x: 0, y: 0 }
    const rect = el.getBoundingClientRect()
    const iw = frame?.viewport_w || rect.width
    const ih = frame?.viewport_h || rect.height
    const scale = Math.min(rect.width / Math.max(1, iw), rect.height / Math.max(1, ih))
    const dw = iw * scale
    const dh = ih * scale
    const left = rect.left + (rect.width - dw) / 2
    const top = rect.top + (rect.height - dh) / 2
    const x = (e.clientX - left) / Math.max(1, dw)
    const y = (e.clientY - top) / Math.max(1, dh)
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) }
  }

  return (
    <div
      ref={surfaceRef}
      className={className}
      // The ONLY interactive surface during a takeover. Pointer events are
      // auto HERE (the grant is open); the overlay root stays pointer-events
      // none so nothing else in the tree steals input.
      // A watch-only view lets the wheel and clicks fall through to nothing:
      // the user sees the agent's page but does not steer it until they take
      // control.
      style={{
        position: "relative", width, height,
        touchAction: "none",
        ...(interactive
          ? ({ pointerEvents: "auto", cursor: "default" } as const)
          : ({ pointerEvents: "none" } as const)),
      }}
      tabIndex={interactive ? 0 : -1}
      role="application"
      aria-label={interactive ? "Live browser - you have control" : "Live browser - the agent's page"}
      onPointerDown={(e) => {
        surfaceRef.current?.focus()
        const { x, y } = toFraction(e)
        emitInput({ kind: "pointer", x, y, button: e.button === 2 ? "right" : "left" })
      }}
      onWheel={(e) => {
        const { x, y } = toFraction(e)
        emitInput({ kind: "wheel", x, y, dy: e.deltaY, dx: e.deltaX })
      }}
      onKeyDown={(e) => {
        // Page-level key only. Text entry is echoed char-by-char as `text`
        // events so the typed value is EPHEMERAL (REQ-14 AC4) — it is never
        // stored in this component.
        if (!interactive) return
        // The key belongs to the page, not to the app (Tab must not move app
        // focus, Backspace must not navigate).
        e.preventDefault()
        if (e.key.length === 1) {
          emitInput({ kind: "text", text: e.key })
        } else {
          emitInput({ kind: "key", key: e.key })
        }
      }}
    >
      {frame?.bytes ? (
        <img
          src={`data:image/${frame.format || "jpeg"};base64,${frame.bytes}`}
          alt="Live browser takeover"
          draggable={false}
          style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
        />
      ) : (
        <div
          className="flex items-center justify-center text-[10px] font-mono text-white/70"
          style={{ width: "100%", height: "100%" }}
        >
          waiting for live frames…
        </div>
      )}
    </div>
  )
}
