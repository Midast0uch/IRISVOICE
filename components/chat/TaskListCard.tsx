"use client"

import { useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { Search, ChevronDown } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Xur } from "@/components/Xur"
import type { TaskStep, TaskStepStatus } from "@/hooks/useTaskProgress"
import { toolLabel } from "@/hooks/useTaskProgress"

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
      className="my-3 w-full"
    >
      {/* The plan card sat as bare text directly on the chat background while
          every document beside it was a glass panel, so a turn read as one
          finished card plus some loose floating rows. Same surface, same radius,
          same accent rail as RichDocument — the two now belong to one system.
          `relative` is also load-bearing: the learning-signal ring below is
          `absolute inset-0` and had no positioned ancestor here, so it escaped
          the card and drew against the whole message column. */}
      <div
        className="relative rounded-xl px-3 py-2.5"
        style={{
          background:
            "linear-gradient(140deg, rgba(12,13,24,0.55) 0%, rgba(16,17,30,0.62) 100%)",
          border: `1px solid ${glowColor}1a`,
          borderLeft: `2px solid ${glowColor}66`,
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 4px 18px rgba(0,0,0,0.35)",
        }}
      >
      {/* REQ-8: subtle Pacman OrbCanvas-style border particles on live
          learning signal. Absolutely positioned so it never shifts layout. */}
      {learningSignal && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-xl"
          style={{
            border: `1px solid ${signalTint[learningSignal]}55`,
            boxShadow: `0 0 14px ${signalTint[learningSignal]}33, inset 0 0 6px ${signalTint[learningSignal]}22`,
            // slow breathing pulse — quiet, not a spinner
            animation: "irisSignalPulse 2.4s ease-in-out infinite",
          }}
        />
      )}
      {/* Header: action core (identity marker) + action badge + progress + collapse toggle */}
      <div className="relative flex items-center gap-2.5 mb-2.5">
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
          className="px-1.5 py-[3px] rounded text-[9px] font-semibold tracking-[0.12em] uppercase leading-none"
          style={{
            color: glowColor,
            backgroundColor: `${glowColor}14`,
            border: `1px solid ${glowColor}33`,
          }}
        >
          {headerTitle.toUpperCase()}
        </span>

        {/* Progress rail. A bare "2/5" made the reader do the arithmetic to
            find out how far along a run was; the bar states it directly, and
            failures take their share of it in red instead of hiding behind a
            "·2✕" suffix. */}
        {steps.length > 0 && (
          <span
            className="ml-auto h-[3px] rounded-full overflow-hidden flex shrink-0"
            style={{ width: 56, background: "rgba(255,255,255,0.08)" }}
            aria-hidden
          >
            <span
              style={{
                width: `${(doneCount / steps.length) * 100}%`,
                background: glowColor,
                transition: "width 0.35s cubic-bezier(0.22,1,0.36,1)",
              }}
            />
            <span
              style={{
                width: `${(failCount / steps.length) * 100}%`,
                background: "#f87171",
                transition: "width 0.35s cubic-bezier(0.22,1,0.36,1)",
              }}
            />
          </span>
        )}
        <span
          className={`text-[9px] font-mono tabular-nums${steps.length > 0 ? "" : " ml-auto"}`}
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
          className="shrink-0 p-1 rounded transition-all duration-150 hover:brightness-125 flex items-center justify-center"
          style={{ color: glowColor, border: `1px solid ${glowColor}30` }}
          aria-label={collapsed ? "Expand plan" : "Collapse plan"}
        >
          {/* The ▸/▾ glyphs render at different heights across fonts, so the
              header shifted by a pixel on every toggle. One icon, rotated. */}
          <ChevronDown
            size={10}
            style={{
              transform: collapsed ? "rotate(-90deg)" : "none",
              transition: "transform 0.2s",
            }}
          />
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
                    className="flex flex-col gap-0.5 w-full text-left py-0.5 hover:brightness-125"
                  >
                    <span className="flex items-start gap-2.5 min-w-0">
                    {/* One identical 12x12 wrapper for BOTH states so the
                        node centre always lands at x=6 — matching the
                        hairline at left:5.5 and the 12px header core. Without
                        this, a 12px working node and a 9px-occupied dot made
                        the step text shift horizontally when a step became
                        active. */}
                    <span
                      className="shrink-0 flex items-center justify-center"
                      style={{
                        width: 12,
                        height: 12,
                        minWidth: 12,
                        marginTop: 3,
                        marginLeft: 0,
                        zIndex: 1,
                        position: "relative",
                      }}
                    >
                      {step.status === "working" ? (
                        <>
                          {/* Opaque backdrop disc masks the vertical hairline
                              exactly as the inactive dots mask it with
                              background:"#05060c" — without it the hairline
                              draws straight through the Xur. A soft ring
                              (glow + border) gives the node presence at 12px,
                              where the Xur's 9-lobe epitrochoid curve is
                              otherwise a faint sub-pixel smudge. */}
                          <span
                            aria-hidden
                            style={{
                              position: "absolute",
                              inset: 0,
                              borderRadius: "50%",
                              background: "#05060c",
                              border: `1px solid ${meta.color}40`,
                              boxShadow: `0 0 8px ${meta.color}`,
                            }}
                          />
                          {/* The active step animates. Xur reuses the same
                              curve / particle language as the orb, so "the
                              agent is on this one" reads at a glance without
                              a second colour system. Rendered above the
                              backdrop disc. */}
                          <span className="relative" style={{ color: meta.color }}>
                            <Xur size={12} color={meta.color} speed={1.4} />
                          </span>
                        </>
                      ) : (
                        <span
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            background: "#05060c",
                            border: `1.5px solid ${meta.color}`,
                            boxShadow: `0 0 8px ${meta.color}`,
                          }}
                        />
                      )}
                    </span>
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
                    </span>
                    {toolLabel(step) || step.activeDetail || step.url ? (
                      <span
                        className="flex flex-col gap-[3px] pl-[22px] min-w-0"
                        style={{ color: glowColor }}
                        title={
                          step.activeDetail
                            ? `${toolLabel(step)} — ${step.activeDetail}${
                                step.activeProgress
                                  ? ` (${step.activeProgress})`
                                  : ""
                              }${step.url ? ` — ${step.url}` : ""}`
                            : toolLabel(step)
                        }
                      >
                        <span className="flex items-baseline gap-1.5 min-w-0 text-[10px] leading-snug">
                        <span
                          className="shrink-0 rounded-full px-2 py-[1px] text-[10px] leading-tight font-normal"
                          style={{
                            color: glowColor,
                            background: "rgba(255,255,255,0.08)",
                            border: "1px solid rgba(255,255,255,0.14)",
                          }}
                        >
                          {toolLabel(step)}
                        </span>
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
                        {/* pin_517dfcbda150 (F1): the live source URL streamed
                            by the crawler on every page event — visible under
                            the detail, truncated to the card width. */}
                        {step.url ? (
                          <span
                            className="block max-w-full truncate normal-case text-[9px] leading-snug"
                            style={{ color: "rgba(255,255,255,0.38)" }}
                          >
                            {step.url}
                          </span>
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
      </div>
    </motion.div>
  )
}
