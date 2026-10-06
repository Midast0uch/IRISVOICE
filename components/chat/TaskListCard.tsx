"use client"

import React, { useState, useEffect, useMemo, useRef, useCallback } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { ChevronDown, Copy, Check, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { deriveCurrentStep } from "@/hooks/useTaskProgress"
import type {
  TaskStep,
  TaskStepStatus,
  MemoryEvent,
  BatchMetrics,
  TemporalDeltaInfo,
  VerifiedField,
} from "@/hooks/useTaskProgress"
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
import { LOOKED_CLOSER, REPORTED_BACK, plainWords } from "@/lib/cards/plainWords"
import { parentOf } from "@/components/chat/matrix/matrixModel"
import { DiffMark } from "@/components/chat/diff/DiffMark"
import { AskPrompt, type AskActions } from "@/components/chat/turn/AskPrompt"
import type { AskItem } from "@/lib/turns/asks"

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
  /**
   * T21 (REQ-22): goal-directed enrichment — the card-level aggregates
   * reduced by useTaskProgress (T20). All optional; each renders ONLY when
   * present, never as a placeholder (phantom UI = fabrication).
   * - `goalSnippet`: one-line goal this card serves.
   * - `extractedSchema`: the declared 12-keyword output contract.
   * - `batchMetrics`: DAG batch pool counters (total/done/failed/inFlight/
   *   rateLimited).
   * - `temporalDelta`: natural-language deltas vs the prior snapshot pill row.
   * - `verifiedFields`: cross-source verification per extracted field.
   */
  goalSnippet?: string
  extractedSchema?: Record<string, unknown>
  batchMetrics?: BatchMetrics
  temporalDelta?: TemporalDeltaInfo
  verifiedFields?: Record<string, VerifiedField>
  /** IRIS asks of this turn (a permission or a question), drawn inside the card; a settled
   * one stays as the receipt line. */
  asks?: AskItem[]
  askActions?: AskActions
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
  [/summari|explain|synthes|conclude|final|combin/i, "SYNTH"],
  // Session 312 (live conv-98): "Combine the recalled findings..." matched
  // /find/ inside "findings" and rendered SEARCH on a synthesis step.
  // Combining prior results into an answer IS synthesis — "combin" sits in
  // the SYNTH row (first match wins, so it beats the /find/ row below).
  // Session 247: crawler phase-node labels ("Extracting content",
  // "Citing sources", "Reading X") must map to their OWN verbs — "extract"
  // previously fell into ANALYZE and "citing" matched nothing (blank/DONE).
  // These sit ABOVE the generic families; first match wins.
  [/extract/i, "EXTRACT"],
  [/cit(e|ing|ation)/i, "CITE"],
  [/analyz|identif|compare|evaluat/i, "ANALYZE"],
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
  goalSnippet,
  extractedSchema,
  batchMetrics,
  temporalDelta,
  verifiedFields,
  asks,
  askActions,
}: TaskListCardProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color

  const [collapsed, setCollapsed] = useState(defaultCollapsed && steps.length > 4)
  const [expandedStep, setExpandedStep] = useState<string | null>(null)
  const [thkOpen, setThkOpen] = useState(false)
  // Session 246 (@taskcard): copy-feedback for the footer ID chrome.
  const [idCopied, setIdCopied] = useState(false)
  // Session 312 (wave glyph): mirrored audio phase from useIRISWebSocket
  // (iris:audio_phase). When IRIS is SPEAKING, the currently working row
  // shows a faint wave glyph — the narrated activity and the row are the
  // same thing while a crawl narrates its pages. Never shown on settled
  // rows (honesty: no row claims speech it didn't carry).
  const [narrating, setNarrating] = useState(false)
  useEffect(() => {
    function onPhase(e: Event) {
      setNarrating((e as CustomEvent).detail?.phase === "speaking")
    }
    window.addEventListener("iris:audio_phase", onPhase)
    return () => window.removeEventListener("iris:audio_phase", onPhase)
  }, [])
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

  // ── T21 (REQ-22, wave 4): goal-directed enrichment derivations ────────
  // Everything in this block renders ONLY from payloads the backend actually
  // emitted (reduced by useTaskProgress). Absent fields render NOTHING — a
  // phantom badge is a fabricated claim.
  const schemaKeys = extractedSchema?.properties
    ? Object.keys(extractedSchema.properties as Record<string, unknown>).slice(0, 6)
    : []
  const verifiedEntries = verifiedFields ? Object.entries(verifiedFields) : []
  const verifiedOk = verifiedEntries.filter(([, v]) => v?.verified)
  const discrepancies = verifiedEntries.filter(([, v]) => v?.discrepancy)
  const hasEnrichment =
    !!goalSnippet ||
    schemaKeys.length > 0 ||
    !!batchMetrics ||
    !!temporalDelta?.statements.length ||
    verifiedOk.length > 0 ||
    discrepancies.length > 0

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
    // Session 248 (pin_587a3e612558 item #4): a progressive phase node
    // declares its phase — derive the verb from PHASE_VERB[phase] DIRECTLY,
    // for the node's whole life (not just while working). Keyword-matching
    // the description is what rendered a fetching-phase node as SEARCH.
    if (s.phase) {
      const pv = PHASE_VERB[s.phase.toLowerCase()]
      if (pv) return pv
    }
    if (s.status === "working" && phase) {
      const pv = PHASE_VERB[phase.toLowerCase()]
      if (pv) return pv
    }
    if (s.toolName && !MODE_NON_TOOLS.has(s.toolName.toLowerCase())) {
      return resolveVerb(s.toolName)
    }
    const intent = intentVerb(s.description)
    if (intent) return intent
    // Session 247 (user finding): NO step may render a blank/em-dash verb.
    // When neither the tool registry nor the description keywords resolve,
    // the step's STATUS is honest, informative, and always available.
    switch (s.status) {
      case "working": return "WORK"
      case "done": return "DONE"
      case "error":
      case "fail": return "FAILED"
      default: return "QUEUED"
    }
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
  // (recall/compress/episodic), falling back to a run-state label.
  //
  // Session-331 (live T3): the old fallback was a bare "Active Execution"
  // whenever there were no memory events — with NO terminal branch. A settled
  // card whose grade fired (task:fail/task:done) therefore still read "Active
  // Execution" with a frozen timer, visually identical to a live run. The
  // label is now a function of the run state: only claim "Active Execution"
  // while the run is actually live; once settled, name the real outcome from
  // the steps. Never fabricate liveness.
  const footnoteText = useMemo(() => {
    const last = memoryEvents?.[memoryEvents.length - 1]
    if (last) return plainWords(formatMemoryEntry(last.kind, last.data)?.summary ?? last.kind)
    if (isWorking) return "Active Execution"
    if (steps.some((s) => s.status === "fail" || s.status === "error")) {
      return "Run failed"
    }
    if (steps.length > 0 && steps.every((s) => s.status === "done" || s.status === "skipped")) {
      return "Run complete"
    }
    if (steps.length > 0) return "Run ended"
    return "Idle"
  }, [memoryEvents, isWorking, steps])

  // Session 246: the footer memory line takes the KIND's tint so episodic
  // activity is visibly alive (amber) vs recall (violet) vs compress (cyan).
  const lastMemoryTint = useMemo(() => {
    const last = memoryEvents?.[memoryEvents.length - 1]
    return last ? MEMORY_TINT[last.kind] ?? null : null
  }, [memoryEvents])

  // Asks live in the subheader, so a waiting ask shows even when the plan is folded.
  const asksNode =
    askActions && asks && asks.length > 0 ? (
      <div className="flex flex-col gap-1.5 min-w-0" data-task-asks>
        {asks.map((a) => (
          <AskPrompt key={a.id} ask={a} variant="card" glowColor={glowColor} actions={askActions} />
        ))}
      </div>
    ) : null

  return (
    <CardChassis
      veinColor={veinColor}
      isActive={isWorking}
      collapsible={false}
      counter={{ done: displayStep, total: steps.length }}
      aria-label="Task progress"
      subheader={
        showThk || asksNode ? (
          <div className="flex flex-col gap-1.5 min-w-0">
        {showThk ? (
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
        ) : null}
        {asksNode}
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
            {/* Session-331: the live ⏱ pill is gated on isWorking ONLY, so a
                settled run can never show a frozen live timer (the old
                `|| elapsedSec > 0` kept it after settle). The frozen-duration
                pill below covers completed/rehydrated runs. */}
            {isWorking && (
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
          {/* Animated identity marker — variant tokens: Xur 14,
              vein-coloured, 0.6 while idle/finished and 1.8 while working —
              the header goes static when the run settles (Session 312 UX
              lock). The websearch Search icon
              is gone: the objective itself carries the context now.
           * Session 246: marginLeft keeps the marker's centre on the SAME
              vertical axis as the body step nodes and the footer dot — one
              continuous left rail (user-requested symmetry). Axis math:
              pl-3(12) + body pl-2(8) + row px-1.5(6) + half node box(8) = 34;
              34 - 12 - 7 = 15. */}
          <span style={{ display: "flex", marginLeft: 15 }}>
            {/* Session 312 (UX lock): 1.8 while working; 0 when the run
                settles — Xur renders one static frame at speed<=0, so the
                header marker STOPS when the card's activity is done
                (user-directed 2026-09-09). */}
            <Xur size={14} color={veinColor} speed={isWorking ? 1.8 : 0} />
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
            {/* T21 (REQ-22): goal-directed enrichment strip — the goal this
                card serves, its extraction contract (schema field chips),
                aggregate batch progress, cross-source verification tally and
                temporal-diff pills. Renders ONLY when the backend emitted the
                fields; nothing here is synthesized client-side. */}
            {hasEnrichment && (
              <div className="flex flex-col gap-1 mb-1.5 px-1.5" data-testid="taskcard-enrichment">
                {goalSnippet ? (
                  <div
                    className="text-[9.5px] font-mono truncate"
                    style={{ color: "rgba(255,255,255,0.45)" }}
                    title={goalSnippet}
                  >
                    {goalSnippet}
                  </div>
                ) : null}
                {schemaKeys.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {schemaKeys.map((k) => (
                      <span
                        key={k}
                        className="px-1 rounded text-[8px] font-mono leading-[14px]"
                        style={{
                          border: "1px solid rgba(255,255,255,0.10)",
                          color: "rgba(255,255,255,0.5)",
                          background: "rgba(255,255,255,0.03)",
                        }}
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                ) : null}
                {batchMetrics?.total ? (
                  <div className="text-[9px] font-mono tabular-nums" style={{ color: "rgba(255,255,255,0.5)" }}>
                    batch {Math.min(batchMetrics.done ?? 0, batchMetrics.total)}/{batchMetrics.total}
                    {batchMetrics.inFlight ? ` · ${batchMetrics.inFlight} in flight` : ""}
                    {batchMetrics.rateLimited ? (
                      <span style={{ color: "#fbbf24" }}> · {batchMetrics.rateLimited} rate-limited</span>
                    ) : null}
                  </div>
                ) : null}
                {verifiedOk.length > 0 || discrepancies.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-1" aria-label="cross-source verification">
                    {verifiedOk.map(([field, v]) => (
                      <span
                        key={field}
                        className="inline-flex items-center gap-0.5 px-1 rounded text-[8px] font-mono leading-[14px]"
                        style={{
                          border: "1px solid rgba(52,211,153,0.25)",
                          color: "#34d399",
                          background: "rgba(52,211,153,0.06)",
                        }}
                        title={`${field}: corroborated across ${v.corroborations ?? "≥2"} sources`}
                      >
                        <Check size={7} aria-hidden /> {field}
                      </span>
                    ))}
                    {/* REQ-11 AC4: irreconcilable numbers stay visible with
                        their source context — a discrepancy is a FINDING, not
                        a state to hide. */}
                    {discrepancies.map(([field, v]) => (
                      <span
                        key={field}
                        className="inline-flex items-center gap-0.5 px-1 rounded text-[8px] font-mono leading-[14px]"
                        style={{
                          border: "1px solid rgba(251,191,36,0.30)",
                          color: "#fbbf24",
                          background: "rgba(251,191,36,0.06)",
                        }}
                        title={`${field}: sources disagree${v.note ? ` — ${v.note}` : ""}`}
                      >
                        ⚠ {field}
                      </span>
                    ))}
                  </div>
                ) : null}
                {temporalDelta?.statements.length ? (
                  <div className="flex flex-wrap gap-1" aria-label="temporal changes">
                    {temporalDelta.statements.map((s, i) => (
                      <span
                        key={`${i}-${s.slice(0, 16)}`}
                        className="px-1 rounded text-[8px] font-mono leading-[14px]"
                        style={{
                          border: `1px solid ${glowColor}38`,
                          color: glowColor,
                          background: `${glowColor}0d`,
                        }}
                        title={s}
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            )}
            {/* data-task-steps / data-task-step: the timeline spine measures the step dots
                and bends into this line; data-task-step carries the displayed status. */}
            <div className="flex flex-col gap-1" data-task-steps>
              {displaySteps.map((step, i) => {
                // Session 246: guard against backend-native statuses that
                // slip through hydration ("running") — never crash the card.
                const meta = STATUS_META[step.status] ?? STATUS_META.unknown
                const isOpen = expandedStep === step.id
                // A split child (<parent>_s<n>) or a backend-labelled branch row "looked closer";
                // when it is done it has "reported back" to its parent.
                const isSplitChild = parentOf(step.id ?? "") !== null
                const rawBranch = (step as StepWithBranch).branchLabel
                const branchLabel = rawBranch ? plainWords(rawBranch) : isSplitChild ? LOOKED_CLOSER : undefined
                const reportedBack = (isSplitChild || !!rawBranch) && step.status === "done"
                // Session 312 (user-approved): activity rows (phase nodes)
                // indent under the plan like branch rows — same chronology,
                // clearer parentage. Settled rows dim slightly so the eye
                // lands on the working row first (colors unchanged).
                const isPhaseRow = step.id?.startsWith("phase-") ?? false
                const settled =
                  step.status === "done" ||
                  step.status === "fail" ||
                  step.status === "error" ||
                  step.status === "skipped"
                return (
                  /* Variant anatomy: branch rows indent pl-4 as a WHOLE —
                     the hierarchy shift the preview shows. */
                  <div
                    key={step.id ?? i}
                    data-task-step={step.status}
                    className={`flex flex-col ${branchLabel || isPhaseRow ? "pl-4" : ""}`}
                    style={{
                      opacity: settled ? 0.75 : 1,
                      transition: "opacity 0.4s ease",
                      position: "relative",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        step.resultPreview || (step.history?.length ?? 0) > 0
                          ? setExpandedStep(isOpen ? null : step.id)
                          : undefined
                      }
                      className={`flex items-center gap-2 w-full text-left px-1.5 py-1 rounded-md transition-colors ${
                        step.resultPreview || (step.history?.length ?? 0) > 0
                          ? "cursor-pointer hover:bg-white/[0.03]"
                          : ""
                      }`}
                      // room for the ± that sits at the end of an editing step's row
                      style={step.diffs?.length ? { paddingRight: 30 } : undefined}
                    >
                      <ChassisStepNode
                        status={
                          step.status === "working" ? "running"
                          : step.status === "done" || step.status === "fail" || step.status === "error" || step.status === "vetoed" ? "done"
                          : "pending"
                        }
                        color={meta.color}
                      />
                      {/* Session 312 (wave glyph): faint marker on the row
                          whose activity IRIS is narrating RIGHT NOW. Amber
                          (the working palette) at half opacity — faint by
                          design, tooltip names it. Only on working rows. */}
                      {narrating && step.status === "working" ? (
                        <span
                          aria-label="IRIS is narrating this step"
                          title="IRIS is narrating this step"
                          style={{
                            fontSize: 10,
                            lineHeight: 1,
                            color: "#fbbf24",
                            opacity: 0.5,
                            flexShrink: 0,
                          }}
                        >
                          〰
                        </span>
                      ) : null}
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
                      {reportedBack && (
                        <span className="shrink-0 text-[9px] font-mono" style={{ color: "rgba(255,255,255,0.4)" }} data-reported-back>
                          · {REPORTED_BACK}
                        </span>
                      )}
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
                      {/* T21 (REQ-22): per-step verification state — ✓ the
                          count of cross-source-verified fields this step
                          produced; ⚠ the fields whose sources disagree. */}
                      {step.verifiedFields && Object.values(step.verifiedFields).some((v) => v?.verified) ? (
                        <span
                          className="shrink-0 text-[9px] font-mono"
                          style={{ color: "#34d399" }}
                          title={Object.entries(step.verifiedFields)
                            .filter(([, v]) => v?.verified)
                            .map(([f]) => f)
                            .join(", ")}
                        >
                          ✓{Object.values(step.verifiedFields).filter((v) => v?.verified).length}
                        </span>
                      ) : null}
                      {step.verifiedFields && Object.values(step.verifiedFields).some((v) => v?.discrepancy) ? (
                        <span
                          className="shrink-0 text-[9px] font-mono"
                          style={{ color: "#fbbf24" }}
                          title={Object.entries(step.verifiedFields)
                            .filter(([, v]) => v?.discrepancy)
                            .map(([f]) => f)
                            .join(", ")}
                        >
                          ⚠
                        </span>
                      ) : null}
                    </button>
                    {/* ± where this step edited a file: opens the review in the lens. */}
                    {step.diffs && step.diffs.length > 0 ? (
                      <span style={{ position: "absolute", right: 4, top: 4 }}>
                        <DiffMark diffs={step.diffs} />
                      </span>
                    ) : null}
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
                    {/* T21 (REQ-22/REQ-14): temporal-diff pills for THIS step —
                        visible on done rows too (the change outlives the read). */}
                    {step.temporalDelta?.statements.length ? (
                      <span className="flex flex-wrap gap-1 pl-[88px] min-w-0 pb-1">
                        {step.temporalDelta.statements.map((s, i) => (
                          <span
                            key={`${step.id}-td-${i}`}
                            className="px-1 rounded text-[8px] font-mono leading-[14px]"
                            style={{
                              border: `1px solid ${glowColor}38`,
                              color: glowColor,
                              background: `${glowColor}0d`,
                            }}
                            title={s}
                          >
                            {s}
                          </span>
                        ))}
                      </span>
                    ) : null}
                    {/* Session 312 (expand-on-demand history): the bounded
                        activity trail this row accumulated while working —
                        newest last, capped at 6 by the reducer. Renders ONLY
                        from real streamed detail (REQ-10 AC4: no fabrication). */}
                    {isOpen && (step.history?.length ?? 0) > 0 ? (
                      <div
                        className="ml-6 mt-1 p-2 rounded-md bg-black/50 border border-white/6 text-[9px] font-mono leading-relaxed break-words"
                        style={{ borderColor: "rgba(255,255,255,0.06)" }}
                      >
                        {step.history!.map((h, hi) => (
                          <div
                            key={`${step.id}-hist-${hi}`}
                            style={{ color: "rgba(255,255,255,0.35)" }}
                          >
                            {h}
                          </div>
                        ))}
                      </div>
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
