"use client"

import React, { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Shield, ShieldCheck, ShieldAlert, CheckCircle, X, Clock, Terminal, AlertTriangle } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"

// ── Types ────────────────────────────────────────────────────────────────

export type PermissionTier = "read_only" | "side_effect" | "destructive"

export interface PermissionCardProps {
  requestId: string
  toolName: string
  tier: PermissionTier
  params?: Record<string, unknown>
  description?: string
  timeoutSeconds: number
  requiresConfirmation?: boolean
  onApprove: (requestId: string) => void
  onDeny: (requestId: string) => void
  onConfirm?: (requestId: string) => void
}

// ── Constants ─────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<PermissionTier, {
  label: string
  color: string
  bgColor: string
  icon: React.ReactNode
}> = {
  read_only: {
    label: "Read Only",
    color: "#3b82f6",
    bgColor: "rgba(59, 130, 246, 0.12)",
    icon: <ShieldCheck size={11} />,
  },
  side_effect: {
    label: "Side Effect",
    color: "#f59e0b",
    bgColor: "rgba(245, 158, 11, 0.12)",
    icon: <AlertTriangle size={11} />,
  },
  destructive: {
    label: "Destructive",
    color: "#ef4444",
    bgColor: "rgba(239, 68, 68, 0.12)",
    icon: <ShieldAlert size={11} />,
  },
}

type Step = "approve" | "confirm"

// ── Component ─────────────────────────────────────────────────────────────

export function PermissionCard({
  requestId,
  toolName,
  tier,
  params,
  description,
  timeoutSeconds,
  requiresConfirmation = false,
  onApprove,
  onDeny,
  onConfirm,
}: PermissionCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"
  const [step, setStep] = useState<Step>("approve")
  const [confirmed, setConfirmed] = useState(false)
  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  const [expired, setExpired] = useState(false)
  const [resolved, setResolved] = useState<"approved" | "denied" | null>(null)

  const tierCfg = TIER_CONFIG[tier]

  // ── Countdown timer ──────────────────────────────────────────────────
  useEffect(() => {
    if (resolved) return
    if (timeLeft <= 0) {
      setExpired(true)
      setResolved("denied")
      onDeny(requestId)
      return
    }
    const id = setTimeout(() => setTimeLeft((t) => t - 1), 1000)
    return () => clearTimeout(id)
  }, [timeLeft, resolved, requestId, onDeny])

  // ── Handlers ─────────────────────────────────────────────────────────
  const handleApprove = useCallback(() => {
    if (requiresConfirmation) {
      setStep("confirm")
    } else {
      setResolved("approved")
      onApprove(requestId)
    }
  }, [requiresConfirmation, requestId, onApprove])

  const handleConfirm = useCallback(() => {
    setConfirmed(true)
    setResolved("approved")
    onConfirm?.(requestId)
    onApprove(requestId)
  }, [requestId, onConfirm, onApprove])

  const handleDeny = useCallback(() => {
    setResolved("denied")
    onDeny(requestId)
  }, [requestId, onDeny])

  // ── Format params for display ────────────────────────────────────────
  const paramEntries = params
    ? Object.entries(params).slice(0, 4)
    : []
  const paramsTruncated = params ? Object.keys(params).length > 4 : false

  // ── Format time ──────────────────────────────────────────────────────
  const minutes = Math.floor(timeLeft / 60)
  const seconds = timeLeft % 60

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-3 w-full"
    >
      <div
        className="rounded-xl overflow-hidden"
        style={{
          background: "linear-gradient(135deg, rgba(10,11,22,0.96) 0%, rgba(15,16,28,0.98) 100%)",
          border: `1px solid ${tierCfg.color}20`,
          boxShadow: `
            inset 0 1px 1px rgba(255,255,255,0.04),
            inset 0 -1px 1px rgba(0,0,0,0.5),
            0 0 0 1px rgba(0,0,0,0.6),
            0 4px 20px rgba(0,0,0,0.4)
          `,
        }}
      >
        {/* Edge fresnel */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `
              linear-gradient(90deg, ${tierCfg.color}06 0%, transparent 20%, transparent 80%, ${tierCfg.color}06 100%),
              linear-gradient(0deg, ${tierCfg.color}04 0%, transparent 20%, transparent 80%, ${tierCfg.color}04 100%)
            `,
            borderRadius: "12px",
          }}
        />

        <div className="relative p-3">
          {/* Header: tier badge + tool name + timer */}
          <div className="flex items-center gap-2 mb-2.5">
            {/* Tier badge */}
            <div
              className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
              style={{
                color: tierCfg.color,
                backgroundColor: tierCfg.bgColor,
                border: `1px solid ${tierCfg.color}30`,
              }}
            >
              {tierCfg.icon}
              {tierCfg.label}
            </div>

            {/* Tool name */}
            <span
              className="text-[11px] font-mono font-medium truncate"
              style={{ color: "rgba(255,255,255,0.7)" }}
            >
              {toolName}
            </span>

            {/* Timer */}
            <div className="ml-auto flex items-center gap-1 text-[9px] tabular-nums"
              style={{
                color: timeLeft <= 10 ? "rgba(239,68,68,0.8)" : "rgba(255,255,255,0.3)",
              }}
            >
              <Clock size={9} />
              {minutes}:{seconds.toString().padStart(2, "0")}
            </div>
          </div>

          {/* Description / prompt */}
          {description && (
            <p className="text-[11px] leading-relaxed mb-2"
              style={{ color: "rgba(255,255,255,0.55)" }}>
              {description}
            </p>
          )}

          {/* Params preview */}
          {paramEntries.length > 0 && (
            <div
              className="mb-2.5 p-2 rounded-lg overflow-hidden"
              style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.06)",
              }}
            >
              <div className="text-[8px] font-semibold tracking-wide uppercase mb-1"
                style={{ color: "rgba(255,255,255,0.25)" }}>
                Parameters
              </div>
              <div className="space-y-0.5">
                {paramEntries.map(([key, val]) => (
                  <div key={key} className="flex gap-2 text-[9px] font-mono">
                    <span style={{ color: "rgba(255,255,255,0.3)" }}>{key}:</span>
                    <span className="truncate" style={{ color: "rgba(255,255,255,0.5)" }}>
                      {typeof val === "string" ? (val.length > 60 ? val.slice(0, 60) + "..." : val) : JSON.stringify(val)}
                    </span>
                  </div>
                ))}
                {paramsTruncated && (
                  <span className="text-[8px]" style={{ color: "rgba(255,255,255,0.2)" }}>
                    +{Object.keys(params!).length - 4} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Step: approve or confirm */}
          <AnimatePresence mode="wait">
            {resolved ? (
              /* Resolved state */
              <motion.div
                key="resolved"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-1.5 py-1.5 text-[10px] font-medium"
                style={{
                  color: resolved === "approved" ? "#22c55e" : "rgba(239,68,68,0.8)",
                }}
              >
                {resolved === "approved" ? <CheckCircle size={12} /> : <X size={12} />}
                {resolved === "approved" ? "Approved" : expired ? "Timed out" : "Denied"}
              </motion.div>
            ) : step === "confirm" ? (
              /* Confirmation step */
              <motion.div
                key="confirm"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="flex items-center gap-2 pt-1 border-t"
                style={{ borderColor: "rgba(255,255,255,0.06)" }}
              >
                <ShieldAlert size={12} style={{ color: "#ef4444" }} />
                <span className="text-[10px] flex-1" style={{ color: "rgba(255,255,255,0.5)" }}>
                  This is a <span className="font-semibold text-red-400/80">destructive</span> operation. Are you sure?
                </span>
                <button
                  onClick={handleConfirm}
                  className="px-2.5 py-1 rounded text-[9px] font-semibold tracking-wide transition-all hover:brightness-110"
                  style={{
                    color: "#ef4444",
                    backgroundColor: "rgba(239,68,68,0.12)",
                    border: "1px solid rgba(239,68,68,0.3)",
                  }}
                >
                  Confirm
                </button>
                <button
                  onClick={handleDeny}
                  className="px-2.5 py-1 rounded text-[9px] font-semibold tracking-wide transition-all hover:brightness-110"
                  style={{
                    color: "rgba(255,255,255,0.4)",
                    backgroundColor: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.08)",
                  }}
                >
                  Cancel
                </button>
              </motion.div>
            ) : (
              /* Initial approve/deny step */
              <motion.div
                key="approve"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="flex gap-2 pt-1.5 border-t"
                style={{ borderColor: "rgba(255,255,255,0.06)" }}
              >
                {/* Deny button */}
                <button
                  onClick={handleDeny}
                  className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-[10px] font-medium tracking-wide transition-all duration-150 hover:brightness-110"
                  style={{
                    color: "rgba(255,255,255,0.5)",
                    backgroundColor: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.08)"
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.04)"
                  }}
                >
                  <X size={10} />
                  Deny
                </button>

                {/* Approve button */}
                <button
                  onClick={handleApprove}
                  className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-[10px] font-medium tracking-wide transition-all duration-150 hover:brightness-110"
                  style={{
                    color: tierCfg.color,
                    backgroundColor: `${tierCfg.color}12`,
                    border: `1px solid ${tierCfg.color}30`,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = `${tierCfg.color}20`
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = `${tierCfg.color}12`
                  }}
                >
                  <CheckCircle size={10} />
                  {requiresConfirmation ? "Approve" : "Allow"}
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  )
}
