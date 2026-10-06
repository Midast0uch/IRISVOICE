"use client"

/**
 * The spine's gutter: the left 30 px of the timeline.
 *   hover (or keyboard focus)  -> a panel listing the turns of this strand,
 *                                 the turns in view highlighted, a knot tagged "from outside"
 *   click a turn               -> onChipClick(messageId) (chat-view's handleChipClick scrolls to it)
 *   drag on the gutter         -> scrubs the scroll position (onScrub gets the 0..1 fraction)
 * This replaces the ConversationChips button that lived in the composer footer.
 */
import React, { useCallback, useEffect, useRef, useState } from "react"
import { brandColors, brandFrom, chipsInView, knotColor, type SpineChip } from "./spineModel"

export const GUTTER_W = 30
const OPEN_DELAY_MS = 140

export interface SpineGutterProps {
  chips: SpineChip[]
  glowColor: string
  /** The scroll area: read for the turns in view. */
  containerRef: React.RefObject<HTMLElement | null>
  onChipClick: (messageId: string) => void
  /** Fraction 0..1 of the gutter height under the pointer while dragging. */
  onScrub: (fraction: number) => void
}

export function SpineGutter({ chips, glowColor, containerRef, onChipClick, onScrub }: SpineGutterProps) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState({ top: 0, h: 0 })
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const scrubbing = useRef(false)
  const gutterRef = useRef<HTMLDivElement>(null)
  const brand = brandFrom(glowColor)
  const [c1] = brandColors(brand)

  const readView = useCallback(() => {
    const el = containerRef.current
    if (el) setView({ top: el.scrollTop, h: el.clientHeight })
  }, [containerRef])

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }
  const show = () => {
    clearTimer()
    readView()
    setOpen(true)
  }
  const hide = () => {
    clearTimer()
    setOpen(false)
  }
  useEffect(() => clearTimer, [])

  // While the list is open, keep the "in view" highlight following the scroll (one read per scroll event).
  useEffect(() => {
    const el = containerRef.current
    if (!open || !el) return
    el.addEventListener("scroll", readView, { passive: true })
    return () => el.removeEventListener("scroll", readView)
  }, [open, containerRef, readView])

  const scrub = (clientY: number) => {
    const r = gutterRef.current?.getBoundingClientRect()
    if (!r || r.height <= 0) return
    onScrub((clientY - r.top) / r.height)
  }

  const here = chipsInView(chips, view.top, view.h)

  return (
    <div
      data-spine-gutter-wrap
      onMouseLeave={hide}
      style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: GUTTER_W, pointerEvents: "none" }}
    >
      <div
        ref={gutterRef}
        data-testid="spine-gutter"
        role="group"
        aria-label="Turns of this strand. Hover for the list, drag to scrub."
        tabIndex={0}
        title="Hover for the turns of this strand; drag to scrub"
        onMouseEnter={() => {
          clearTimer()
          timer.current = setTimeout(show, OPEN_DELAY_MS)
        }}
        onFocus={show}
        onKeyDown={(e) => {
          if (e.key === "Escape") hide()
        }}
        onPointerDown={(e) => {
          scrubbing.current = true
          try {
            e.currentTarget.setPointerCapture?.(e.pointerId)
          } catch {
            /* a pointer that is already gone: the drag just does not capture */
          }
          scrub(e.clientY)
        }}
        onPointerMove={(e) => {
          if (scrubbing.current) scrub(e.clientY)
        }}
        onPointerUp={() => {
          scrubbing.current = false
        }}
        onPointerCancel={() => {
          scrubbing.current = false
        }}
        style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: GUTTER_W, pointerEvents: "auto", cursor: "ns-resize", outline: "none", touchAction: "none" }}
      />
      {open && (
        <div
          data-testid="spine-chips"
          role="group"
          aria-label="Turns in this strand"
          style={{
            position: "absolute",
            left: GUTTER_W,
            top: 8,
            maxHeight: "72%",
            width: 224,
            overflowY: "auto",
            pointerEvents: "auto",
            padding: 6,
            borderRadius: 10,
            background: "rgba(8,9,18,0.96)",
            border: `1px solid ${c1.replace(/,1\)$/, ",0.3)")}`,
            boxShadow: "0 16px 40px rgba(0,0,0,0.6)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            scrollbarWidth: "none",
            zIndex: 30,
          }}
        >
          <div className="text-[9px] font-mono uppercase" style={{ letterSpacing: "0.12em", color: "rgba(255,255,255,0.4)", padding: "2px 6px 6px" }}>
            Turns in this strand
          </div>
          {chips.length === 0 && (
            <div className="text-[11px]" style={{ color: "rgba(255,255,255,0.4)", padding: 6 }}>
              No turns yet.
            </div>
          )}
          {chips.map((chip, i) => {
            const dot = chip.knot ? knotColor(brand, chip.knot) : c1
            return (
              <button
                key={`${chip.messageId}-${i}`}
                type="button"
                data-chip-index={i}
                data-here={here[i] ? "true" : "false"}
                onClick={() => {
                  hide()
                  onChipClick(chip.messageId)
                }}
                className="flex w-full items-center gap-2 text-left text-[11.5px]"
                style={{
                  padding: "6px 8px",
                  borderRadius: 6,
                  border: 0,
                  cursor: "pointer",
                  background: here[i] ? "rgba(255,255,255,0.07)" : "transparent",
                  color: here[i] ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.6)",
                }}
              >
                <i aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: dot, flex: "none", opacity: here[i] ? 1 : 0.55 }} />
                <span className="flex-1 min-w-0 truncate">{chip.label}</span>
                {chip.knot && (
                  <small className="flex-none text-[9.5px]" style={{ color: dot }}>
                    from outside
                  </small>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default SpineGutter
