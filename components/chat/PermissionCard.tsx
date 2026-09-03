"use client"

import React, { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  ShieldCheck,
  ShieldAlert,
  CheckCircle,
  X,
  Clock,
  AlertTriangle,
} from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { CardChassis, ChassisBadge } from "@/components/chat/CardChassis"

export type PermissionTier = "read_only" | "side_effect" | "destructive"

export interface PermissionCardProps {
  requestId: string
  toolName: string
  tier: PermissionTier
  params: Record<string, unknown>
  description?: string
  timeoutSeconds?: number
  requiresConfirmation?: boolean
  onApprove: (id: string) => void
  onDeny: (id: string) => void
  onConfirm: (id: string) => void
}

const TIER_CONFIG = {
  read_only: {
    label: "Read Only",
    color: "#34d399",
    icon: ShieldCheck,
    confirmLabel: "Approve",
  },
  side_effect: {
    label: "Side Effect",
    color: "#fbbf24",
    icon: ShieldAlert,
    confirmLabel: "Allow",
  },
  destructive: {
    label: "Destructive",
    color: "#f87171",
    icon: AlertTriangle,
    confirmLabel: "Confirm",
  },
} as const

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean")
    return String(value)
  if (Array.isArray(value)) return value.join(", ")
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/**
 * PermissionCard — inline tool-approval UI in the chat stream.
 * T11 (REQ-2): rendered on the shared Liquid Ink `CardChassis` so it reads as
 * part of the same chat-stream system as the task/question/document cards.
 * The tier drives the accent vein colour (REQ-2 AC2) — the card's role is
 * expressed through the chassis, not a separate borderless "orbital" surface.
 * Glowing action core + tool badge (derived from the agent's request, never
 * hardcoded) still track the brand colour (XurOrb), unchanged.
 */
export function PermissionCard({
  requestId,
  toolName,
  tier,
  params,
  description,
  timeoutSeconds = 30,
  requiresConfirmation = false,
  onApprove,
  onDeny,
  onConfirm,
}: PermissionCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"

  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  const [showConfirm, setShowConfirm] = useState(false)
  // Session 248: optimistic local resolution. The backend round-trip
  // (grant -> broadcast -> iris:permission_granted) removes this card, but
  // the user must SEE the click land immediately — during a running DER
  // turn that round-trip can take seconds. Also swallows the rapid
  // re-clicks observed live (7 duplicate grants for one request).
  const [localAction, setLocalAction] = useState<"granted" | "denied" | null>(
    null
  )

  useEffect(() => {
    if (timeLeft <= 0 || localAction) return
    const timer = setInterval(() => {
      setTimeLeft((t) => Math.max(0, t - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [timeLeft, localAction])

  const handleApprove = useCallback(() => {
    if (localAction) return
    if (requiresConfirmation && !showConfirm) {
      setShowConfirm(true)
      return
    }
    setLocalAction("granted")
    onApprove(requestId)
  }, [localAction, requiresConfirmation, showConfirm, onApprove, requestId])

  const handleConfirm = useCallback(() => {
    if (localAction) return
    setLocalAction("granted")
    onConfirm(requestId)
  }, [localAction, onConfirm, requestId])

  const handleDeny = useCallback(() => {
    if (localAction) return
    setLocalAction("denied")
    onDeny(requestId)
  }, [localAction, onDeny, requestId])

  const tierCfg = TIER_CONFIG[tier] || TIER_CONFIG.side_effect
  const resolved =
    localAction === "granted" ? (
      <span className="flex items-center gap-1 text-[10px] font-mono text-emerald-400">
        <CheckCircle size={11} /> {localAction === "granted" ? "ALLOWED" : ""}
      </span>
    ) : localAction === "denied" ? (
      <span className="flex items-center gap-1 text-[10px] font-mono text-red-400">
        <X size={11} /> DENIED
      </span>
    ) : null
  const minutes = Math.floor(timeLeft / 60)
  const seconds = timeLeft % 60
  const paramEntries = Object.entries(params || {}).filter(
    ([, v]) => v !== undefined && v !== null
  )

  return (
    <CardChassis
      veinColor={tierCfg.color}
      isActive={timeLeft > 0}
      collapsible={false}
      aria-label={`Permission request: ${toolName}`}
      header={
        <>
          {/* Action core — glowing brand-color node, unchanged from the
              orbital treatment. */}
          <span
            className="relative shrink-0"
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: `radial-gradient(circle at 35% 30%, #aef3ff, ${glowColor} 60%, #006b8a)`,
              boxShadow: `0 0 10px ${glowColor}, inset 0 0 4px rgba(255,255,255,0.6)`,
            }}
          />
          {/* Tool badge — was 9px; a tool name carries meaning (which tool is
              asking), so it moves to the chassis's 10px meaning floor
              (Decision 15) via ChassisBadge. */}
          <ChassisBadge
            color={glowColor}
            background={`${glowColor}1a`}
            border={`1px solid ${glowColor}30`}
          >
            {toolName}
          </ChassisBadge>
          {/* Tier label — same reasoning: read_only/side_effect/destructive
              is meaning, not chrome, so 9px -> 10px. */}
          <span
            className="text-[10px] font-semibold uppercase tracking-wide shrink-0"
            style={{ color: tierCfg.color }}
          >
            {tierCfg.label}
          </span>
          {/* Timer stays at 9px — chrome, per the same de-emphasized-timer
              precedent CardChassis documents for TaskListCard's footnote. */}
          <div
            className="ml-auto flex items-center gap-1 text-[9px] tabular-nums shrink-0"
            style={{
              color:
                timeLeft <= 10 ? "rgba(239,68,68,0.8)" : "rgba(255,255,255,0.3)",
            }}
          >
            <Clock size={9} />
            {minutes}:{seconds.toString().padStart(2, "0")}
          </div>
        </>
      }
    >
      {description && (
        <p className="text-[11px] leading-snug mb-2" style={{ color: "rgba(255,255,255,0.85)" }}>
          {description}
        </p>
      )}

      {paramEntries.length > 0 && (
        <div className="flex flex-col gap-1 mb-2">
          {paramEntries.slice(0, 4).map(([k, v]) => (
            <div key={k} className="flex items-start gap-2 text-[10px]">
              <span
                className="font-mono uppercase tracking-wide shrink-0 w-20 truncate"
                style={{ color: "rgba(255,255,255,0.4)" }}
              >
                {k}
              </span>
              <span
                className="font-mono break-words flex-1"
                style={{ color: "rgba(255,255,255,0.7)" }}
              >
                {formatValue(v)}
              </span>
            </div>
          ))}
          {paramEntries.length > 4 && (
            <span className="text-[9px]" style={{ color: "rgba(255,255,255,0.3)" }}>
              +{paramEntries.length - 4} more
            </span>
          )}
        </div>
      )}

      <AnimatePresence mode="wait">
        {showConfirm ? (
          <motion.div
            key="confirm"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="flex items-center gap-2"
          >
            <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.6)" }}>
              Confirm {tierCfg.label.toLowerCase()} action?
            </span>
            <button
              type="button"
              onClick={handleConfirm}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold transition-colors"
              style={{
                color: "#05060c",
                backgroundColor: tierCfg.color,
              }}
            >
              <CheckCircle size={11} />
              {tierCfg.confirmLabel}
            </button>
            <button
              type="button"
              onClick={handleDeny}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold"
              style={{ color: "rgba(255,255,255,0.6)", border: "1px solid rgba(255,255,255,0.15)" }}
            >
              <X size={11} />
              Cancel
            </button>
          </motion.div>
        ) : (
          <motion.div
            key="actions"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="flex items-center gap-2"
          >
            <button
              type="button"
              onClick={handleApprove}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold transition-colors"
              style={{
                color: "#05060c",
                backgroundColor: tierCfg.color,
              }}
            >
              <CheckCircle size={11} />
              {tierCfg.confirmLabel}
            </button>
            <button
              type="button"
              onClick={handleDeny}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold"
              style={{ color: "rgba(255,255,255,0.6)", border: "1px solid rgba(255,255,255,0.15)" }}
            >
              <X size={11} />
              Deny
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </CardChassis>
  )
}
