"use client"

import React, { useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { Search, ChevronDown } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Xur } from "@/components/Xur"
import { deriveCurrentStep } from "@/hooks/useTaskProgress"
import type { TaskStep, TaskStepStatus } from "@/hooks/useTaskProgress"
import { toolLabel } from "@/hooks/useTaskProgress"
import {
  CardChassis,
  ChassisBadge,
  ChassisBranchBadge,
  VEIN_COLOR_BY_STATE,
  type ChassisVeinState,
} from "@/components/chat/CardChassis"
import { formatMemoryEntry } from "@/lib/cards/memoryRegistry"

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

// A step carries `branchLabel` once the backend emits it on sub-loop-split
// children (T2b, agent_kernel.py ~11570-11612). Not on `TaskStep` yet — this
// card renders it when present and nothing when absent, exactly like every
// other optional field here, without inventing a second step type.
type StepWithBranch = TaskStep & { branchLabel?: string }

/**
 * TaskListCard — inline agent plan/progress in the chat stream.
 * T9 (REQ-1, REQ-10): renders through the shared `CardChassis` (T8) rather
 * than its own bespoke surface — the ink background, accent vein, header row,
 * bracketed `[done/total]` counter and REQ-1 AC5 padding are ALL the
 * chassis's now; this file supplies only its own header content and the step
 * list body. Presentational: receives `steps` from chat-view (which uses
 * useTaskProgress).
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
  // The COUNTER shows the step being worked on; the BAR shows real completion.
  //
  // This card was computing its own number from `doneCount`, ignoring the
  // shared currentStep the orb uses — so while step 3 of 4 ran, the orb read 3
  // and the card read "2/4". Same rule for both now (deriveCurrentStep: a
  // running step is the step you are on). The progress BAR deliberately stays
  // on doneCount, because a step in flight is not finished work.
  //
  // THERE IS EXACTLY ONE NUMERIC COUNTER ON THIS CARD, and it is the chassis's
  // bracketed one. An earlier pass rendered BOTH a chassis `[done/total]` and
  // an inline `current/total` in the SAME header row — so a card in flight read
  // "[1/3]  2/3", two 9px mono fractions side by side, disagreeing, with nothing
  // saying what either meant. Two honest numbers presented as one thing is not
  // honest; it is just unreadable. The counter answers "which step am I on" and
  // agrees with the orb; the BAR answers "how much is done" and stays on
  // doneCount, because a step in flight is not finished work.
  const displayStep = deriveCurrentStep(steps)
  // Action-only header, derived from the agent's live tool (never "Plan").
  const headerTitle = planTitle || mode?.toUpperCase() || "TASK"

  // REQ-1 AC2/AC3: the chassis vein is driven by real execution state, not by
  // the user's brand color — `glowColor` above stays reserved for identity
  // badges so a user-set brand color never overrides what the vein is saying
  // (REQ-2 edge case). A step actually running is "thinking"; a crystallized
  // learning signal wins over that; otherwise idle.
  const isWorking = steps.some((s) => s.status === "working")
  const veinState: ChassisVeinState = learningSignal === "crystallized" ? "crystallized" : isWorking ? "thinking" : "idle"
  const veinColor = VEIN_COLOR_BY_STATE[veinState]

  // REQ-10: memory activity slot, rendered EXCLUSIVELY from the shared
  // registry (AC2) and ONLY when a real event has been received (AC4) — never
  // fabricated, never padded. `learning`/`crystallized` are the only kinds
  // emitting today (agent_kernel.py:11403); `recall`/`compress`/`episodic`
  // stay silent until T8c, so this slot is honestly sparse until then.
  const memoryKind = learningSignal === "crystallized" ? "crystallized" : learningSignal ? "learning" : null
  const memoryEntry = memoryKind ? formatMemoryEntry(memoryKind, { signal: learningSignal }) : null

  // REQ-8: honest learning signal -> subtle Pacman OrbCanvas-style border
  // particles on the card. The signal is real state (avoided / retried /
  // crystallized), never narration. Tint follows the signal kind. Kept local
  // — the memory registry defines label/glyph/fields, not color.
  const signalTint: Record<string, string> = {
    avoided: "#f59e0b", // amber — a step was avoided (AVOID)
    retried: "#3b82f6", // blue — split into Sub-Loops
    crystallized: "#22c55e", // green — skill captured
  }

  return (
    <CardChassis
      veinColor={veinColor}
      isActive={isWorking}
      collapsible={false}
      counter={{ done: displayStep, total: steps.length }}
      aria-label="Task progress"
      header={
        <>
          {/* REQ-8: subtle Pacman OrbCanvas-style border particles on live
              learning signal. `chassis-surface` (the nearest `relative`
              ancestor) is what `inset-0` resolves against here, so this ring
              still wraps the WHOLE card even though it's mounted inside the
              header slot. */}
          {learningSignal && (
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 rounded-lg"
              style={{
                border: `1px solid ${signalTint[learningSignal]}55`,
                boxShadow: `0 0 14px ${signalTint[learningSignal]}33, inset 0 0 6px ${signalTint[learningSignal]}22`,
                // slow breathing pulse — quiet, not a spinner
                animation: "irisSignalPulse 2.4s ease-in-out infinite",
              }}
            />
          )}
          {/* W4 (T24): websearch gets a magnifying glass icon; other actions get the gradient core */}
          {headerTitle.toLowerCase().includes("websearch") ? (
            <span className="relative shrink-0 flex items-center justify-center" style={{ width: 12, height: 12 }}>
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
          <ChassisBadge color={glowColor}>{headerTitle.toUpperCase()}</ChassisBadge>

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
          {/* Failures get their OWN element, never a "· 2✕" suffix welded onto
              the counter. The rail above already gives failures their share in
              red; this states the count. Keeping it separate is what lets the
              card carry exactly one fraction. */}
          {failCount > 0 && (
            <span
              className={`text-[10px] font-mono tabular-nums shrink-0${steps.length > 0 ? "" : " ml-auto"}`}
              style={{ color: "#f87171" }}
              title={`${failCount} step${failCount === 1 ? "" : "s"} failed`}
            >
              {failCount}✕
            </span>
          )}

          {/* REQ-8/REQ-10: honest learning-signal badge. The DISPLAYED LABEL
              comes from the memory registry's formatted summary — never a
              second hardcoded copy of the signal text — while color stays
              local (the registry defines label/glyph/fields, not color). */}
          {memoryEntry && (
            <span
              className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
              style={{
                color: signalTint[learningSignal!],
                backgroundColor: `${signalTint[learningSignal!]}1a`,
                border: `1px solid ${signalTint[learningSignal!]}40`,
              }}
              title={`Learning signal: ${memoryEntry.summary}`}
            >
              {memoryEntry.summary}
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
        </>
      }
      // The chassis owns collapse geometry, but not THIS card's own toggle —
      // `collapsible={false}` above keeps the chassis's own chevron out of
      // the way (avoiding a second, differently-labeled affordance) while
      // this card keeps driving visibility itself: only pass `children` when
      // expanded, so the chassis's AnimatePresence gate still mounts/unmounts
      // the step list exactly as it did before the migration (REQ-1 AC4).
      children={
        !collapsed ? (
          <div className="relative">
            {/* Continuous vertical hairline through all step nodes — centered at 6px
                (matches the 12px step-icon wrapper and header core center), fades at
                top/bottom */}
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
                const branchLabel = (step as StepWithBranch).branchLabel
                return (
                  <div key={step.id ?? i} className="flex flex-col">
                    <button
                      type="button"
                      onClick={() =>
                        step.resultPreview ? setExpandedStep(isOpen ? null : step.id) : undefined
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
                          color: step.status === "pending" ? "rgba(255,255,255,0.45)" : "rgba(255,255,255,0.9)",
                        }}
                      >
                        {step.description}
                      </span>
                      {branchLabel && <ChassisBranchBadge branchLabel={branchLabel} />}
                      </span>
                      {toolLabel(step) || step.activeDetail || step.url ? (
                        <span
                          className="flex flex-col gap-[3px] pl-[22px] min-w-0"
                          style={{ color: glowColor }}
                          title={
                            step.activeDetail
                              ? `${toolLabel(step)} — ${step.activeDetail}${
                                  step.activeProgress ? ` (${step.activeProgress})` : ""
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
                                    <span style={{ color: "rgba(255,255,255,0.35)" }}> {step.activeProgress}</span>
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
                        style={{ color: "rgba(255,255,255,0.55)", whiteSpace: "pre-wrap" }}
                      >
                        {step.resultPreview}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        ) : undefined
      }
    />
  )
}
