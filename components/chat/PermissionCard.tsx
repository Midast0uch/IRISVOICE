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
 * Orbital (borderless) treatment: glowing action core + the requested tool as
 * the action badge (derived from the agent's request, never hardcoded). Glow
 * tracks the brand color (XurOrb).
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

  useEffect(() => {
    if (timeLeft <= 0) return
    const timer = setInterval(() => {
      setTimeLeft((t) => Math.max(0, t - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [timeLeft])

  const handleApprove = useCallback(() => {
    if (requiresConfirmation && !showConfirm) {
      setShowConfirm(true)
      return
    }
    onApprove(requestId)
  }, [requiresConfirmation, showConfirm, onApprove, requestId])

  const handleConfirm = useCallback(() => {
    onConfirm(requestId)
  }, [onConfirm, requestId])

  const handleDeny = useCallback(() => {
    onDeny(requestId)
  }, [onDeny, requestId])

  const tierCfg = TIER_CONFIG[tier] || TIER_CONFIG.side_effect
  const minutes = Math.floor(timeLeft / 60)
  const seconds = timeLeft % 60
  const paramEntries = Object.entries(params || {}).filter(
    ([, v]) => v !== undefined && v !== null
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-2 w-full"
    >
      {/* Header: action core + tool badge + tier + timer */}
      <div className="flex items-center gap-2.5 mb-2.5">
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
        <span
          className="px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
          style={{
            color: glowColor,
            backgroundColor: `${glowColor}1a`,
            border: `1px solid ${glowColor}30`,
          }}
        >
          {toolName.toUpperCase()}
        </span>
        <span
          className="text-[9px] font-semibold uppercase tracking-wide"
          style={{ color: tierCfg.color }}
        >
          {tierCfg.label}
        </span>
        <div
          className="ml-auto flex items-center gap-1 text-[9px] tabular-nums"
          style={{
            color:
              timeLeft <= 10 ? "rgba(239,68,68,0.8)" : "rgba(255,255,255,0.3)",
          }}
        >
          <Clock size={9} />
          {minutes}:{seconds.toString().padStart(2, "0")}
        </div>
      </div>

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
    </motion.div>
  )
}
