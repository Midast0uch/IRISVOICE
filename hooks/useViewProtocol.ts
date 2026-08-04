"use client"

/**
 * useViewProtocol — REQ-4 AC1-AC5 (T9/T10/T11) parent side of the view protocol.
 *
 * The frame is sandboxed to an opaque origin; its postMessage arrives with
 * origin === "null", so the parent CANNOT authenticate by origin. REQ-4 AC4
 * requires BOTH checks, either alone is insufficient:
 *   1. event.source === iframe.contentWindow (frame reference)
 *   2. payload shape === the fixed view-protocol shape, v === 1
 *
 * Messages that pass both checks are surfaced via `iris:view_state`
 * CustomEvents (kind: ready|scroll) so the overlay / panel can consume them
 * without the parent ever reaching INTO the frame. Degradation (REQ-4 AC5):
 * if the injected script is stripped, no messages arrive and the parent simply
 * sees nothing — it never throws, and the overlay falls back to coarse states.
 *
 * The hook also exposes sendScrollTo / sendHighlight — the ONLY two commands
 * the parent may send IN (fixed shapes; the frame validates them).
 */

import { useCallback, useEffect, useRef } from "react"

export interface ViewState {
  kind: "ready" | "scroll"
  top: number
  height: number
  viewport: number
}

const VIEW_PROTOCOL_VERSION = 1

/** Shape gate: must be a view message of the fixed protocol, version 1.
 *  kind:"scroll" => top+height+viewport all numeric.
 *  kind:"ready"  => height numeric (top/viewport may be absent). */
export function isViewMessage(data: unknown): data is ViewState & { __iris: string } {
  if (!data || typeof data !== "object") return false
  const m = data as Record<string, unknown>
  if (m.__iris !== "view") return false
  if (m.v !== VIEW_PROTOCOL_VERSION) return false
  if (m.kind === "ready") {
    return typeof m.height === "number"
  }
  if (m.kind === "scroll") {
    return (
      typeof m.top === "number" &&
      typeof m.height === "number" &&
      typeof m.viewport === "number"
    )
  }
  return false
}

export function useViewProtocol(iframeRef: React.RefObject<HTMLIFrameElement | null>) {
  const lastSeen = useRef<ViewState | null>(null)

  const send = useCallback(
    (kind: "scrollTo" | "highlight", payload: Record<string, unknown>) => {
      const win = iframeRef.current?.contentWindow
      if (!win) return
      try {
        win.postMessage({ __iris: "cmd", v: VIEW_PROTOCOL_VERSION, kind, ...payload }, "*")
      } catch {
        /* never throw into the panel */
      }
    },
    [iframeRef],
  )

  const sendScrollTo = useCallback(
    (top: number, smooth = false) => send("scrollTo", { top, smooth }),
    [send],
  )
  const sendHighlight = useCallback(
    (rects: Array<{ x: number; y: number; w: number; h: number }>) =>
      send("highlight", { rects }),
    [send],
  )

  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      // CHECK 1 — frame reference. An opaque-origin frame cannot be
      // authenticated by origin, so the source must BE our contentWindow.
      if (ev.source !== iframeRef.current?.contentWindow) return
      // CHECK 2 — shape. Anything not matching the fixed protocol is dropped.
      if (!isViewMessage(ev.data)) return

      const state: ViewState = {
        kind: ev.data.kind,
        top: typeof ev.data.top === "number" ? ev.data.top : 0,
        height: typeof ev.data.height === "number" ? ev.data.height : 0,
        viewport: typeof ev.data.viewport === "number" ? ev.data.viewport : 0,
      }
      lastSeen.current = state
      window.dispatchEvent(
        new CustomEvent<ViewState>("iris:view_state", { detail: state }),
      )
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [iframeRef])

  return { sendScrollTo, sendHighlight, lastSeen }
}
