'use client'
/**
 * useWindowResize — Tauri window sizing for IRIS wing expansion.
 *
 * The native window IS the frame described in lib/orbWingGeometry: chat wing,
 * orb band, dashboard wing, and nothing spare. Every number comes from that
 * module, so the window can no longer reserve width the wings do not draw.
 *
 * Two things are held still while the window changes shape:
 *   - the ORB, which must not move on screen when a wing opens or shuts;
 *   - the user's own placement, including which monitor they dragged it to.
 * Both fall out of one rule: the window's top-left is always the orb's fixed
 * screen point minus the orb's position inside the current frame.
 */

import { useRef, useCallback } from 'react'
import { isTauri } from '@/hooks/useDeepLink'
import {
  computeFrame,
  IDLE_W,
  IDLE_H,
  type UIStr,
  type SpotlightStr,
} from '@/lib/orbWingGeometry'

// The orb's home: its centre inside the idle frame. Every other frame is
// offset so the orb lands on the same screen pixel.
const HOME_ORB_X = IDLE_W / 2
const HOME_ORB_Y = IDLE_H / 2

// ── Hook ───────────────────────────────────────────────────────────────────
export function useWindowResize() {
  // The shift CURRENTLY applied to the window (logical px), relative to the
  // idle frame. The user's own position is always `outerPosition() - applied`,
  // so it is DERIVED on every call instead of cached.
  //
  // It used to be cached once, on the first resize. That made every later
  // setPosition() teleport the window back to wherever it sat when the first
  // wing opened — so dragging the widget to a second monitor and then opening
  // or closing a wing threw it back to the first monitor. Re-reading the live
  // position keeps every drag the user makes between state changes.
  const appliedRef = useRef({ x: 0, y: 0 })

  // Serialises overlapping calls. `ui`, `spotlight` and `level` can change in
  // the same tick; two interleaved reads would both see the same pre-move
  // position and the offset bookkeeping would drift.
  const queueRef = useRef<Promise<void>>(Promise.resolve())

  const resize = useCallback(
    async (ui: UIStr, spotlight: SpotlightStr, level: number = 1) => {
      if (!isTauri()) return

      const run = queueRef.current.then(async () => {
        try {
          const { getCurrentWindow }  = await import('@tauri-apps/api/window')
          const { LogicalSize, LogicalPosition } = await import('@tauri-apps/api/dpi')
          const win = getCurrentWindow()

          const pos = await win.outerPosition()
          // Tauri's own scale factor, NOT window.devicePixelRatio. The two
          // disagree: devicePixelRatio is what WebView2 reports for the page,
          // which Windows text scaling can shift, while scaleFactor() is the
          // scale of the monitor the window is actually on. On a multi-monitor
          // setup with different DPI per screen, the wrong one converts the
          // physical position into a logical position for the wrong screen and
          // the window lands off by the ratio between them.
          const factor = (await win.scaleFactor()) || window.devicePixelRatio || 1

          // Undo the shift we are responsible for; whatever remains is where
          // the user has put the window, on whichever monitor.
          const baseX = pos.x / factor - appliedRef.current.x
          const baseY = pos.y / factor - appliedRef.current.y

          const frame = computeFrame(ui, spotlight, level)
          // Hold the orb still: the frame grows around it, never under it.
          const offsetX = HOME_ORB_X - frame.orbCenterX
          const offsetY = HOME_ORB_Y - frame.orbCenterY

          // Move first so the window expands from the correct visual edge.
          //
          // setSize sets the INNER (webview) size in Tauri v2, which is what
          // the page then measures as window.innerWidth. setPosition sets the
          // OUTER position. Mixing them is safe here because the widget window
          // is decorations:false / shadow:false, so the two rectangles are the
          // same, and because any constant frame inset cancels out — the orb
          // is held still by a DIFFERENCE of two positions, not by an absolute
          // one.
          //
          // Where the webview still ends up a fraction narrower than the size
          // requested (DPI rounding), the page absorbs it: frameLeft() centres
          // the assembly in the LIVE viewport width rather than assuming it
          // equals frame.width, so the shortfall is split evenly between the
          // two wings instead of landing on one of them.
          await win.setPosition(new LogicalPosition(baseX + offsetX, baseY + offsetY))
          await win.setSize(new LogicalSize(frame.width, frame.height))
          appliedRef.current = { x: offsetX, y: offsetY }
        } catch {
          // Non-fatal: resize fails gracefully in dev/browser mode
        }
      })

      queueRef.current = run
      await run
    },
    []
  )

  return { resize }
}
