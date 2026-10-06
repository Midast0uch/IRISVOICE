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

// Session 326 (owner, live): the card read as machine speak — a raw
// `run_command` badge beside a `SIDE EFFECT` tier word. Neither tells a
// non-coder what is about to happen. Now the badge says "Permission" and the
// slot beside it names the ACTION TYPE in plain words ("Run command"). The raw
// tool name and params still render in the body (see below) so nothing is
// hidden — the header is the human verdict, the rows stay the evidence.
const TOOL_ACTION_LABELS: Record<string, string> = {
  run_command: "Run command",
  write_file: "Write file",
  edit_file: "Edit file",
  append_file: "Add to file",
  replace_in_file: "Edit file",
  patch_file: "Patch file",
  copy_file: "Copy file",
  move_file: "Move file",
  rename_file: "Rename file",
  create_directory: "Create folder",
  delete_file: "Delete file",
  read_file: "Read file",
  list_files: "List files",
  glob_files: "Find files",
  search: "Web search",
  crawler_query: "Web search",
  take_screenshot: "Take screenshot",
  gui_click: "Screen click",
  gui_type: "Screen typing",
  git_commit: "Git commit",
  git_push: "Git push",
  shutdown: "Shut down",
  lock_screen: "Lock screen",
}

/** Human action label for the badge; falls back to a neutral "Permission". */
export function actionLabel(toolName: string): string {
  const key = (toolName || "").toLowerCase()
  if (TOOL_ACTION_LABELS[key]) return TOOL_ACTION_LABELS[key]
  // Unknown tool: de-underscore and title-case so it reads as words, not a
  // code identifier ("fetch_vision" -> "Fetch vision").
  const words = key.replace(/[._]+/g, " ").trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Permission"
}

const TIER_CONFIG = {
  read_only: {
    label: "Just looking — nothing changes",
    color: "#34d399",
    icon: ShieldCheck,
    confirmLabel: "Approve",
  },
  side_effect: {
    label: "This can change things on your computer",
    color: "#fbbf24",
    icon: ShieldAlert,
    confirmLabel: "Allow",
  },
  destructive: {
    label: "This can delete or overwrite things — check twice",
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
          {/* Badge — Session 326 (owner): the card is a PERMISSION request, so
              the badge says exactly that. What kind of action it is moves to
              the tier slot beside it. */}
          <ChassisBadge
            color={glowColor}
            background={`${glowColor}1a`}
            border={`1px solid ${glowColor}30`}
          >
            Permission
          </ChassisBadge>
          {/* Action label — Session 326 (owner): names the action TYPE in plain
              words ("Run command", "Write file"), replacing the bare
              "SIDE EFFECT" tier word. The risk stays visible via the accent
              vein colour, the description line, and this label's tooltip. */}
          <span
            className="text-[10px] font-semibold tracking-wide shrink-0"
            style={{ color: tierCfg.color }}
            title={tierCfg.label}
          >
            {actionLabel(toolName)}
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
              Are you sure? This one can delete or overwrite things.
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
