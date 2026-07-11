"use client"

import { useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import type { TaskStep, TaskStepStatus } from "@/hooks/useTaskProgress"

export interface TaskListCardProps {
  steps: TaskStep[]
  turnId?: string
  mode?: string
  defaultCollapsed?: boolean
  planTitle?: string
}

const STATUS_META: Record<
  TaskStepStatus,
  { icon: string; color: string; label: string }
> = {
  pending: { icon: "○", color: "rgba(255,255,255,0.4)", label: "Pending" },
  working: { icon: "◐", color: "#fbbf24", label: "Working" },
  done: { icon: "✓", color: "#34d399", label: "Done" },
  skipped: { icon: "⊘", color: "rgba(255,255,255,0.3)", label: "Skipped" },
  vetoed: { icon: "⊘", color: "#f87171", label: "Vetoed" },
  fail: { icon: "✕", color: "#f87171", label: "Failed" },
}

/**
 * TaskListCard — inline agent plan/progress card in the chat stream.
 * Matches the Prism Glass aesthetic of PermissionCard / QuestionCard.
 * Presentational: receives `steps` from chat-view (which uses useTaskProgress).
 */
export default function TaskListCard({
  steps,
  turnId,
  mode,
  defaultCollapsed = true,
  planTitle,
}: TaskListCardProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color
  const shimmerPrimary = theme.shimmer.primary
  const glassBlur = theme.glass.blur
  const glassOpacity = theme.glass.opacity

  const [collapsed, setCollapsed] = useState(defaultCollapsed && steps.length > 4)
  const [expandedStep, setExpandedStep] = useState<string | null>(null)

  const doneCount = steps.filter((s) => s.status === "done").length
  const failCount = steps.filter((s) => s.status === "fail").length
  const headerTitle = planTitle || "Plan"

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-3 w-full"
    >
      <div
        className="rounded-lg overflow-hidden relative"
        style={{
          background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
          borderLeft: `2px solid ${glowColor}`,
          border: `1px solid ${glowColor}20`,
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
              linear-gradient(90deg, ${shimmerPrimary}06 0%, transparent 20%, transparent 80%, ${shimmerPrimary}06 100%),
              linear-gradient(0deg, ${shimmerPrimary}04 0%, transparent 20%, transparent 80%, ${shimmerPrimary}04 100%)
            `,
            borderRadius: "10px",
          }}
        />

        <div className="relative p-3">
          {/* Header: mode badge + progress + collapse toggle */}
          <div className="flex items-center gap-2 mb-2.5">
            <div
              className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
              style={{
                color: glowColor,
                backgroundColor: `${glowColor}1a`,
                border: `1px solid ${glowColor}30`,
              }}
            >
              {headerTitle}
            </div>
            {mode ? (
              <span
                className="text-[9px] font-mono uppercase tracking-wide"
                style={{ color: "rgba(255,255,255,0.5)" }}
              >
                {mode}
              </span>
            ) : null}
            <span
              className="ml-auto text-[9px] font-mono tabular-nums"
              style={{ color: "rgba(255,255,255,0.6)" }}
            >
              {doneCount}/{steps.length}
              {failCount > 0 ? ` · ${failCount}✕` : ""}
            </span>
            <button
              type="button"
              onClick={() => setCollapsed((c) => !c)}
              className="text-[9px] px-1.5 py-0.5 rounded hover:brightness-125"
              style={{ color: glowColor, border: `1px solid ${glowColor}30` }}
              aria-label={collapsed ? "Expand plan" : "Collapse plan"}
            >
              {collapsed ? "▸" : "▾"}
            </button>
          </div>

          {/* Step list */}
          <AnimatePresence initial={false}>
            {!collapsed ? (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden flex flex-col gap-1"
              >
                {steps.map((step, i) => {
                  const meta = STATUS_META[step.status]
                  const isOpen = expandedStep === step.id
                  return (
                    <div key={step.id ?? i} className="flex flex-col">
                      <button
                        type="button"
                        onClick={() =>
                          step.resultPreview
                            ? setExpandedStep(isOpen ? null : step.id)
                            : undefined
                        }
                        className="flex items-center gap-2 w-full text-left py-0.5 hover:brightness-125"
                      >
                        <span
                          className="text-[11px] font-mono w-4 text-center"
                          style={{ color: meta.color }}
                        >
                          {meta.icon}
                        </span>
                        <span
                          className="text-[11px] font-mono truncate flex-1"
                          style={{
                            color:
                              step.status === "pending"
                                ? "rgba(255,255,255,0.45)"
                                : "rgba(255,255,255,0.85)",
                          }}
                        >
                          {step.description}
                        </span>
                        {step.toolName ? (
                          <span
                            className="text-[9px] font-mono uppercase tracking-wide shrink-0"
                            style={{ color: glowColor }}
                          >
                            {step.toolName}
                          </span>
                        ) : null}
                      </button>
                      {isOpen && step.resultPreview ? (
                        <div
                          className="ml-6 mb-1 text-[9px] font-mono leading-relaxed"
                          style={{
                            color: "rgba(255,255,255,0.55)",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {step.resultPreview}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  )
}
