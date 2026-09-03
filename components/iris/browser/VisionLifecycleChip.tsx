"use client"

/**
 * VisionLifecycleChip — REQ-5 (specs/vision-browser-stage, T10).
 *
 * Renders the vision server's lifecycle truth (cold | spawning | warm |
 * error) as a compact dot + label in the browser panel. Consumes the
 * EXISTING `vision_status` WS message via the `iris:vision_status`
 * CustomEvent dispatched by useIRISWebSocket — no polling, no new transport
 * (OPT GATE: one listener, renders null when idle).
 *
 * The backend emits lifecycle transitions with payload
 * { status: "lifecycle", state, reason?, trigger? } — additive on the
 * existing vision_status shape; older payloads without `state` are ignored.
 */

import React, { useEffect, useState } from "react"

type LifecycleState = "cold" | "spawning" | "warm" | "error"

const CHIP_STYLE: Record<LifecycleState, { dot: string; label: string; pulse: boolean }> = {
  cold: { dot: "#94a3b8", label: "VISION COLD", pulse: false },
  spawning: { dot: "#fbbf24", label: "VISION SPAWNING", pulse: true },
  warm: { dot: "#22c55e", label: "VISION WARM", pulse: false },
  error: { dot: "#ef4444", label: "VISION ERROR", pulse: false },
}

export function VisionLifecycleChip({ glowColor }: { glowColor?: string }) {
  const [state, setState] = useState<LifecycleState>("cold")
  const [reason, setReason] = useState("")
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const onStatus = (e: Event) => {
      const d = (e as CustomEvent<{ state?: string; reason?: string }>).detail ?? {}
      if (!d.state) return // additive field absent -> legacy payload, ignore
      const s = d.state as LifecycleState
      if (!CHIP_STYLE[s]) return
      setState(s)
      setReason(d.reason || "")
      // REQ-5 AC3: visible while active OR not cold — an error must linger.
      setVisible(s !== "cold")
    }
    window.addEventListener("iris:vision_status", onStatus as EventListener)
    return () =>
      window.removeEventListener("iris:vision_status", onStatus as EventListener)
  }, [])

  if (!visible) return null
  const style = CHIP_STYLE[state]

  return (
    <div
      className="shrink-0 flex items-center gap-1.5 px-2 h-6 rounded-full"
      title={reason || undefined}
      style={{
        background: "rgba(4,8,12,0.6)",
        border: `1px solid ${style.dot}33`,
      }}
      role="status"
      aria-live="polite"
    >
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{
          background: style.dot,
          boxShadow: style.pulse ? `0 0 6px ${style.dot}` : "none",
          animation: style.pulse ? "iris-vision-pulse 1.2s ease-in-out infinite" : undefined,
        }}
      />
      <span className="text-[8px] font-mono tracking-wider" style={{ color: `${style.dot}cc` }}>
        {style.label}
      </span>
      <style>{`
        @keyframes iris-vision-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.35; }
        }
      `}</style>
    </div>
  )
}

export default VisionLifecycleChip
