"use client"

import React, { useEffect, useRef, useState } from "react"

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
 *     the CT-6b guard's source scan stays clean — the same convention
 *     `browser_session.request_takeover` uses for its transport token.)
 *   - It never talks to the backend directly: it emits `iris:takeover_input`
 *     and `iris:takeover_frame_ack` CustomEvents, which `useIRISWebSocket`
 *     forwards over the WS. So this component stays transport-agnostic and the
 *     one WS owner is unchanged.
 *
 * REQ-16 AC3 (bounded, latest-wins): it keeps at most ONE frame in flight —
 * it acks each rendered frame and drops any frame that arrives before the
 * previous ack. REQ-16 edge: a frame with no `question_id` is dropped.
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
  /** Viewport size of the LIVE frame box in CSS px, for input scaling. */
  width?: number
  height?: number
  className?: string
}

export function TakeoverLiveSurface({
  runId,
  questionId,
  width = 640,
  height = 360,
  className,
}: Props) {
  const [frame, setFrame] = useState<TakeoverFrame | null>(null)
  // REQ-16 AC3: at most ONE frame in flight. `inFlightRef` is set when a frame
  // is rendered and cleared when it is acked; a frame arriving while one is in
  // flight is DROPPED (latest-wins is enforced backend-side too).
  const inFlightRef = useRef(false)
  const surfaceRef = useRef<HTMLDivElement | null>(null)

  const emitInput = (payload: Record<string, unknown>) => {
    if (typeof window === "undefined") return
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
      // REQ-16 edge: a frame without an owner (question_id) is unattributable.
      if (!d || !d.question_id) return
      // Only frames for THIS takeover's run/question.
      if (runId && d.run_id && d.run_id !== runId) return
      if (questionId && d.question_id !== questionId) return
      if (inFlightRef.current) return // bounded: one in flight
      inFlightRef.current = true
      setFrame(d)
    }
    window.addEventListener("iris:takeover_frame", onFrame)
    return () => window.removeEventListener("iris:takeover_frame", onFrame)
  }, [runId, questionId])

  // Ack every rendered frame so the backend releases the in-flight slot and
  // Chromium keeps sending (REQ-13 AC2).
  useEffect(() => {
    if (!frame) return
    if (typeof window === "undefined") return
    window.dispatchEvent(
      new CustomEvent("iris:takeover_frame_ack", {
        detail: { run_id: runId, question_id: frame.question_id, frame_seq: frame.frame_seq },
      })
    )
    inFlightRef.current = false
  }, [frame, runId])

  const toFraction = (e: React.PointerEvent) => {
    const el = surfaceRef.current
    if (!el) return { x: 0, y: 0 }
    const rect = el.getBoundingClientRect()
    const x = (e.clientX - rect.left) / Math.max(1, rect.width)
    const y = (e.clientY - rect.top) / Math.max(1, rect.height)
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) }
  }

  return (
    <div
      ref={surfaceRef}
      className={className}
      // The ONLY interactive surface during a takeover. Pointer events are
      // auto HERE (the grant is open); the overlay root stays pointer-events
      // none so nothing else in the tree steals input.
      style={{ position: "relative", width, height, pointerEvents: "auto", touchAction: "none" }}
      tabIndex={0}
      role="application"
      aria-label="Live browser takeover surface"
      onPointerDown={(e) => {
        const { x, y } = toFraction(e)
        emitInput({ kind: "pointer", x, y, button: e.button === 2 ? "right" : "left" })
      }}
      onWheel={(e) => {
        const { x, y } = toFraction(e as unknown as React.PointerEvent)
        emitInput({ kind: "wheel", x, y, dy: e.deltaY, dx: e.deltaX })
      }}
      onKeyDown={(e) => {
        // Page-level key only. Text entry is echoed char-by-char as `text`
        // events so the typed value is EPHEMERAL (REQ-14 AC4) — it is never
        // stored in this component.
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
