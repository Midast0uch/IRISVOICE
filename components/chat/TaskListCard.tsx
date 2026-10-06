"use client"

import React, { useState, useEffect, useMemo, useRef, useCallback } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { ChevronDown, Copy, Check } from "lucide-react"
import { Xur } from "@/components/Xur"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useBrandPalette } from "@/hooks/useBrandPalette"
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
  /** The model's live reasoning, latest sentence (the turn's reasoning while it runs). When set it is the card's ONE
   * thinking line, under the running step ("thinking · …"), and the action-based THK strip steps aside. */
  thinking?: string
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

// Plain past-tense verbs for the personal card (concept 2: "Remembered / Searched / Ran ...").
// The registry verb stays the source; this only words it for the screen. READ is left out on
// purpose: its past tense is the same word, and the display test pins the registry text "READ"
// in the DOM — the card's CSS shows it as "Read" (sentence case, see .iris-tc-v).
const PAST_VERB: Record<string, string> = {
  WRITE: "Wrote",
  PATCH: "Edited",
  LIST: "Listed",
  ERASE: "Erased",
  EXEC: "Ran",
  DIFF: "Compared",
  COMMIT: "Committed",
  PUSH: "Pushed",
  BRANCH: "Branched",
  LOG: "Checked",
  FORGE: "GitHub",
  SEARCH: "Searched",
  FETCH: "Fetched",
  SEE: "Looked",
  SNAP: "Captured",
  CLICK: "Clicked",
  TYPE: "Typed",
  KEY: "Pressed",
  CLIP: "Clipped",
  SCRIBE: "Wrote up",
  MERGE: "Merged",
  RECALL: "Remembered",
  LEARN: "Learned",
  PACK: "Combined",
  ASK: "Asked",
  SPEAK: "Said",
  PLAN: "Planned",
  EXTRACT: "Extracted",
  CITE: "Cited",
  ANALYZE: "Analyzed",
  SYNTH: "Summed up",
  WORK: "Worked",
  DONE: "Done",
  FAILED: "Failed",
}

// A step that has not run yet keeps the plain verb ("Search"); one that ran or is running reads
// in the past tense. A tool with no known verb never leaks its compacted engine name.
function plainVerb(verb: string | null, status: TaskStepStatus): string | null {
  if (!verb) return null
  const waiting = status === "pending" || status === "unknown" || status === "skipped"
  if (waiting) return verb in PAST_VERB || verb === "READ" ? verb : "Queued"
  if (verb === "READ") return verb
  if (verb === "QUEUED") return "Worked"
  return PAST_VERB[verb] ?? "Worked"
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
  thinking,
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
  // Concept 2 colours: --b1 (accents) and --b2 (memory line) come from the brand palette.
  const [b1, b2] = useBrandPalette()

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

  // The chassis's bracketed counter keeps agreeing with the orb via deriveCurrentStep (a running
  // step is the step you are on); it stays in the DOM, and the card's goal line shows the one
  // visible "N of M steps" (finished steps only — a step in flight is not finished work).
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
  // The goal itself reads on the card's goal line; the strip keeps the rest.
  const hasEnrichment =
    schemaKeys.length > 0 ||
    !!batchMetrics ||
    !!temporalDelta?.statements.length ||
    verifiedOk.length > 0 ||
    discrepancies.length > 0

  // Concept 2 goal line + rail: one segment per top-level step (a "looked closer" child is
  // not a step of its own), the pill says in one word where the run is.
  const isChildStep = (s: TaskStep) => parentOf(s.id ?? "") !== null || !!(s as StepWithBranch).branchLabel
  const topSteps = displaySteps.filter((s) => !isChildStep(s))
  const finishedTop = topSteps.filter((s) => s.status !== "pending" && s.status !== "unknown" && s.status !== "working").length
  const retriedTop = topSteps.filter(
    (s) =>
      (s.status === "fail" || s.status === "error") &&
      displaySteps.some((c) => isChildStep(c) && parentOf(c.id ?? "") === s.id),
  ).length
  const failedOnly = Math.max(0, topSteps.filter((s) => s.status === "fail" || s.status === "error").length - retriedTop)
  const needsYou = !!asks?.some((a) => a.state === "waiting")
  const cardState: { key: string; label: string } | null = needsYou
    ? { key: "needs", label: "needs you" }
    : isWorking
      ? { key: "working", label: "working" }
      : runComplete
        ? { key: "done", label: "✓ done" }
        : steps.length > 0
          ? { key: "stopped", label: "stopped" }
          : null

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
  const showThk = !thinking && Boolean(currentAction || isWorking || hasThoughts)
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
  // On screen the engine word "crystallized" reads "Learned" (owner, 2026-10-06); the internal value stays.
  const learnedSummary = memoryEntry ? (learningSignal === "crystallized" ? "Learned" : memoryEntry.summary) : ""

  const signalTint: Record<string, string> = {
    avoided: "#f59e0b", // amber — a step was avoided (AVOID)
    retried: "#3b82f6", // blue — split into Sub-Loops
    crystallized: "#22c55e", // green — skill captured
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
    <div className="iris-tc" style={{ ["--b1" as string]: b1, ["--b2" as string]: b2 }}>
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
          /* Footer (concept 2 .foot): memory line (brand b2, truncates) · time · card id (b1).
           * Session 246: this app has an UN-LAYERED global margin/padding
             reset that overrides Tailwind v4's layered utilities, so the footer
             is laid out by the .iris-tc-* classes (css-src/globals.css), which
             set their own margins. */
          <span className="iris-tc-foot">
            {/* Session 245: the memory footer goes LIVE — learning signals get
                their own glyph + signal tint; regular memory events render their
                registry summary; only a run with zero memory activity keeps the
                quiet run-state label. The glyph flashes when a memory event lands
                (Session 246, memoryDotFlash; key re-mounts it per event). */}
            <span className="iris-tc-mem">
              <span
                aria-hidden
                key={dotFlashKey}
                style={{
                  display: "inline-block",
                  marginRight: 5,
                  animation: dotFlashKey > 0 ? "memoryDotFlash 0.8s ease-out" : undefined,
                }}
              >
                ◈
              </span>
              {learningSignal && memoryEntry ? (
                <span
                  style={{ color: signalTint[learningSignal] ?? veinColor, fontWeight: 600 }}
                  title={`Learning signal: ${learnedSummary}`}
                >
                  {memoryEntry.glyph} {learnedSummary}
                </span>
              ) : (
                <span title={footnoteText}>{footnoteText}</span>
              )}
            </span>
            {/* Session-331: the live ⏱ pill is gated on isWorking ONLY, so a
                settled run can never show a frozen live timer (the old
                `|| elapsedSec > 0` kept it after settle). The frozen-duration
                pill below covers completed/rehydrated runs. */}
            {isWorking && (
              <span className="iris-tc-time" title="Elapsed execution time">
                ⏱ {timerLabel}
              </span>
            )}
            {/* Session 246 (user ask): a REHYDRATED card shows how long the
                task took — frozen duration from the persisted record, instead
                of no timer at all. */}
            {!isWorking && elapsedSec === 0 && typeof durationSec === "number" && durationSec > 0 && (
              <span className="iris-tc-time" title="Total task duration">
                ⏱ {durationSec >= 3600
                  ? `${Math.floor(durationSec / 3600)}:${String(Math.floor((durationSec % 3600) / 60)).padStart(2, "0")}:${String(durationSec % 60).padStart(2, "0")}`
                  : `${Math.floor(durationSec / 60)}:${String(durationSec % 60).padStart(2, "0")}`}
              </span>
            )}
            {/* Session 246 (@taskcard): the card's ID lives in the footer —
                `<short-id>/memory.db` — with a one-click copy beside it, so it
                can be referenced as @taskcard:<id> from ANY conversation thread. */}
            <span className="iris-tc-idbox">
              {cardId && (
                <button
                  type="button"
                  onClick={copyCardId}
                  className="iris-tc-copy"
                  style={idCopied ? { color: "#34d399" } : undefined}
                  title={`Copy task-card ID: ${cardId}`}
                  aria-label="Copy task-card ID"
                >
                  {idCopied ? <Check size={9} /> : <Copy size={9} />}
                </button>
              )}
              <span className="iris-tc-id">
                {cardId ? `${cardId.replace(/^card_/, "")}/memory.db` : "taskcard/memory.db"}
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
            <div className="iris-tc-head">
              {/* Concept 2 top row: title · state pill · fold chevron. */}
              <div className="iris-tc-top">
                {/* Animated identity marker — variant tokens: Xur 14,
                    vein-coloured. Session 312 (UX lock): 1.8 while working; 0
                    when the run settles — Xur renders one static frame at
                    speed<=0, so the header marker STOPS when the card's
                    activity is done (user-directed 2026-09-09). */}
                <span className="iris-tc-mark">
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
                {/* Where the run is, in one word (WORKING / NEEDS YOU / ✓ DONE /
                    STOPPED — upper-cased by CSS, the text stays lower case). */}
                {cardState && (
                  <span className="iris-tc-state" data-state={cardState.key}>
                    {cardState.label}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setCollapsed((c) => !c)}
                  className="iris-tc-chev"
                  aria-label={collapsed ? "Expand plan" : "Collapse plan"}
                >
                  {collapsed ? "⌄" : "⌃"}
                </button>
              </div>
              {/* Segmented progress rail — one bar per step, coloured by state;
                  a failure takes its own red segment. */}
              {topSteps.length > 0 && (
                <div className="iris-tc-rail" aria-hidden="true">
                  {topSteps.map((s, i) => (
                    <i
                      key={s.id ?? i}
                      className={
                        s.status === "done" || s.status === "skipped"
                          ? "done"
                          : s.status === "working"
                            ? "running"
                            : s.status === "fail" || s.status === "error" || s.status === "vetoed"
                              ? "failed"
                              : ""
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        }
        children={
          !collapsed ? (
            <div>
              {/* Concept 2 goal line: "Goal · <goal> · N of M steps". The goal
                  renders ONLY from a real goalSnippet; the count is the card's one
                  visible counter. */}
              {(goalSnippet || topSteps.length > 0) && (
                <div className="iris-tc-goal">
                  {goalSnippet ? (
                    <>
                      <b>Goal</b> · <span title={goalSnippet}>{goalSnippet}</span> ·{" "}
                    </>
                  ) : null}
                  {finishedTop} of {topSteps.length} steps
                  {retriedTop > 0 ? ` · ${retriedTop} tried again` : ""}
                  {failedOnly > 0 ? <span style={{ color: "#ff7a6e" }}> · {failedOnly} failed</span> : null}
                </div>
              )}
              {/* T21 (REQ-22): goal-directed enrichment strip — the goal this
                  card serves, its extraction contract (schema field chips),
                  aggregate batch progress, cross-source verification tally and
                  temporal-diff pills. Renders ONLY when the backend emitted the
                  fields; nothing here is synthesized client-side. (The goal
                  itself reads on the goal line above.) */}
              {hasEnrichment && (
                <div className="flex flex-col gap-1 mb-1.5 px-1.5" data-testid="taskcard-enrichment">
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
                  (the first child of each row's button) and bends into this line;
                  data-task-step carries the displayed status. The FULL step list shows. */}
              <div className="iris-tc-steps" data-task-steps>
                {displaySteps.map((step, i) => {
                  // The ONE thinking line sits under the running step (else under the last one).
                  const showThinking =
                    !!thinking &&
                    (displaySteps.some((x) => x.status === "working")
                      ? displaySteps.findIndex((x) => x.status === "working") === i
                      : i === displaySteps.length - 1)
                  // Session 246: guard against backend-native statuses that
                  // slip through hydration ("running") — never crash the card.
                  const meta = STATUS_META[step.status] ?? STATUS_META.unknown
                  const isOpen = expandedStep === step.id
                  const expandable = !!step.resultPreview || (step.history?.length ?? 0) > 0
                  // A split child (<parent>_s<n>) or a backend-labelled branch row "looked closer";
                  // when it is done it has "reported back" to its parent.
                  const isSplitChild = parentOf(step.id ?? "") !== null
                  const rawBranch = (step as StepWithBranch).branchLabel
                  const branchLabel = rawBranch ? plainWords(rawBranch) : isSplitChild ? LOOKED_CLOSER : undefined
                  const reportedBack = (isSplitChild || !!rawBranch) && step.status === "done"
                  // Session 312 (user-approved): activity rows (phase nodes)
                  // indent under the plan like branch rows — same chronology,
                  // clearer parentage.
                  const isPhaseRow = step.id?.startsWith("phase-") ?? false
                  // A failed step says why on its own line (concept 2: "✕ <why> · tried again below");
                  // "tried again" only when a "looked closer" child of it really follows.
                  const failed = step.status === "fail" || step.status === "error"
                  const triedAgain = failed && displaySteps.some((c) => parentOf(c.id ?? "") === step.id)
                  const whyText = failed && step.resultPreview && !isOpen ? plainWords(step.resultPreview) : ""
                  return (
                    <div
                      key={step.id ?? i}
                      data-task-step={step.status}
                      className={`iris-tc-st${branchLabel || isPhaseRow ? " sub" : ""}`}
                    >
                      <button
                        type="button"
                        onClick={() => (expandable ? setExpandedStep(isOpen ? null : step.id) : undefined)}
                        className={`iris-tc-ln${expandable ? " click" : ""}`}
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
                        {/* Verb column — fixed width so targets align; plain past
                            tense ("Searched", "Ran") once the step ran, the plain
                            verb while it waits. Phase-driven while working
                            (PHASE_VERB). CSS shows it in sentence case. */}
                        <span className="iris-tc-v" title={step.toolName || undefined}>
                          {plainVerb(stepVerb(step), step.status) ?? "—"}
                        </span>
                        {branchLabel && <span className="iris-tc-br">↳ {branchLabel}</span>}
                        {reportedBack && (
                          <span className="iris-tc-rb" data-reported-back>
                            · {REPORTED_BACK}
                          </span>
                        )}
                        {/* Target — ONE truncated line. Session 246: the full
                            text stays on hover (title). */}
                        <span className="iris-tc-tg" title={step.description}>
                          {step.description}
                        </span>
                        {/* Short summary at the row's right end (a failed step's
                            text moves to its "✕" line below). Click opens the
                            boxed view below. */}
                        {step.resultPreview && !isOpen && !failed ? (
                          <span className="iris-tc-sm" title={step.resultPreview}>
                            {step.resultPreview}
                          </span>
                        ) : null}
                        {/* T21 (REQ-22): per-step verification state — ✓ the
                            count of cross-source-verified fields this step
                            produced; ⚠ the fields whose sources disagree. */}
                        {step.verifiedFields && Object.values(step.verifiedFields).some((v) => v?.verified) ? (
                          <span
                            className="iris-tc-ok"
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
                            className="iris-tc-ok"
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
                        <span style={{ position: "absolute", right: 0, top: 0 }}>
                          <DiffMark diffs={step.diffs} />
                        </span>
                      ) : null}
                      {/* Live lines under the running step (amber, left rule): ONLY
                          while this step is working — rotating host detail + source
                          URL stream beside the plan text. Once done, the summary
                          lives at the row's right end. */}
                      {step.status === "working" && (step.activeDetail || step.url) ? (
                        <div
                          className="iris-tc-live"
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
                              <motion.div
                                key={step.activeDetail}
                                initial={{ opacity: 0, y: -3 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: 3 }}
                                transition={{ duration: 0.18 }}
                              >
                                {step.activeDetail}
                                {step.activeProgress ? (
                                  <span style={{ color: "rgba(242,193,78,0.55)" }}> {step.activeProgress}</span>
                                ) : null}
                              </motion.div>
                            </AnimatePresence>
                          ) : null}
                          {step.url ? <div style={{ opacity: 0.7 }}>{step.url}</div> : null}
                        </div>
                      ) : null}
                      {showThinking ? (
                        <span
                          className="iris-tc-think truncate italic"
                          data-thinking-line
                          title={thinking}
                        >
                          thinking · {thinking}
                        </span>
                      ) : null}
                      {whyText ? (
                        <div className="iris-tc-why" title={whyText}>
                          ✕ {whyText}
                          {triedAgain ? " · tried again below" : ""}
                        </div>
                      ) : null}
                      {/* T21 (REQ-22/REQ-14): temporal-diff pills for THIS step —
                          visible on done rows too (the change outlives the read). */}
                      {step.temporalDelta?.statements.length ? (
                        <span className="iris-tc-pills">
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
                        <div className="iris-tc-box" style={{ color: "rgba(255,255,255,0.45)" }}>
                          {step.history!.map((h, hi) => (
                            <div key={`${step.id}-hist-${hi}`}>{h}</div>
                          ))}
                        </div>
                      ) : null}
                      {/* Expanded summary — boxed panel. */}
                      {isOpen && step.resultPreview ? <div className="iris-tc-box">{step.resultPreview}</div> : null}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : undefined
        }
      />
    </div>
  )
}
