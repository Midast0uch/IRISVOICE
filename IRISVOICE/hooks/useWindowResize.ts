'use client'
/**
 * useWindowResize — Tauri window sizing for IRIS wing expansion.
 *
 * When ChatView / DashboardWing open, the Tauri window grows to accommodate
 * their 2× widths.  The orb occupies the original 680 px "home" column;
 * each wing adds its own width on top.
 *
 * Chat wing is on the LEFT side of the orb.  To keep the orb at the same
 * screen X position after expanding for chat, the window shifts LEFT by the
 * chat panel width (equal and opposite).  Dashboard expands rightward —
 * no X shift needed.
 *
 * Window widths by state  (orb=680 + wings, all in logical pixels):
 *   IDLE                          →   680
 *   CHAT_OPEN  balanced           →  1190  (xOffset −510)
 *   CHAT_OPEN  chat-spotlight     →  1360  (xOffset −680)
 *   DASHBOARD_OPEN  balanced/spt  →  1240 / 1440
 *   BOTH_OPEN  balanced           →  1750  (xOffset −510)
 *   BOTH_OPEN  chat-spotlight     →  1720  (xOffset −680)
 *   BOTH_OPEN  dash-spotlight     →  1800  (xOffset −360)
 */

import { useEffect, useRef, useCallback } from 'react'
import { isTauri } from '@/hooks/useDeepLink'

// ── Wing widths (2× from original CSS values) ──────────────────────────────
const CHAT_W = { balanced: 510, spotlight: 680, background: 360 } as const
const DASH_W = { balanced: 560, spotlight: 760, background: 360 } as const
const ORB_W  = 680
const WIN_H  = 680

// ── String values from the UILayoutState / SpotlightState enums ────────────
// (mirror the enum string values so this file can remain decoupled)
type UIStr       = 'idle' | 'chat_open' | 'dashboard_open' | 'both_open'
type SpotlightStr = 'balanced' | 'chatSpotlight' | 'dashboardSpotlight'

interface Dims { width: number; xOffset: number }

function computeDims(ui: UIStr, spotlight: SpotlightStr): Dims {
  if (ui === 'idle') return { width: ORB_W, xOffset: 0 }

  const chatOpen      = ui === 'chat_open'      || ui === 'both_open'
  const dashboardOpen = ui === 'dashboard_open' || ui === 'both_open'

  const chatW = !chatOpen ? 0
    : spotlight === 'chatSpotlight'      ? CHAT_W.spotlight
    : spotlight === 'dashboardSpotlight' ? CHAT_W.background
    : CHAT_W.balanced

  const dashW = !dashboardOpen ? 0
    : spotlight === 'dashboardSpotlight' ? DASH_W.spotlight
    : spotlight === 'chatSpotlight'      ? DASH_W.background
    : DASH_W.balanced

  return {
    width  : ORB_W + chatW + dashW,
    xOffset: -chatW,   // shift LEFT when chat is visible so orb stays on screen
  }
}

// ── Hook ───────────────────────────────────────────────────────────────────
export function useWindowResize() {
  // Capture initial screen position once (logical pixels).
  const baseXRef = useRef<number | null>(null)
  const baseYRef = useRef<number | null>(null)

  useEffect(() => {
    if (!isTauri()) return
    ;(async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window')
        const pos    = await getCurrentWindow().outerPosition()
        const factor = window.devicePixelRatio || 1
        baseXRef.current = pos.x / factor
        baseYRef.current = pos.y / factor
      } catch {
        // Non-fatal: resize won't fire but app still works
      }
    })()
  }, [])

  const resize = useCallback(
    async (ui: UIStr, spotlight: SpotlightStr) => {
      if (!isTauri()) return
      if (baseXRef.current === null || baseYRef.current === null) return

      const { width, xOffset } = computeDims(ui, spotlight)
      const targetX = baseXRef.current + xOffset
      const targetY = baseYRef.current

      try {
        const { getCurrentWindow }  = await import('@tauri-apps/api/window')
        const { LogicalSize, LogicalPosition } = await import('@tauri-apps/api/dpi')
        const win = getCurrentWindow()
        // Move first so the window expands from the correct visual edge
        await win.setPosition(new LogicalPosition(targetX, targetY))
        await win.setSize(new LogicalSize(width, WIN_H))
      } catch {
        // Non-fatal
      }
    },
    []
  )

  return { resize }
}
