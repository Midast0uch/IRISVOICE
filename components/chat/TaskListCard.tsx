"use client"

import React, { useState, useEffect, useMemo } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { Search, ChevronDown } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Xur } from "@/components/Xur"
import { deriveCurrentStep } from "@/hooks/useTaskProgress"
import type { TaskStep, TaskStepStatus, MemoryEvent } from "@/hooks/useTaskProgress"
import { toolLabel, MODE_NON_TOOLS } from "@/hooks/useTaskProgress"
import { resolveVerb } from "@/lib/cards/verbRegistry"
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
  /** T8c (REQ-10 AC5): real memory-activity events (recall / compress /
   * episodic) surfaced in the card's memory slot. */
  memoryEvents?: MemoryEvent[]
  /** Live agent thought/action â€” drives the THK row (design token table:
   * badge #fbbf24 on amber, thought italic truncate). Rendered ONLY when
   * real data arrived; never fabricated (REQ-10 AC4). */
  currentAction?: string
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
// children (T2b, agent_kernel.py ~11570-11612). Not on `TaskStep` yet â€” this
// card renders it when present and nothing when absent, exactly like every
// other optional field here, without inventing a second step type.
type StepWithBranch = TaskStep & { branchLabel?: string }

/**
 * TaskListCard â€” inline agent plan/progress in the chat stream.
 * T9 (REQ-1, REQ-10): renders through the shared `CardChassis` (T8) rather
 * than its own bespoke surface â€” the ink background, accent vein, header row,
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
  memoryEvents,
  currentAction,
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
  // shared currentStep the orb uses â€” so while step 3 of 4 ran, the orb read 3
  // and the card read "2/4". Same rule for both now (deriveCurrentStep: a
  // running step is the step you are on). The progress BAR deliberately stays
  // on doneCount, because a step in flight is not finished work.
  //
  // THERE IS EXACTLY ONE NUMERIC COUNTER ON THIS CARD, and it is the chassis's
  // bracketed one. An earlier pass rendered BOTH a chassis `[done/total]` and
  // an inline `current/total` in the SAME header row â€” so a card in flight read
  // "[1/3]  2/3", two 9px mono fractions side by side, disagreeing, with nothing
  // saying what either meant. Two honest numbers presented as one thing is not
  // honest; it is just unreadable. The counter answers "which step am I on" and
  // agrees with the orb; the BAR answers "how much is done" and stays on
  // doneCount, because a step in flight is not finished work.
  const displayStep = deriveCurrentStep(steps)
  // Action-only header, derived from the agent's live tool (never "Plan").
  const headerTitle = planTitle || mode?.toUpperCase() || "TASK"

  // REQ-1 AC2/AC3: the chassis vein is driven by real execution state, not by
  // the user's brand color â€” `glowColor` above stays reserved for identity
  // badges so a user-set brand color never overrides what the vein is saying
  // (REQ-2 edge case). A step actually running is "thinking"; a crystallized
  // learning signal wins over that; otherwise idle.
  const isWorking = steps.some((s) => s.status === "working")
  const veinState: ChassisVeinState = learningSignal === "crystallized" ? "crystallized" : isWorking ? "thinking" : "idle"
  const veinColor = VEIN_COLOR_BY_STATE[veinState]

  // REQ-3 AC2 (design token table): elapsed running timer â€” `â± m:ss`,
  // tabular-nums, vein-tinted pill. Ticks ONLY while a step is working and
  // freezes when the run settles (converge / fail) â€” never fabricated while
  // idle. Interval cleaned up on every effect pass (no leaked timers).
  const [elapsedSec, setElapsedSec] = useState(0)
  useEffect(() => {
    if (!isWorking) return
    const id = setInterval(() => setElapsedSec((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [isWorking])
  const timerLabel = `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, "0")}`

  // REQ-14 verb column â€” ONE registry source shared with the CLI renderer.
  // A verb renders ONLY for a real tool: steps with no toolName (pure plan
  // lines) and mode-names masquerading as tools (MODE_NON_TOOLS, shared with
  // chat-view's suppression filter) get a quiet em-dash, NEVER the registry's
  // "TOOL" fallback or a mode uppercased into verb position. Blank-honest
  // beats label-noise.
  const stepVerb = (s: TaskStep): string | null => {
    if (!s.toolName || MODE_NON_TOOLS.has(s.toolName.toLowerCase())) return null
    return resolveVerb(s.toolName)
  }

  // REQ-10: memory activity slot, rendered EXCLUSIVELY from the shared
  // registry (AC2) and ONLY when a real event has been received (AC4) â€” never
  // fabricated, never padded. `learning`/`crystallized` come from the
  // task:learning signal; `recall`/`compress`/`episodic` arrive as real
  // memory:event emits (T8c) and are rendered through the same registry.
  const memoryKind = learningSignal === "crystallized" ? "crystallized" : learningSignal ? "learning" : null
  const memoryEntry = memoryKind ? formatMemoryEntry(memoryKind, { signal: learningSignal }) : null

  // REQ-8: honest learning signal -> subtle Pacman OrbCanvas-style border
  // particles on the card. The signal is real state (avoided / retried /
  // crystallized), never narration. Tint follows the signal kind. Kept local
  // â€” the memory registry defines label/glyph/fields, not color.
  const signalTint: Record<string, string> = {
    avoided: "#f59e0b", // amber â€” a step was avoided (AVOID)
    retried: "#3b82f6", // blue â€” split into Sub-Loops
    crystallized: "#22c55e", // green â€” skill captured
  }

  // T8c (REQ-10 AC5): combine the learning signal with the real memory events
  // into one registry-driven badge list. Each entry is formatted by the
  // shared registry (AC2) and only rendered when real (AC4).
  const MEMORY_TINT: Record<string, string> = {
    recall: "#a78bfa",
    compress: "#38bdf8",
    episodic: "#fbbf24",
  }
  const memoryBadges = useMemo(() => {
    const out: { key: string; glyph: string; text: string; color: string; title: string }[] = []
    if (memoryKind && memoryEntry) {
      out.push({
        key: `learning-${learningSignal}`,
        glyph: memoryEntry.glyph,
        text: memoryEntry.summary,
        color: signalTint[learningSignal!],
        title: `Learning signal: ${memoryEntry.summary}`,
      })
    }
    for (const ev of memoryEvents || []) {
      const fe = formatMemoryEntry(ev.kind, ev.data)
      if (!fe) continue
      // Learning/crystallized carry a signal-specific summary (e.g. "Retried");
      // recall/compress/episodic use reserved Wormhole fields (not yet
      // populated), so fall back to the stable label for an honest badge.
      const text =
        ev.kind === "learning" || ev.kind === "crystallized"
          ? fe.summary
          : fe.label
      out.push({
        key: `mem-${ev.at}-${ev.kind}`,
        glyph: fe.glyph,
        text,
        color: MEMORY_TINT[ev.kind] ?? glowColor,
        title: fe.summary,
      })
    }
    return out
  }, [memoryKind, memoryEntry, memoryEvents, learningSignal, glowColor])

  // Design token table â€” footnote text: latest REAL memory event
  // (recall/compress/episodic), falling back to "Active Execution". The
  // learning signal deliberately does NOT feed the footnote â€” it already
  // renders as a header badge, and repeating it duplicated the word twice
  // on the card (caught by TaskListCard.display.test.tsx).
  const footnoteText = useMemo(() => {
    const last = memoryEvents?.[memoryEvents.length - 1]
    if (!last) return "Active Execution"
    return formatMemoryEntry(last.kind, last.data)?.summary ?? last.kind
  }, [memoryEvents])

  return (
    <CardChassis
      veinColor={veinColor}
      isActive={isWorking}
      collapsible={false}
      counter={{ done: displayStep, total: steps.length }}
      aria-label="Task progress"
      subheader={
        /* Design token table â€” THK row: badge #fbbf24 on amber, thought
           italic truncate. Only when real thought/action data arrived. */
        currentAction ? (
          <span className="flex items-center gap-1.5 min-w-0">
            <ChassisBadge color="#fbbf24">THK</ChassisBadge>
            <span className="italic truncate text-[10px]" style={{ color: "rgba(251,191,36,0.7)" }}>
              {currentAction}
            </span>
          </span>
        ) : undefined
      }
      footer={
        /* Design token table â€” footnote: memory dot in vein colour +
           latest memory detail; falls back to "Active Execution". Driven by
           the registry-formatted badges (never fabricated). */
        <span className="flex items-center gap-1.5 min-w-0">
          <span
            aria-hidden
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: veinColor,
              boxShadow: `0 0 6px ${veinColor}`,
              flexShrink: 0,
            }}
          />
          <span className="truncate text-[9px] font-mono" style={{ color: "rgba(255,255,255,0.35)" }}>
            {footnoteText}
          </span>
        </span>
      }
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
                // slow breathing pulse â€” quiet, not a spinner
                animation: "irisSignalPulse 2.4s ease-in-out infinite",
              }}
            />
          )}
          {/* W4 (T24): websearch gets a magnifying glass icon; other actions get
              the gradient core. Keyed on mode AND title â€” with objective-first
              titles ("Search the latest llama.cpp release notesâ€¦") the word
              websearch may only appear in `mode`. */}
          {`${headerTitle} ${mode ?? ""}`.toLowerCase().includes("websearch") ? (
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
              {/* Connector from core to step list â€” only when steps visible */}
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
          {/* Mode/action badge stays SHORT â€” ChassisBadge is shrink-0, so a
              long title inside it could never shrink and would be clipped
              mid-glyph by the chassis's overflow-hidden once the timer, rail,
              memory badges and toggle share the row. The OBJECTIVE renders
              beside it as min-w-0 truncate text: it clips gracefully at the
              boundary and keeps its full text on the title tooltip. */}
          <ChassisBadge color={glowColor}>{(mode ?? headerTitle).toUpperCase()}</ChassisBadge>
          {planTitle && (
            <span
              className="min-w-0 flex-1 truncate text-[11px] font-mono font-semibold"
              style={{ color: "rgba(255,255,255,0.9)" }}
              title={planTitle}
            >
              {planTitle}
            </span>
          )}

          {/* REQ-3 AC2: elapsed running timer â€” vein-tinted pill, freezes when
              the run settles. Hidden entirely until the first working tick so
              an idle card never shows a fabricated 0:00. */}
          {(isWorking || elapsedSec > 0) && (
            <span
              className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono tabular-nums"
              style={{ color: veinColor, border: `1px solid ${veinColor}40`, background: `${veinColor}0d` }}
              title="Elapsed execution time"
            >
              â± {timerLabel}
            </span>
          )}

          {/* Progress rail. A bare "2/5" made the reader do the arithmetic to
              find out how far along a run was; the bar states it directly, and
              failures take their share of it in red instead of hiding behind a
              "Â·2âœ•" suffix. */}
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
          {/* Failures get their OWN element, never a "Â· 2âœ•" suffix welded onto
              the counter. The rail above already gives failures their share in
              red; this states the count. Keeping it separate is what lets the
              card carry exactly one fraction. */}
          {failCount > 0 && (
            <span
              className={`text-[10px] font-mono tabular-nums shrink-0${steps.length > 0 ? "" : " ml-auto"}`}
              style={{ color: "#f87171" }}
              title={`${failCount} step${failCount === 1 ? "" : "s"} failed`}
            >
              {failCount}âœ•
            </span>
          )}

          {/* REQ-8/REQ-10: honest memory-activity badges. Every badge's
              label/glyph comes from the shared memory registry's formatted
              summary â€” never a second hardcoded copy â€” while color stays
              local (the registry defines label/glyph/fields, not color). The
              list combines the learning signal with the real recall/compress/
              episodic events (T8c). */}
          {memoryBadges.map((b) => (
            <span
              key={b.key}
              className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
              style={{
                color: b.color,
                backgroundColor: `${b.color}1a`,
                border: `1px solid ${b.color}40`,
              }}
              title={b.title}
            >
              {b.glyph} {b.text}
            </span>
          ))}

          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="shrink-0 p-1 rounded transition-all duration-150 hover:brightness-125 flex items-center justify-center"
            style={{ color: glowColor, border: `1px solid ${glowColor}30` }}
            aria-label={collapsed ? "Expand plan" : "Collapse plan"}
          >
            {/* The â–¸/â–¾ glyphs render at different heights across fonts, so the
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
      // The chassis owns collapse geometry, but not THIS card's own toggle â€”
      // `collapsible={false}` above keeps the chassis's own chevron out of
      // the way (avoiding a second, differently-labeled affordance) while
      // this card keeps driving visibility itself: only pass `children` when
      // expanded, so the chassis's AnimatePresence gate still mounts/unmounts
      // the step list exactly as it did before the migration (REQ-1 AC4).
      children={
        !collapsed ? (
          <div className="relative pl-2">
            {/* pl-1: keeps the node/verb column off the accent vein's glow
                halo â€” content starts 4px further in; the detail-row indent
                (pl-[84px]) is row-relative so alignment is unchanged. */}
            {/* Continuous vertical hairline through all step nodes â€” centered at 6px
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
                      <span className="flex items-start gap-3 min-w-0">
                      {/* One identical 12x12 wrapper for BOTH states so the
                          node centre always lands at x=6 â€” matching the
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
                            {/* Design token table â€” node Â· running: animate-ping
                                ring + inner ring + Xur. The ping announces "this
                                step is in flight" without a spinner. */}
                            <span
                              aria-hidden
                              className="absolute inset-0 rounded-full animate-ping"
                              style={{ border: `1.5px solid ${meta.color}80`, background: `${meta.color}14` }}
                            />
                            {/* Opaque backdrop disc masks the vertical hairline
                                exactly as the inactive dots mask it with
                                background:"#05060c" â€” without it the hairline
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
                                backdrop disc. Size 7 per the design tokens. */}
                            <span className="relative" style={{ color: meta.color }}>
                              <Xur size={7} color={meta.color} speed={1.4} />
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
                      {/* REQ-14 verb column â€” ONE registry source shared with the
                          CLI renderer (lib/cards/verbRegistry.resolveVerb).
                          w-12 fixed so targets align; vein-coloured per the
                          design token table. Steps with no real tool render a
                          quiet em-dash â€” never "TOOL", never a mode name. */}
                      <span
                        className="w-12 shrink-0 font-mono font-bold uppercase tracking-wider text-[10px] leading-snug"
                        style={{ color: stepVerb(step) ? veinColor : "rgba(255,255,255,0.2)", marginTop: 3 }}
                        title={step.toolName || undefined}
                      >
                        {stepVerb(step) ?? "â€”"}
                      </span>
                      <span
                        className="text-[11px] leading-snug flex-1 min-w-0 break-words"
                        style={{
                          color: step.status === "pending" ? "rgba(255,255,255,0.45)" : "rgba(255,255,255,0.9)",
                        }}
                      >
                        {step.description}
                      </span>
                      {branchLabel && <ChassisBranchBadge branchLabel={branchLabel} />}
                      </span>
                      {step.activeDetail || step.url || step.resultPreview ? (
                        <span
                          className="flex flex-col gap-[3px] pl-[84px] min-w-0"
                          style={{ color: glowColor }}
                          title={
                            step.activeDetail
                              ? `${toolLabel(step)} â€” ${step.activeDetail}${
                                  step.activeProgress ? ` (${step.activeProgress})` : ""
                                }${step.url ? ` â€” ${step.url}` : ""}`
                              : toolLabel(step)
                          }
                        >
                          <span className="flex items-baseline gap-1.5 min-w-0 text-[10px] leading-snug">
                            {/* Live source, beside the plan text. The verb column
                                is the SINGLE tool representation â€” the human tool
                                label is deliberately NOT repeated here (it read
                                "SEARCH â€¦ WebSearch", saying the same thing twice).
                                The label survives in the row's title tooltip and
                                the verb's own title={toolName}. */}
                            {/* Live source, beside the tool rather than replacing
                                the plan text. Keyed on the detail so each new host
                                re-mounts and fades in â€” the "rotation". */}
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
                              by the crawler on every page event â€” visible under
                              the detail, truncated to the card width. */}
                          {step.url ? (
                            <span
                              className="block max-w-full truncate normal-case text-[9px] leading-snug"
                              style={{ color: "rgba(255,255,255,0.38)" }}
                            >
                              {step.url}
                            </span>
                          ) : null}
                          {/* Design token table â€” inline summary: 9px mono,
                              white/25, max-w-[170px], prefixed `Â·`. Shown while
                              collapsed; click still opens the full pre-wrap view. */}
                          {step.resultPreview && !isOpen ? (
                            <span
                              className="truncate text-[9px] font-mono max-w-[170px]"
                              style={{ color: "rgba(255,255,255,0.25)" }}
                            >
                              Â· {step.resultPreview}
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
