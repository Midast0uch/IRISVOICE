"use client"

import React, { useState, useEffect, useMemo, useRef, useCallback } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { ChevronDown, Copy, Check, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { deriveCurrentStep } from "@/hooks/useTaskProgress"
import type { TaskStep, TaskStepStatus, MemoryEvent } from "@/hooks/useTaskProgress"
import { toolLabel, MODE_NON_TOOLS } from "@/hooks/useTaskProgress"
import { resolveVerb } from "@/lib/cards/verbRegistry"
import {
  CardChassis,
  ChassisBadge,
  ChassisBranchBadge,
  ChassisChromeLabel,
  ChassisStepNode,
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
  /** Live agent action — drives the THK row when no stream entries exist.
   * Rendered ONLY when real data arrived; never fabricated (REQ-10 AC4). */
  currentAction?: string
  /** REQ-4: structured crawl pipeline phase (searching / fetching /
   * extracting / citing …) — rotates the working step's verb. */
  phase?: string
  /** Live agent thinking stream (newest last) — the THK section's expandable
   * trace. Rendered ONLY when real reasoning arrived; never fabricated. */
  thoughtStream?: string[]
  /** Session 246: total wall-clock seconds the completed run took
   * (rehydrated cards). Renders a frozen duration pill in the footer. */
  durationSec?: number
  /** Session 246: card-level liveness from the hook (task frames keep the
   * run "working" even when no individual step is — e.g. the synthesis
   * tail, where no tool:call ever marks the final step). Drives the
   * glowing node + timer so the card never looks frozen mid-run. */
  cardActive?: boolean
  /** Session 246 (@taskcard): the card's stable id — rendered in the footer
   * chrome (`<id>/memory.db`) with a one-click copy, so users can reference
   * it via @taskcard:<id> from ANY conversation thread. */
  cardId?: string
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

// Session 245 (pin_07b780e7ce21): verb ROTATION for websearch. The crawler's
// structured pipeline phase (card.phase, already flowing over task:progress)
// drives the working step's verb so the column says what the agent is doing
// RIGHT NOW instead of one static SEARCH for the whole run. When no phase is
// present the registry verb for the real tool renders, exactly as before.
const PHASE_VERB: Record<string, string> = {
  planning: "PLAN",
  searching: "SEARCH",
  fetching: "READ",
  reading: "READ",
  extracting: "EXTRACT",
  citing: "CITE",
  synthesizing: "SYNTH",
}

// Session 245 (universal verb progression): planner steps carry NO tool
// (D1.3 — goals only), which used to render a blank em-dash column for every
// reasoning step. These keyword intents are derived from the step's OWN
// description — the plan's stated purpose, not a fabrication — so every row
// shows what that node is for, and the working step's live phase still wins.
//
// Session 246 audit (user finding: "Run the test suite…" rendered an em-dash):
// coverage extended to the exec/io/web/dialog families so common planner
// phrasings resolve. Order matters — FIRST match wins, so specific families
// sit above generic ones.
const INTENT_VERBS: Array<[RegExp, string]> = [
  [/summari|explain|synthes|conclude|final/i, "SYNTH"],
  [/analyz|identif|compare|evaluat|extract/i, "ANALYZE"],
  [/search|find|look up|research|gather/i, "SEARCH"],
  // exec before read/write: "run a review of…" is execution, not reading.
  [/run|test|execute|launch|restart|deploy/i, "EXEC"],
  [/delete|remove|clean|erase|uninstall/i, "ERASE"],
  [/commit\b/i, "COMMIT"],
  [/push\b/i, "PUSH"],
  [/branch|checkout/i, "BRANCH"],
  [/git diff|git status|diff\b/i, "DIFF"],
  [/git log|changelog|history\b/i, "LOG"],
  [/github|issue|pull request|\bPR\b/i, "FORGE"],
  [/fetch|download|crawl/i, "FETCH"],
  [/click/i, "CLICK"],
  [/type\b|keyboard|press key/i, "TYPE"],
  [/screenshot|screen|vision|look at/i, "SEE"],
  [/record|transcribe|clip|merge.*audio|merge.*video/i, "SCRIBE"],
  [/ask|clarif|question the user/i, "ASK"],
  [/speak|narrate|say\b/i, "SPEAK"],
  [/recall|remember|memory\b/i, "RECALL"],
  [/list|enumerate|catalog|inventory|scan directory/i, "LIST"],
  [/read|review|open|inspect/i, "READ"],
  [/write|draft|compose|generate|create|save/i, "WRITE"],
]

function intentVerb(description: string): string | null {
  const d = (description || "").toLowerCase()
  for (const [re, verb] of INTENT_VERBS) {
    if (re.test(d)) return verb
  }
  return null
}

/**
 * TaskListCard — inline agent plan/progress in the chat stream.
 * Renders through the shared `CardChassis` (T8) — the ink background, accent
 * vein, header row, bracketed `[done/total]` counter and REQ-1 AC5 padding
 * are ALL the chassis's; this file supplies its own header content, the THK
 * thinking section, the step list body and the footer. Presentational:
 * receives `steps` from chat-view (which uses useTaskProgress).
 *
 * Session 245 Liquid Ink fidelity pass (pin_07b780e7ce21, user-approved):
 *   - animated Xur header marker (variant tokens: size 14, vein colour,
 *     speed 1.8 working / 0.6 idle); the OBJECTIVE leads the header — no
 *     mode badge in front of it.
 *   - THK gets its OWN section: clickable row that expands the agent's
 *     thinking stream; italic "Reflecting..." fallback while thinking.
 *   - steps: 10.5px mono truncated targets, `· summary` back on the row
 *     tail, branch rows indented pl-4, boxed expanded summaries.
 *   - footer: timer pill + data/memory.db chrome label (moved from header).
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
  phase,
  thoughtStream,
  durationSec,
  cardActive,
  cardId,
}: TaskListCardProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color

  const [collapsed, setCollapsed] = useState(defaultCollapsed && steps.length > 4)
  const [expandedStep, setExpandedStep] = useState<string | null>(null)
  const [thkOpen, setThkOpen] = useState(false)
  // Session 246 (@taskcard): copy-feedback for the footer ID chrome.
  const [idCopied, setIdCopied] = useState(false)
  const copyCardId = useCallback(() => {
    if (!cardId) return
    navigator.clipboard?.writeText(cardId).then(
      () => {
        setIdCopied(true)
        setTimeout(() => setIdCopied(false), 1400)
      },
      () => {},
    )
  }, [cardId])

  const doneCount = steps.filter((s) => s.status === "done").length
  const failCount = steps.filter((s) => s.status === "fail").length
  // The COUNTER shows the step being worked on; the BAR shows real completion.
  // One numeric counter on this card — the chassis's bracketed one — agreeing
  // with the orb via deriveCurrentStep (a running step is the step you are
  // on). The progress BAR deliberately stays on doneCount, because a step in
  // flight is not finished work.
  const displayStep = deriveCurrentStep(steps)
  // Objective-first header (pin_07b780e7ce21): the OBJECTIVE TITLE is the
  // dominant header element — VariantLiquidInk renders it at text-[12px]
  // font-mono font-semibold white/95 tracking-tight truncate, immediately
  // after the marker, with NO badge in front. It renders ONLY from a real
  // planTitle: falling back to steps[0].description duplicated that text
  // with the step row below (caught by TaskListCard.test.tsx). The backend
  // derives plan_title from original_task whenever the planner omits it
  // (AgentKernel._effective_plan_title), so every live card carries one;
  // legacy payloads without plan_title keep the short mode badge.
  const objective = planTitle || null

  // REQ-1 AC2/AC3: the chassis vein is driven by real execution state.
  // Session 246: cardActive ORs in the hook-level run liveness — during the
  // synthesis tail no STEP is 'working' (no tool:call fires), but the run
  // is still going; without this the glowing node vanished and the timer
  // froze mid-run.
  const isWorking = Boolean(cardActive) || steps.some((s) => s.status === "working")
  // Session 246 (user finding): while the LAST step processes (the synthesis
  // tail), the backend never emits a tool:call for it — so no row ever showed
  // the glowing running node and the card looked frozen. When the run is
  // live but NO step is explicitly working, light up the next pending step
  // as running (display-only: statuses/counts below stay real).
  const anyWorking = isWorking
  const displaySteps = useMemo(() => {
    if (!anyWorking) return steps
    if (steps.some((s) => s.status === "working")) return steps
    const idx = steps.findIndex((s) => s.status === "pending" || s.status === "unknown")
    if (idx < 0) return steps
    const out = steps.slice()
    out[idx] = { ...out[idx], status: "working" as TaskStepStatus }
    return out
  }, [steps, anyWorking])
  // Session 245: run-complete state — every step reached a terminal status
  // and nothing is in flight. Drives the variant's "done" header badge.
  const runComplete =
    !isWorking &&
    steps.length > 0 &&
    steps.every((s) => s.status === "done" || s.status === "skipped")
  const veinState: ChassisVeinState = learningSignal === "crystallized" ? "crystallized" : isWorking ? "thinking" : "idle"
  const veinColor = VEIN_COLOR_BY_STATE[veinState]

  // Elapsed running timer — ticks ONLY while a step is working and freezes
  // when the run settles. Rendered in the FOOTER (variant anatomy), never
  // fabricated while idle. Interval cleaned up on every effect pass.
  const [elapsedSec, setElapsedSec] = useState(0)
  useEffect(() => {
    if (!isWorking) return
    const id = setInterval(() => setElapsedSec((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [isWorking])
  const timerLabel = `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, "0")}`

  // REQ-14 verb column — ONE registry source shared with the CLI renderer,
  // extended with phase rotation for the working step (see PHASE_VERB).
  // Session 245 (universal progression): the working step's live phase wins
  // FIRST — even for tool-less steps — so synthesis shows SYNTH instead of
  // reverting to SEARCH; then the registry verb for a real tool; then the
  // description-derived intent verb; only a step with neither renders the
  // quiet em-dash.
  const stepVerb = (s: TaskStep): string | null => {
    if (s.status === "working" && phase) {
      const pv = PHASE_VERB[phase.toLowerCase()]
      if (pv) return pv
    }
    if (s.toolName && !MODE_NON_TOOLS.has(s.toolName.toLowerCase())) {
      return resolveVerb(s.toolName)
    }
    return intentVerb(s.description)
  }

  // ── THK thinking section (session 245) ──────────────────────────────
  // The agent's live thought trace gets its own section under a hairline
  // divider: clickable row -> expandable stream panel. Everything renders
  // ONLY from real data (REQ-10 AC4): the row appears while the agent is
  // working or a real action/thought arrived; the stream panel only when
  // real reasoning entries exist; "Reflecting..." fills the gap while
  // thinking with nothing said yet (variant behavior).
  const hasThoughts = (thoughtStream?.length ?? 0) > 0
  const showThk = Boolean(currentAction || isWorking || hasThoughts)
  const latestThought = hasThoughts ? thoughtStream![thoughtStream!.length - 1] : currentAction
  const streamRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (thkOpen && streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight
    }
  }, [thkOpen, thoughtStream?.length])

  // REQ-10: memory activity slot, rendered EXCLUSIVELY from the shared
  // registry (AC2) and ONLY when a real event has been received (AC4).
  const memoryKind = learningSignal === "crystallized" ? "crystallized" : learningSignal ? "learning" : null
  const memoryEntry = memoryKind ? formatMemoryEntry(memoryKind, { signal: learningSignal }) : null

  const signalTint: Record<string, string> = {
    avoided: "#f59e0b", // amber — a step was avoided (AVOID)
    retried: "#3b82f6", // blue — split into Sub-Loops
    crystallized: "#22c55e", // green — skill captured
  }

  const MEMORY_TINT: Record<string, string> = {
    recall: "#a78bfa",
    compress: "#38bdf8",
    episodic: "#fbbf24",
  }
  // Session 246 (user-directed): memory events are FOOTER content, not
  // header badges. Learning/crystallized signals style the footer line
  // (glyph + signal tint, below); episodic activity feeds footnoteText.
  // The header keeps ONLY the objective, the done badge and the rail.

  // Session 246: the footer dot FLASHES when a memory event lands — a subtle
  // scale+brightness pulse (memoryDotFlash, css-src/globals.css). Re-mounting
  // via key restarts the animation cleanly per event.
  const memCount = memoryEvents?.length ?? 0
  const [dotFlashKey, setDotFlashKey] = useState(0)
  const prevMemCount = useRef(memCount)
  useEffect(() => {
    if (memCount > prevMemCount.current) setDotFlashKey((k) => k + 1)
    prevMemCount.current = memCount
  }, [memCount])

  // Design token table — footnote text: latest REAL memory event
  // (recall/compress/episodic), falling back to "Active Execution".
  const footnoteText = useMemo(() => {
    const last = memoryEvents?.[memoryEvents.length - 1]
    if (!last) return "Active Execution"
    return formatMemoryEntry(last.kind, last.data)?.summary ?? last.kind
  }, [memoryEvents])

  // Session 246: the footer memory line takes the KIND's tint so episodic
  // activity is visibly alive (amber) vs recall (violet) vs compress (cyan).
  const lastMemoryTint = useMemo(() => {
    const last = memoryEvents?.[memoryEvents.length - 1]
    return last ? MEMORY_TINT[last.kind] ?? null : null
  }, [memoryEvents])

  return (
    <CardChassis
      veinColor={veinColor}
      isActive={isWorking}
      collapsible={false}
      counter={{ done: displayStep, total: steps.length }}
      aria-label="Task progress"
      subheader={
        showThk ? (
          /* THK section — own divided strip (variant anatomy). Clickable
             when a real stream exists; italic whisper otherwise. */
          <div className="flex flex-col min-w-0">
            <button
              type="button"
              onClick={() => hasThoughts && setThkOpen((o) => !o)}
              className="flex items-center gap-1.5 min-w-0 text-left"
              aria-expanded={thkOpen}
              aria-label={hasThoughts ? "Toggle thinking stream" : undefined}
            >
              <ChassisBadge color="#fbbf24">THK</ChassisBadge>
              <span className="italic truncate text-[10px]" style={{ color: "rgba(251,191,36,0.7)" }}>
                {latestThought ?? (isWorking ? "Reflecting..." : "")}
              </span>
              {hasThoughts && (
                <ChevronDown
                  size={10}
                  className="shrink-0 opacity-50"
                  style={{ transform: thkOpen ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}
                />
              )}
            </button>
            {thkOpen && hasThoughts && (
              <div
                ref={streamRef}
                className="mt-1.5 max-h-[120px] overflow-y-auto rounded-md bg-black/40 border border-white/6 p-2 font-mono text-[9px] leading-relaxed"
                style={{ color: "rgba(251,191,36,0.55)" }}
                data-testid="thk-stream"
              >
                {thoughtStream!.map((line, i) => (
                  <div key={i} className="whitespace-pre-wrap break-words">
                    {line}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : undefined
      }
      footer={
        /* Footer (variant anatomy): memory dot + status on the left;
           TIMER + data/memory.db chrome label on the right.
         * Session 246: this app has an UN-LAYERED global margin/padding
           reset that overrides Tailwind v4's layered utilities — synthetic
           probes show ml-auto/mr-auto/pl-* all compute 0. So the two sides
           are separated with justify-between (verified working), NOT
           margin-auto, and each side is its own flex group. */
        <span className="flex items-center justify-between gap-2 min-w-0 w-full">
          <span className="flex items-center gap-1.5 min-w-0">
          <span
            aria-hidden
            key={dotFlashKey}
            style={{
              /* Session 246: margin puts the dot's centre on the shared left
                 rail (34px axis: pl-3 + body pl-2 + row px-1.5 + half node). */
              marginLeft: 19.5,
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: veinColor,
              boxShadow: `0 0 6px ${veinColor}`,
              flexShrink: 0,
              animation: dotFlashKey > 0 ? "memoryDotFlash 0.8s ease-out" : undefined,
            }}
          />
          {/* Session 245: the memory footer goes LIVE — learning signals get
              their own glyph + signal-tinted font effect; regular memory
              events render their registry summary; only a run with zero
              memory activity keeps the quiet "Active Execution". */}
          {learningSignal && memoryEntry ? (
            <span
              className="truncate text-[9px] font-mono font-bold uppercase tracking-wider"
              style={{
                color: signalTint[learningSignal] ?? veinColor,
                textShadow: `0 0 8px ${signalTint[learningSignal] ?? veinColor}55`,
              }}
              title={`Learning signal: ${memoryEntry.summary}`}
            >
              {memoryEntry.glyph} {memoryEntry.summary}
            </span>
          ) : (
            <span
              className="truncate text-[9px] font-mono"
              style={{
                color: lastMemoryTint ?? "rgba(255,255,255,0.35)",
                textShadow: lastMemoryTint ? `0 0 8px ${lastMemoryTint}44` : undefined,
              }}
              title={footnoteText}
            >
              {footnoteText}
            </span>
          )}
          </span>
          {/* Right group — justify-between on the parent pins this to the
              FAR RIGHT edge of the footer. */}
          <span className="flex items-center gap-2 shrink-0">
            {(isWorking || elapsedSec > 0) && (
              <span
                className="px-1.5 py-0.5 rounded text-[9px] font-mono tabular-nums"
                style={{ color: `${veinColor}cc`, border: `1px solid ${veinColor}20`, background: `${veinColor}10` }}
                title="Elapsed execution time"
              >
                ⏱ {timerLabel}
              </span>
            )}
            {/* Session 246 (user ask): a REHYDRATED card shows how long the
                task took — frozen duration from the persisted record, instead
                of no timer at all. */}
            {!isWorking && elapsedSec === 0 && typeof durationSec === "number" && durationSec > 0 && (
              <span
                className="px-1.5 py-0.5 rounded text-[9px] font-mono tabular-nums"
                style={{ color: "rgba(255,255,255,0.45)", border: "1px solid rgba(255,255,255,0.10)", background: "rgba(255,255,255,0.04)" }}
                title="Total task duration"
              >
                ⏱ {durationSec >= 3600
                  ? `${Math.floor(durationSec / 3600)}:${String(Math.floor((durationSec % 3600) / 60)).padStart(2, "0")}:${String(durationSec % 60).padStart(2, "0")}`
                  : `${Math.floor(durationSec / 60)}:${String(durationSec % 60).padStart(2, "0")}`}
              </span>
            )}
            {/* Session 246 (@taskcard): the card's ID lives in the footer
                chrome — `<short-id>/memory.db` — with a one-click copy to its
                left, so it can be referenced as @taskcard:<id> from ANY
                conversation thread. */}
            {/* Copy + ID hug each other (gap-1); the timer stays a full
                gap-2 away so the pairs read as separate clusters. */}
            <span className="flex items-center gap-1 shrink-0">
              {cardId && (
                <button
                  type="button"
                  onClick={copyCardId}
                  className="flex items-center justify-center rounded transition-all duration-150 hover:brightness-150"
                  style={{ color: idCopied ? "#34d399" : "rgba(255,255,255,0.4)", padding: 1, lineHeight: 0 }}
                  title={`Copy task-card ID: ${cardId}`}
                  aria-label="Copy task-card ID"
                >
                  {idCopied ? <Check size={9} /> : <Copy size={9} />}
                </button>
              )}
              <ChassisChromeLabel>
                {cardId ? `${cardId.replace(/^card_/, "")}/memory.db` : "taskcard/memory.db"}
              </ChassisChromeLabel>
            </span>
          </span>
        </span>
      }
      header={
        <>
          {/* REQ-8: subtle Pacman OrbCanvas-style border particles on live
              learning signal. */}
          {learningSignal && (
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 rounded-lg"
              style={{
                border: `1px solid ${signalTint[learningSignal]}55`,
                boxShadow: `0 0 14px ${signalTint[learningSignal]}33, inset 0 0 6px ${signalTint[learningSignal]}22`,
                animation: "irisSignalPulse 2.4s ease-in-out infinite",
              }}
            />
          )}
          {/* Animated identity marker — variant tokens verbatim: Xur 14,
              vein-coloured, faster while working. The websearch Search icon
              is gone: the objective itself carries the context now.
           * Session 246: marginLeft keeps the marker's centre on the SAME
              vertical axis as the body step nodes and the footer dot — one
              continuous left rail (user-requested symmetry). Axis math:
              pl-3(12) + body pl-2(8) + row px-1.5(6) + half node box(8) = 34;
              34 - 12 - 7 = 15. */}
          <span style={{ display: "flex", marginLeft: 15 }}>
            <Xur size={14} color={veinColor} speed={isWorking ? 1.8 : 0.6} />
          </span>
          {/* OBJECTIVE leads the header (12px mono semibold white/95
              tracking-tight truncate, full text on tooltip). No badge in
              front of it. Legacy payloads without planTitle fall back to a
              short mode badge. */}
          {objective ? (
            <span
              className="min-w-0 flex-1 truncate text-[12px] font-mono font-semibold tracking-tight"
              style={{ color: "rgba(255,255,255,0.95)" }}
              title={objective}
            >
              {objective}
            </span>
          ) : (
            mode && <ChassisBadge color={glowColor}>{mode.toUpperCase()}</ChassisBadge>
          )}
          {/* Variant anatomy: the crystallized/done badge beside the
              objective — a run that finished clean shows it, not just
              learning-signal runs. */}
          {runComplete && (
            <ChassisBadge color="#34d399" icon={<Sparkles size={8} />}>
              done
            </ChassisBadge>
          )}

          {/* Progress rail — failures take their share in red. */}
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
          {failCount > 0 && (
            <span
              className={`text-[10px] font-mono tabular-nums shrink-0${steps.length > 0 ? "" : " ml-auto"}`}
              style={{ color: "#f87171" }}
              title={`${failCount} step${failCount === 1 ? "" : "s"} failed`}
            >
              {failCount}✕
            </span>
          )}

          {/* Session 246: memory badges REMOVED from the header — memory
              activity is footer content (learning signal styles the footer
              line; episodic events feed footnoteText). */}

          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="shrink-0 p-1 rounded transition-all duration-150 hover:brightness-125 flex items-center justify-center"
            style={{ color: glowColor, border: `1px solid ${glowColor}30` }}
            aria-label={collapsed ? "Expand plan" : "Collapse plan"}
          >
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
      children={
        !collapsed ? (
          <div className="relative pl-2">
            {/* Continuous vertical hairline through all step nodes. */}
            {steps.length > 1 && (
              <div
                style={{
                  position: "absolute",
                  left: 7.5,
                  top: 10,
                  bottom: 10,
                  width: 1,
                  background: `linear-gradient(to bottom, transparent, ${glowColor}30 4px, ${glowColor}20 calc(100% - 4px), transparent)`,
                }}
              />
            )}
            <div className="flex flex-col gap-1">
              {displaySteps.map((step, i) => {
                // Session 246: guard against backend-native statuses that
                // slip through hydration ("running") — never crash the card.
                const meta = STATUS_META[step.status] ?? STATUS_META.unknown
                const isOpen = expandedStep === step.id
                const branchLabel = (step as StepWithBranch).branchLabel
                return (
                  /* Variant anatomy: branch rows indent pl-4 as a WHOLE —
                     the hierarchy shift the preview shows. */
                  <div key={step.id ?? i} className={`flex flex-col ${branchLabel ? "pl-4" : ""}`}>
                    <button
                      type="button"
                      onClick={() =>
                        step.resultPreview ? setExpandedStep(isOpen ? null : step.id) : undefined
                      }
                      className={`flex items-center gap-2 w-full text-left px-1.5 py-1 rounded-md transition-colors ${
                        step.resultPreview ? "cursor-pointer hover:bg-white/[0.03]" : ""
                      }`}
                    >
                      <ChassisStepNode
                        status={
                          step.status === "working" ? "running"
                          : step.status === "done" || step.status === "fail" || step.status === "error" || step.status === "vetoed" ? "done"
                          : "pending"
                        }
                        color={meta.color}
                      />
                      {/* Verb column — fixed width so targets align;
                          phase-driven while working (PHASE_VERB), registry
                          verb otherwise, em-dash when no real tool. */}
                      <span
                        className="w-12 shrink-0 text-left font-mono font-bold uppercase tracking-wider text-[10px] leading-snug"
                        style={{ color: stepVerb(step) ? veinColor : "rgba(255,255,255,0.2)" }}
                        title={step.toolName || undefined}
                      >
                        {stepVerb(step) ?? "—"}
                      </span>
                      {branchLabel && <ChassisBranchBadge branchLabel={branchLabel} />}
                      {/* Target — variant tokens: 10.5px mono, white/85,
                          ONE truncated line. Session 246: max-w caps long-
                          winded planner descriptions even when the row has
                          room — the full text stays on hover (title). */}
                      <span
                        className="text-[10.5px] font-mono text-white/85 truncate leading-tight flex-1 min-w-0 max-w-[52ch]"
                        style={{
                          color: step.status === "pending" ? "rgba(255,255,255,0.45)" : undefined,
                        }}
                        title={step.description}
                      >
                        {step.description}
                      </span>
                      {/* Inline summary back on the ROW TAIL (variant
                          anatomy): 9px mono white/25, max-w-[170px],
                          prefixed ·. Click opens the boxed view below. */}
                      {step.resultPreview && !isOpen ? (
                        <span
                          className="text-[9px] font-mono text-white/25 truncate max-w-[170px] shrink-0"
                          title={step.resultPreview}
                        >
                          · {step.resultPreview}
                        </span>
                      ) : null}
                    </button>
                    {/* Live-crawl under-row: ONLY while this step is
                        working — rotating host detail + source URL stream
                        beside the plan text. Once done, the summary lives
                        on the row tail above. */}
                    {step.status === "working" && (step.activeDetail || step.url) ? (
                      <span
                        className="flex flex-col gap-[3px] pl-[88px] min-w-0 pb-1"
                        style={{ color: glowColor }}
                        title={
                          step.activeDetail
                            ? `${toolLabel(step)} — ${step.activeDetail}${
                                step.activeProgress ? ` (${step.activeProgress})` : ""
                              }${step.url ? ` — ${step.url}` : ""}`
                            : toolLabel(step)
                        }
                      >
                        {step.activeDetail ? (
                          <AnimatePresence mode="wait" initial={false}>
                            <motion.span
                              key={step.activeDetail}
                              initial={{ opacity: 0, y: -3 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: 3 }}
                              transition={{ duration: 0.18 }}
                              className="truncate normal-case text-[10px] leading-snug"
                              style={{ color: "rgba(255,255,255,0.55)" }}
                            >
                              {step.activeDetail}
                              {step.activeProgress ? (
                                <span style={{ color: "rgba(255,255,255,0.35)" }}> {step.activeProgress}</span>
                              ) : null}
                            </motion.span>
                          </AnimatePresence>
                        ) : null}
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
                    {/* Expanded summary — boxed panel (variant tokens):
                        black/50 surface, hairline border, padded. */}
                    {isOpen && step.resultPreview ? (
                      <div
                        className="ml-6 mt-1 mb-1 p-2 rounded-md bg-black/50 border border-white/6 text-[9px] font-mono text-white/50 leading-relaxed break-words"
                        style={{ borderColor: "rgba(255,255,255,0.06)" }}
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
