"use client"

import { useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { Search } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Xur } from "@/components/Xur"
import type { TaskStep, TaskStepStatus } from "@/hooks/useTaskProgress"

export interface TaskListCardProps {
  steps: TaskStep[]
  turnId?: string
  mode?: string
  defaultCollapsed?: boolean
  planTitle?: string
  /** REQ-8: honest learning signal (avoided / retried / crystallized). */
  learningSignal?: "avoided" | "retried" | "crystallized" | null
}

const STATUS_META: Record<TaskStepStatus, { color: string; label: string }> = {
  unknown: { color: "rgba(255,255,255,0.4)", label: "Unknown" },
  pending: { color: "rgba(255,255,255,0.4)", label: "Pending" },
  working: { color: "#fbbf24", label: "Working" },
  done: { color: "#34d399", label: "Done" },
  skipped: { color: "rgba(255,255,255,0.3)", label: "Skipped" },
  vetoed: { color: "#f87171", label: "Vetoed" },
  error: { color: "#f87171", label: "Failed" },
  fail: { color: "#f87171", label: "Failed" },
}

/**
 * TaskListCard — inline agent plan/progress in the chat stream.
 * Orbital (borderless) treatment: a glowing action core + action badge, with
 * step nodes on a hairline connector. Glow tracks the brand color (XurOrb).
 * Presentational: receives `steps` from chat-view (which uses useTaskProgress).
 */
export default function TaskListCard({
  steps,
  turnId,
  mode,
  defaultCollapsed = true,
  planTitle,
  learningSignal,
}: TaskListCardProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color

  const [collapsed, setCollapsed] = useState(defaultCollapsed && steps.length > 4)
  const [expandedStep, setExpandedStep] = useState<string | null>(null)

  const doneCount = steps.filter((s) => s.status === "done").length
  const failCount = steps.filter((s) => s.status === "fail").length
  // Action-only header, derived from the agent's live tool (never "Plan").
  const headerTitle = planTitle || mode?.toUpperCase() || "TASK"

  // REQ-8: honest learning signal -> subtle Pacman OrbCanvas-style border
  // particles on the card. The signal is real state (avoided / retried /
  // crystallized), never narration. Tint follows the signal kind.
  const signalTint: Record<string, string> = {
    avoided: "#f59e0b", // amber — a step was avoided (AVOID)
    retried: "#3b82f6", // blue — split into Sub-Loops
    crystallized: "#22c55e", // green — skill captured
  }
  const signalLabel: Record<string, string> = {
    avoided: "avoided",
    retried: "retried",
    crystallized: "crystallized",
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-2 w-full"
    >
      {/* REQ-8: subtle Pacman OrbCanvas-style border particles on live
          learning signal. Absolutely positioned so it never shifts layout. */}
      {learningSignal && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-2xl"
          style={{
            border: `1px solid ${signalTint[learningSignal]}55`,
            boxShadow: `0 0 14px ${signalTint[learningSignal]}33, inset 0 0 6px ${signalTint[learningSignal]}22`,
            // slow breathing pulse — quiet, not a spinner
            animation: "irisSignalPulse 2.4s ease-in-out infinite",
          }}
        />
      )}
      {/* Header: action core (identity marker) + action badge + progress + collapse toggle */}
      <div className="flex items-center gap-2.5 mb-2.5">
        {/* W4 (T24): websearch gets a magnifying glass icon; other actions get the gradient core */}
        {headerTitle.toLowerCase().includes("websearch") ? (
          <span className="relative shrink-0 flex items-center justify-center"
            style={{
              width: 12,
              height: 12,
            }}
          >
            <Search size={10} style={{ color: glowColor }} />
          </span>
        ) : (
          <span
            className="relative shrink-0"
            style={{
              width: 12,
              height: 12,
              borderRadius: "50%",
              background: `radial-gradient(circle at 35% 30%, #aef3ff, ${glowColor} 60%, #006b8a)`,
              boxShadow: `0 0 12px ${glowColor}, inset 0 0 4px rgba(255,255,255,0.6)`,
            }}
          >
            {/* Connector from core to step list — only when steps visible */}
            {!collapsed && steps.length > 0 && (
              <span
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "100%",
                  width: 1,
                  height: 32,
                  transform: "translateX(-50%)",
                  background: `linear-gradient(${glowColor}, ${glowColor}20)`,
                }}
              />
            )}
          </span>
        )}
        <span
          className="px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
          style={{
            color: glowColor,
            backgroundColor: `${glowColor}1a`,
            border: `1px solid ${glowColor}30`,
          }}
        >
          {headerTitle.toUpperCase()}
        </span>
        <span
          className="ml-auto text-[9px] font-mono tabular-nums"
          style={{ color: "rgba(255,255,255,0.6)" }}
        >
          {doneCount}/{steps.length}
          {failCount > 0 ? ` · ${failCount}✕` : ""}
        </span>
        {/* REQ-8: honest learning-signal badge (real state, not narration) */}
        {learningSignal && (
          <span
            className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
            style={{
              color: signalTint[learningSignal],
              backgroundColor: `${signalTint[learningSignal]}1a`,
              border: `1px solid ${signalTint[learningSignal]}40`,
            }}
            title={`Learning signal: ${signalLabel[learningSignal]}`}
          >
            {signalLabel[learningSignal]}
          </span>
        )}
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

      {/* Step list — nodes on a continuous left-side hairline */}
      <AnimatePresence initial={false}>
        {!collapsed ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="relative">
              {/* Continuous vertical hairline through all step nodes — centered at 6px (matches header core center), fades at top/bottom */}
              {steps.length > 1 && (
                <div
                  style={{
                    position: "absolute",
                    left: 5.5,
                    top: 10,
                    bottom: 10,
                    width: 1,
                    background: `linear-gradient(to bottom, transparent, ${glowColor}30 4px, ${glowColor}20 calc(100% - 4px), transparent)`,
                  }}
                />
              )}
              <div className="flex flex-col gap-3">
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
                    className="flex items-start gap-2.5 w-full text-left py-0.5 hover:brightness-125"
                  >
                    {step.status === "working" ? (
                      // The active step animates. Xur reuses the same curve /
                      // particle language as the orb, so "the agent is on this
                      // one" reads at a glance without a second colour system.
                      <span
                        className="shrink-0"
                        style={{
                          marginTop: 3,
                          marginLeft: 0,
                          zIndex: 1,
                          position: "relative",
                          color: meta.color,
                        }}
                      >
                        <Xur size={12} color={meta.color} speed={1.4} />
                      </span>
                    ) : (
                      <span
                        className="shrink-0"
                        style={{
                          width: 6,
                          minWidth: 6,
                          height: 6,
                          borderRadius: "50%",
                          marginTop: 6,
                          marginLeft: 3,
                          background: "#05060c",
                          border: `1.5px solid ${meta.color}`,
                          boxShadow: `0 0 8px ${meta.color}`,
                          zIndex: 1,
                          position: "relative",
                        }}
                      />
                    )}
                    <span
                      className="text-[11px] leading-snug flex-1 break-words"
                      style={{
                        color:
                          step.status === "pending"
                            ? "rgba(255,255,255,0.45)"
                            : "rgba(255,255,255,0.9)",
                      }}
                    >
                      {step.description}
                    </span>
                    {step.toolName || step.activeDetail ? (
                      <span
                        className="text-[9px] font-mono uppercase tracking-wide shrink-0 mt-0.5 flex items-baseline gap-1 max-w-[46%] justify-end"
                        style={{ color: glowColor }}
                        title={
                          step.activeDetail
                            ? `${step.toolName || ""} — ${step.activeDetail}${
                                step.activeProgress
                                  ? ` (${step.activeProgress})`
                                  : ""
                              }`
                            : step.toolName
                        }
                      >
                        {step.toolName ? (
                          <span className="shrink-0">{step.toolName}</span>
                        ) : null}
                        {/* Live source, beside the tool rather than replacing
                            the plan text. Keyed on the detail so each new host
                            re-mounts and fades in — the "rotation". */}
                        {step.activeDetail ? (
                          <AnimatePresence mode="wait" initial={false}>
                            <motion.span
                              key={step.activeDetail}
                              initial={{ opacity: 0, y: -3 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: 3 }}
                              transition={{ duration: 0.18 }}
                              className="truncate normal-case"
                              style={{ color: "rgba(255,255,255,0.55)" }}
                            >
                              {step.activeDetail}
                              {step.activeProgress ? (
                                <span style={{ color: "rgba(255,255,255,0.35)" }}>
                                  {" "}
                                  {step.activeProgress}
                                </span>
                              ) : null}
                            </motion.span>
                          </AnimatePresence>
                        ) : null}
                      </span>
                    ) : null}
                  </button>
                  {isOpen && step.resultPreview ? (
                    <div
                      className="ml-7 mb-1 text-[9px] font-mono leading-relaxed"
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
            </div>
          </div>
        </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.div>
  )
}
