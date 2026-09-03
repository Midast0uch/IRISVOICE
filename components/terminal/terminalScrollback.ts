/**
 * terminalScrollback — module-level scrollback store for the Developer Terminal
 * slide-over (T13 / T13a, REQ-7 / REQ-13).
 *
 * WHY MODULE-LEVEL: REQ-13 requires the terminal to preserve its scrollback
 * (command history + rendered task blocks + question lists) when the slide-over
 * is closed. Component state dies with the component; a module-level store
 * survives ANY unmount (closing the slide-over, switching to the dashboard,
 * HMR remounts) and rehydrates the panel on reopen. This is the same pattern
 * the project already uses for crawl state (CrawlProvider above the panel) and
 * the workspace store (zustand at module scope).
 *
 * The store is a plain subscriber store (no React) so it can be driven from
 * window event listeners that live for the whole session, not just while the
 * panel is mounted. It consumes the SAME events the chat cards consume:
 *   - `iris:task_update`  (task:start / task:progress / tool:call / tool:result
 *     / tool:error / task:done / task:fail — dispatched by useIRISWebSocket)
 *   - `iris:task:event`   (crawler phase fallback, same as useTaskProgress)
 *   - `iris:question_ask` / `iris:question_answered` / `iris:question_timeout`
 *   - `iris:cli_output` / `iris:cli_started` / `iris:cli_activity`
 *   - `iris:text_response`
 *
 * All rendering is plain text / ASCII box-drawing — no canvas, no xterm — which
 * is the "ASCII fallback when no canvas" requirement satisfied naturally.
 */

import { visibleWidth } from "@/lib/cli/CLITaskProgressRenderer"
import { deriveCurrentStep, type TaskStepStatus } from "@/hooks/useTaskProgress"

// ── Public types ────────────────────────────────────────────────────────────

export type TerminalLineKind = "command" | "output" | "system" | "error"

export interface TerminalLine {
  id: number
  kind: TerminalLineKind
  text: string
  ts: number
  /**
   * Provenance (cli-workspace-unification T4): lines mirrored from
   * `iris:text_response` are tagged "chat" because the unified scroll already
   * renders those as regular assistant messages — rendering them again as
   * shell output would duplicate every reply. Only untagged ("shell") lines
   * are interleaved into the timeline.
   */
  source?: "chat"
}

export interface TerminalTaskStep {
  id: string
  description: string
  status: TaskStepStatus
  toolName?: string
  activeDetail?: string
  activeProgress?: string
}

export interface TerminalTaskBlock {
  cardId: string
  planTitle?: string
  currentAction?: string
  isWorking: boolean
  steps: TerminalTaskStep[]
  currentStep: number
  totalSteps: number
  updatedAt: number
}

export interface TerminalQuestion {
  questionId: string
  text: string
  options?: string[]
  allowOther?: boolean
  timeoutSeconds?: number
  askedAt: number
}

export interface TerminalSnapshot {
  lines: TerminalLine[]
  taskBlocks: TerminalTaskBlock[]
  questions: TerminalQuestion[]
  isOpen: boolean
  /** Gate 3 T11 (REQ-6): recalled command history, newest last, bounded 200. */
  history: string[]
  /** Gate 3 T14 (REQ-5 AC3): idle / working / blocked / done. */
  sessionState: "idle" | "working" | "blocked" | "done"
  /** Gate 3 T10 (REQ-4 AC4): effective workdir shown in the panel header. */
  workdir: string
}

export interface ResolvedAnswer {
  questionId: string
  answer: string | string[]
}

// ── Bounds (quality check: memory footprint bounded) ────────────────────────

const MAX_LINES = 500
const MAX_TASK_BLOCKS = 10
const MAX_QUESTIONS = 10
const MAX_STEPS = 50
/** Gate 3 T11 (REQ-6 AC3): bounded command history. */
export const MAX_HISTORY = 200

// ── Internal state ──────────────────────────────────────────────────────────

let lines: TerminalLine[] = []
let taskBlocks: TerminalTaskBlock[] = []
let questions: TerminalQuestion[] = []
let isOpen = false
let nextId = 1
let snapshotCache: TerminalSnapshot | null = null
const listeners = new Set<() => void>()
let initialized = false

// ── Gate 3 T11/T10/T14 state ───────────────────────────────────────────────
let history: string[] = []
let historyConversationId: string | null = null
let historySaveTimer: ReturnType<typeof setTimeout> | null = null
let sessionState: "idle" | "working" | "blocked" | "done" = "idle"
let workdir = ""

/**
 * Load persisted history for a conversation (backend-backed — REQ-6 AC2
 * decided NOT localStorage: the Tauri webview's localStorage is per-webview
 * and cleared on some reinstall paths). Fire-and-forget; failure degrades to
 * in-memory-only history.
 */
export function loadHistory(conversationId: string): void {
  if (historyConversationId === conversationId) return
  historyConversationId = conversationId
  flushHistorySave()
  fetch(`/api/terminal/history?conversation_id=${encodeURIComponent(conversationId)}`)
    .then((r) => (r.ok ? r.json() : { history: [] }))
    .then((data) => {
      if (historyConversationId !== conversationId) return // switched mid-flight
      const loaded = Array.isArray(data.history) ? data.history : []
      if (loaded.length > history.length) {
        history = loaded.slice(-MAX_HISTORY)
        notify()
      }
    })
    .catch(() => { /* degraded: memory-only */ })
}

function flushHistorySave(): void {
  if (historySaveTimer) {
    clearTimeout(historySaveTimer)
    historySaveTimer = null
  }
  const conversationId = historyConversationId
  if (!conversationId) return
  fetch("/api/terminal/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId, history }),
  }).catch(() => { /* silent — REQ-12 AC3 off the latency path */ })
}

/** Record a sent command: consecutive dedupe (REQ-6 edge), bounded 200. */
export function recordHistory(command: string): void {
  const trimmed = command.trim()
  if (!trimmed) return
  if (history[history.length - 1] === trimmed) return // consecutive dedupe
  history = [...history, trimmed].slice(-MAX_HISTORY)
  notify()
  if (historySaveTimer) clearTimeout(historySaveTimer)
  historySaveTimer = setTimeout(flushHistorySave, 1500) // debounced persist
}

const recallState: { index: number; draft: string } = { index: -1, draft: "" }

/** Called after a command is SENT so recall starts fresh from the newest. */
export function resetRecall(): void {
  recallState.index = -1
  recallState.draft = ""
}

/** Recall navigation: ↑ walks back (stashing the live draft once), ↓ walks
 *  forward and returns to the stashed draft at the end. */
export function recallHistory(
  direction: "up" | "down",
  draft: string,
): { line: string | null; index: number } {
  if (history.length === 0) return { line: null, index: -1 }
  if (direction === "up") {
    if (recallState.index === -1) {
      recallState.draft = draft // REQ-6 edge: stash draft on first ArrowUp
      recallState.index = history.length - 1
    } else if (recallState.index > 0) {
      recallState.index -= 1
    }
    return { line: history[recallState.index], index: recallState.index }
  }
  // down
  if (recallState.index === -1) return { line: null, index: -1 }
  if (recallState.index < history.length - 1) {
    recallState.index += 1
    return { line: history[recallState.index], index: recallState.index }
  }
  // past newest → restore the stashed live draft
  recallState.index = -1
  const stash = recallState.draft
  recallState.draft = ""
  return { line: stash, index: -1 }
}

/** T14 (REQ-5 AC3): session state from cli_* events. */
export function setSessionState(state: "idle" | "working" | "blocked" | "done"): void {
  if (sessionState === state) return
  sessionState = state
  notify()
}

/** T10 (REQ-4 AC4): effective workdir for the header. */
export function setWorkdir(path: string): void {
  if (workdir === path) return
  workdir = path
  notify()
}

// ── Subscription / snapshot ─────────────────────────────────────────────────

function notify(): void {
  snapshotCache = null
  for (const listener of listeners) listener()
}

export function getSnapshot(): TerminalSnapshot {
  if (!snapshotCache) snapshotCache = { lines, taskBlocks, questions, isOpen, history, sessionState, workdir }
  return snapshotCache
}

export function subscribe(listener: () => void): () => void {
  ensureInit()
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

// ── Open/close (REQ-13: on-demand slide-over) ───────────────────────────────

export function setOpen(open: boolean): void {
  if (isOpen === open) return
  isOpen = open
  notify()
}

export function toggleOpen(): void {
  setOpen(!isOpen)
}

// ── Scrollback mutations ────────────────────────────────────────────────────

export function appendLine(kind: TerminalLineKind, text: string): void {
  lines = [...lines, { id: nextId++, kind, text, ts: Date.now() }].slice(-MAX_LINES)
  notify()
}

export function appendCommand(text: string): void {
  appendLine("command", `$ ${text}`)
}

export function appendOutput(text: string): void {
  const parts = text.split(/\r?\n/).filter((l) => l.length > 0)
  if (parts.length === 0) return
  const now = Date.now()
  const newLines: TerminalLine[] = parts.map((p) => ({
    id: nextId++,
    kind: "output" as const,
    text: p,
    ts: now,
  }))
  lines = [...lines, ...newLines].slice(-MAX_LINES)
  notify()
}

export function appendSystem(text: string): void {
  appendLine("system", text)
}

export function appendError(text: string): void {
  appendLine("error", text)
}

/** Explicit user action: wipe the scrollback. Does NOT close the panel. */
export function clear(): void {
  lines = []
  taskBlocks = []
  questions = []
  notify()
}

/** Test-only: full reset including open state. */
export function reset(): void {
  lines = []
  taskBlocks = []
  questions = []
  isOpen = false
  nextId = 1
  history = []
  historyConversationId = null
  recallState.index = -1
  recallState.draft = ""
  sessionState = "idle"
  workdir = ""
  notify()
}

// ── Task block reducer (mirrors useTaskProgress.reduceTaskUpdate, compact) ──

interface TaskUpdateDetail {
  type: string
  task_id?: string
  description?: string
  plan_title?: string
  action?: string
  update_step?: boolean
  detail?: string
  detail_url?: string
  detail_progress?: string
  add_step?: boolean
  step_done?: boolean
  success?: boolean
  mode?: string
  steps?: Array<{
    id: string
    description: string
    status?: string
    tool_name?: string
  }>
  total_steps?: number
  tool_name?: string
  step_number?: number
  step_id?: string
  result_summary?: string
  error?: string
  outcome?: string
  failed_steps?: Array<{ step_id?: string; description?: string }>
  cancelled?: boolean
  phase?: string
  phase_sequence?: number
  signal?: "avoided" | "retried" | "crystallized" | null
  card_id?: string
  card_relation?: "new" | "continues"
  conversation_id?: string
}

function upsertTaskBlock(block: TerminalTaskBlock): void {
  const idx = taskBlocks.findIndex((b) => b.cardId === block.cardId)
  if (idx >= 0) {
    taskBlocks = [...taskBlocks.slice(0, idx), block, ...taskBlocks.slice(idx + 1)]
  } else {
    taskBlocks = [...taskBlocks, block].slice(-MAX_TASK_BLOCKS)
  }
  notify()
}

/** Resolve the block a non-start event targets: declared card_id, else the
 *  most recently created block (legacy payloads carry no card_id). */
function resolveTargetBlockId(detail: TaskUpdateDetail): string | undefined {
  if (detail.card_id) {
    return taskBlocks.some((b) => b.cardId === detail.card_id) ? detail.card_id : undefined
  }
  return taskBlocks.length > 0 ? taskBlocks[taskBlocks.length - 1].cardId : undefined
}

function applyToBlock(
  detail: TaskUpdateDetail,
  updater: (block: TerminalTaskBlock) => TerminalTaskBlock,
): void {
  const cardId = resolveTargetBlockId(detail)
  if (!cardId) return
  const idx = taskBlocks.findIndex((b) => b.cardId === cardId)
  if (idx < 0) return
  const updated = updater(taskBlocks[idx])
  if (updated === taskBlocks[idx]) return
  taskBlocks = [...taskBlocks.slice(0, idx), updated, ...taskBlocks.slice(idx + 1)]
  notify()
}

function handleTaskStart(detail: TaskUpdateDetail): void {
  const incoming: TerminalTaskStep[] = (detail.steps || [])
    .slice(0, MAX_STEPS)
    .map((s) => ({
      id: s.id,
      description: s.description,
      status: (s.status as TaskStepStatus) ?? "unknown",
      toolName: s.tool_name,
    }))
  const cardId = detail.card_id || `legacy_${detail.task_id || "unknown"}`
  const existing = taskBlocks.find((b) => b.cardId === cardId)

  if (existing && detail.card_relation === "continues" && incoming.length > 0) {
    // Merge (same reconcile-not-wipe rule as the cards): the backend emits
    // task:start more than once per task (plan skeleton, then DER execution).
    const byId = new Map(existing.steps.map((s) => [s.id, s]))
    const merged = incoming.map((s) => {
      const ex = byId.get(s.id)
      return ex ? { ...ex, description: s.description, toolName: s.toolName } : s
    })
    for (const s of existing.steps) {
      if (!incoming.some((inc) => inc.id === s.id)) merged.push(s)
    }
    upsertTaskBlock({
      ...existing,
      isWorking: true,
      steps: merged,
      totalSteps: Math.max(merged.length, existing.currentStep),
      planTitle: detail.plan_title || existing.planTitle,
      updatedAt: Date.now(),
    })
    return
  }

  upsertTaskBlock({
    cardId,
    planTitle: detail.plan_title,
    currentAction: undefined,
    isWorking: true,
    steps: incoming,
    currentStep: 0,
    totalSteps: detail.total_steps ?? incoming.length,
    updatedAt: Date.now(),
  })
}

function handleTaskUpdate(detail: TaskUpdateDetail): void {
  switch (detail.type) {
    case "task:start":
      handleTaskStart(detail)
      break

    case "tool:call":
      applyToBlock(detail, (b) => {
        let steps = b.steps
        if (detail.step_number != null) {
          const idx = detail.step_number - 1
          if (steps[idx]) {
            const s = steps.slice()
            s[idx] = { ...s[idx], status: "working", toolName: detail.tool_name || s[idx].toolName }
            steps = s
          }
        }
        return {
          ...b,
          steps,
          isWorking: true,
          currentAction: detail.description || b.currentAction,
          updatedAt: Date.now(),
        }
      })
      break

    case "tool:result": {
      if (detail.step_number == null) break
      applyToBlock(detail, (b) => {
        const idx = detail.step_number! - 1
        if (!b.steps[idx]) return b
        const steps = b.steps.slice()
        steps[idx] = {
          ...steps[idx],
          status: "done",
          activeDetail: undefined,
          activeProgress: undefined,
        }
        return { ...b, steps, currentStep: deriveCurrentStep(steps), isWorking: true, updatedAt: Date.now() }
      })
      break
    }

    case "tool:error": {
      if (detail.step_number == null) break
      applyToBlock(detail, (b) => {
        const idx = detail.step_number! - 1
        if (!b.steps[idx]) return b
        const steps = b.steps.slice()
        steps[idx] = {
          ...steps[idx],
          status: "fail",
          activeDetail: undefined,
          activeProgress: undefined,
        }
        return { ...b, steps, currentStep: deriveCurrentStep(steps), isWorking: true, updatedAt: Date.now() }
      })
      break
    }

    case "task:progress":
      applyToBlock(detail, (b) => {
        if (detail.step_done) {
          const id = detail.step_id || `der-${detail.step_number ?? b.steps.length}`
          const idx = b.steps.findIndex((s) => s.id === id)
          if (idx < 0) return b
          const steps = b.steps.slice()
          steps[idx] = {
            ...steps[idx],
            status: detail.success === false ? "error" : "done",
            activeDetail: undefined,
            activeProgress: undefined,
          }
          return { ...b, steps, updatedAt: Date.now() }
        }
        if (detail.add_step) {
          const id = detail.step_id || `der-${detail.step_number ?? b.steps.length + 1}`
          if (b.steps.some((s) => s.id === id)) return b
          const steps = [
            ...b.steps,
            {
              id,
              description: detail.description || "Working...",
              status: "working" as TaskStepStatus,
              toolName: detail.tool_name,
            },
          ]
          return {
            ...b,
            steps,
            totalSteps: Math.max(b.totalSteps, steps.length),
            isWorking: true,
            updatedAt: Date.now(),
          }
        }
        const action = detail.description || detail.action
        if (!action) return b
        let steps = b.steps
        if (detail.update_step) {
          const workingIdx = steps.findIndex((s) => s.status === "working")
          if (workingIdx >= 0) {
            const s = steps.slice()
            s[workingIdx] = {
              ...s[workingIdx],
              activeDetail: detail.detail || action,
              activeProgress: detail.detail_progress,
            }
            steps = s
          }
        }
        return { ...b, steps, currentAction: action, isWorking: true, updatedAt: Date.now() }
      })
      break

    case "task:done":
    case "task:fail":
      applyToBlock(detail, (b) => {
        const failedIds = new Set(
          (detail.failed_steps || []).map((f) => f?.step_id).filter((x): x is string => !!x),
        )
        const taskFailed = detail.type === "task:fail" || detail.outcome === "cancelled"
        const steps = b.steps.map((s) => {
          const cleared = { ...s, activeDetail: undefined, activeProgress: undefined }
          if (failedIds.has(s.id)) return { ...cleared, status: "fail" as const }
          if (s.status === "working") {
            return { ...cleared, status: (taskFailed ? "error" : "done") as TaskStepStatus }
          }
          if (s.status === "pending" || s.status === "unknown") {
            return { ...cleared, status: "skipped" as const }
          }
          return cleared
        })
        return {
          ...b,
          isWorking: false,
          currentAction: undefined,
          steps,
          currentStep: deriveCurrentStep(steps),
          updatedAt: Date.now(),
        }
      })
      break

    default:
      break
  }
}

/** Crawler phase fallback (`iris:task:event`) — attach phase/stage/message to
 *  the most recent block, exactly as useTaskProgress does for the orb. */
function handleTaskEvent(detail: { phase?: string; stage?: string; message?: string }): void {
  if (taskBlocks.length === 0) return
  const last = taskBlocks[taskBlocks.length - 1]
  const action =
    detail.message || (detail.phase ? `${detail.phase}${detail.stage ? ` — ${detail.stage}` : ""}` : undefined)
  if (!action) return
  upsertTaskBlock({ ...last, currentAction: action, isWorking: true, updatedAt: Date.now() })
}

// ── Question handlers ───────────────────────────────────────────────────────

function handleQuestionAsk(detail: {
  question_id?: string
  text?: string
  options?: string[]
  allow_other?: boolean
  timeout_seconds?: number
}): void {
  if (!detail?.question_id || !detail?.text) return
  const idx = questions.findIndex((q) => q.questionId === detail.question_id)
  const entry: TerminalQuestion = {
    questionId: detail.question_id,
    text: detail.text,
    options: detail.options,
    allowOther: detail.allow_other,
    timeoutSeconds: detail.timeout_seconds,
    askedAt: Date.now(),
  }
  if (idx >= 0) {
    questions = [...questions.slice(0, idx), entry, ...questions.slice(idx + 1)]
  } else {
    questions = [...questions, entry].slice(-MAX_QUESTIONS)
  }
  notify()
}

function handleQuestionResolved(detail: { question_id?: string }): void {
  if (!detail?.question_id) return
  const idx = questions.findIndex((q) => q.questionId === detail.question_id)
  if (idx < 0) return
  questions = [...questions.slice(0, idx), ...questions.slice(idx + 1)]
  notify()
}

// ── Window event wiring (registered once, session-long) ─────────────────────

function ensureInit(): void {
  if (initialized) return
  initialized = true

  if (typeof window === "undefined") return

  const onTaskUpdate = (e: Event) => {
    const detail = (e as CustomEvent<TaskUpdateDetail>).detail
    if (!detail || typeof detail.type !== "string") return
    try {
      handleTaskUpdate(detail)
    } catch (err) {
      console.warn("[TerminalScrollback] task_update handler failed:", err)
    }
  }

  const onTaskEvent = (e: Event) => {
    const detail = (e as CustomEvent<{ phase?: string; stage?: string; message?: string }>).detail
    if (!detail) return
    try {
      handleTaskEvent(detail)
    } catch (err) {
      console.warn("[TerminalScrollback] task:event handler failed:", err)
    }
  }

  const onQuestionAsk = (e: Event) => {
    const detail = (e as CustomEvent<{
      question_id?: string
      text?: string
      options?: string[]
      allow_other?: boolean
      timeout_seconds?: number
    }>).detail
    if (!detail) return
    try {
      handleQuestionAsk(detail)
    } catch (err) {
      console.warn("[TerminalScrollback] question_ask handler failed:", err)
    }
  }

  const onQuestionResolved = (e: Event) => {
    const detail = (e as CustomEvent<{ question_id?: string }>).detail
    if (!detail) return
    try {
      handleQuestionResolved(detail)
    } catch (err) {
      console.warn("[TerminalScrollback] question_resolved handler failed:", err)
    }
  }

  const onCliOutput = (e: Event) => {
    const detail = (e as CustomEvent<{ line?: string }>).detail
    if (detail?.line !== undefined) appendOutput(detail.line)
  }

  // Gate 3 T1/T10: direct shell output — same panel, own event.
  const onTerminalOutput = (e: Event) => {
    const detail = (e as CustomEvent<{ line?: string }>).detail
    if (detail?.line !== undefined) appendOutput(detail.line)
    setSessionState("working") // output arriving ⇒ session alive
  }

  // Gate 3 T14 (REQ-5 AC3): badge transitions from events already on the wire.
  const onCliStartedState = () => setSessionState("working")
  const onCliActivityState = () => setSessionState("working")

  const onQuestionAskState = () => setSessionState("blocked")
  const onQuestionResolvedState = () => setSessionState("working")

  const onCliStarted = (e: Event) => {
    const detail = (e as CustomEvent<{ tool_name?: string }>).detail
    if (detail?.tool_name) appendSystem(`[${detail.tool_name} started]`)
  }

  const onCliActivity = (e: Event) => {
    const detail = (e as CustomEvent<{ tool_name?: string }>).detail
    if (detail?.tool_name) appendSystem(`[tool: ${detail.tool_name}]`)
  }

  const onTextResponse = (e: Event) => {
    const detail = (e as CustomEvent<{ text?: string }>).detail
    if (detail?.text) {
      const parts = detail.text.split(/\r?\n/).filter((l) => l.length > 0)
      if (parts.length === 0) return
      const now = Date.now()
      lines = [
        ...lines,
        ...parts.map((p) => ({
          id: nextId++,
          kind: "output" as const,
          text: p,
          ts: now,
          source: "chat" as const,
        })),
      ].slice(-MAX_LINES)
      notify()
    }
  }

  window.addEventListener("iris:task_update", onTaskUpdate)
  window.addEventListener("iris:task:event", onTaskEvent)
  window.addEventListener("iris:question_ask", (e) => {
    onQuestionAsk(e)
    onQuestionAskState()
  })
  window.addEventListener("iris:question_answered", (e) => {
    onQuestionResolved(e)
    onQuestionResolvedState()
  })
  window.addEventListener("iris:question_timeout", (e) => {
    onQuestionResolved(e)
    onQuestionResolvedState()
  })
  window.addEventListener("iris:cli_output", onCliOutput)
  window.addEventListener("iris:cli_started", (e) => {
    onCliStarted(e)
    onCliStartedState()
  })
  window.addEventListener("iris:cli_activity", (e) => {
    onCliActivity(e)
    onCliActivityState()
  })
  window.addEventListener("iris:text_response", (e) => {
    onTextResponse(e)
    setSessionState("done") // a completed turn settles the badge
  })
  // Gate 3 T1: direct shell output stream.
  window.addEventListener("iris:terminal_output", onTerminalOutput)
}

// ── ASCII renderers (text-only — the "no canvas" fallback) ──────────────────

const BOX_INNER = 56

function boxTop(): string {
  return `┌${"─".repeat(BOX_INNER + 2)}┐`
}
function boxSep(): string {
  return `├${"─".repeat(BOX_INNER + 2)}┤`
}
function boxBottom(): string {
  return `└${"─".repeat(BOX_INNER + 2)}┘`
}
function boxRow(content: string): string {
  const pad = Math.max(0, BOX_INNER - visibleWidth(content))
  return `│ ${content}${" ".repeat(pad)} │`
}
function truncateTo(text: string, max: number): string {
  if (visibleWidth(text) <= max) return text
  const budget = Math.max(1, max - 1)
  let out = ""
  let w = 0
  for (const ch of text) {
    const cw = visibleWidth(ch)
    if (w + cw > budget) break
    out += ch
    w += cw
  }
  return `${out}…`
}

const STEP_MARKERS: Record<TaskStepStatus, string> = {
  working: "►",
  done: "✓",
  fail: "✗",
  error: "✗",
  skipped: "–",
  vetoed: "⊘",
  pending: "○",
  unknown: "○",
}

/** Compact ASCII task block: plan title, step list with the working step
 *  marked, and the current action line. */
export function renderTaskBlockAscii(block: TerminalTaskBlock): string[] {
  const out: string[] = []
  const title = block.planTitle || "Task"
  out.push(boxTop())
  out.push(boxRow(`TASK: ${truncateTo(title, BOX_INNER - 6)}`))
  if (block.steps.length > 0) {
    out.push(boxSep())
    for (const s of block.steps) {
      const marker = STEP_MARKERS[s.status] ?? "○"
      const detail = s.activeDetail
        ? ` — ${s.activeDetail}${s.activeProgress ? ` (${s.activeProgress})` : ""}`
        : ""
      out.push(boxRow(`${marker} ${truncateTo(s.description + detail, BOX_INNER - 4)}`))
    }
  }
  if (block.currentAction) {
    out.push(boxSep())
    out.push(boxRow(`▸ ${truncateTo(block.currentAction, BOX_INNER - 3)}`))
  }
  out.push(boxBottom())
  return out
}

/** Numbered question block — a developer answers by typing the number or the
 *  answer text into the terminal input (routed via the REQ-6 funnel). */
export function renderQuestionAscii(q: TerminalQuestion, index: number): string[] {
  const out: string[] = []
  out.push(boxTop())
  out.push(boxRow(`QUESTION ${index}: ${truncateTo(q.text, BOX_INNER - 13)}`))
  const opts = q.options || []
  if (opts.length > 0) {
    out.push(boxSep())
    opts.forEach((opt, i) => {
      out.push(boxRow(`  ${i + 1}. ${truncateTo(opt, BOX_INNER - 6)}`))
    })
  }
  if (q.allowOther) {
    out.push(boxSep())
    out.push(boxRow("  (free text allowed)"))
  }
  out.push(boxSep())
  out.push(boxRow("  Answer: type the number or the answer text"))
  out.push(boxBottom())
  return out
}

// ── REQ-6 answer resolution (the SAME funnel the QuestionCard uses) ─────────
//
// The QuestionCard resolves an answer by calling
// `sendMessage('question_response', { question_id, answer })`. The terminal
// input handler calls THIS resolver to decide whether an input is an answer,
// then routes the result through that exact same call — never a separate path.
//
// Resolution order (documented, deterministic):
//   1. Exact option-text match against any pending question (case-insensitive).
//   2. "<N> <answer>" — question index N, then an option index or free text.
//   3. Bare number N — option index of the first pending question if it has
//      options, else question index N (first option, or the number as text).
//   4. Free text — ONLY when exactly one pending question exists, it has no
//      options, and the input is not a shell command (`/` or `>` prefix).
//      This keeps shell commands from being hijacked by a pending question.
export function resolveTerminalAnswer(
  input: string,
  pending: TerminalQuestion[],
): ResolvedAnswer | null {
  if (pending.length === 0) return null
  const trimmed = input.trim()
  if (!trimmed) return null

  // 1. Exact option-text match.
  for (const q of pending) {
    const match = (q.options || []).find((o) => o.toLowerCase() === trimmed.toLowerCase())
    if (match) return { questionId: q.questionId, answer: match }
  }

  // 2. "<N> <answer>".
  const twoPart = trimmed.match(/^(\d+)\s+(.+)$/)
  if (twoPart) {
    const qIdx = parseInt(twoPart[1], 10) - 1
    const q = pending[qIdx]
    if (q) {
      const rest = twoPart[2].trim()
      const optIdx = parseInt(rest, 10)
      const opts = q.options || []
      if (!Number.isNaN(optIdx) && optIdx >= 1 && optIdx <= opts.length) {
        return { questionId: q.questionId, answer: opts[optIdx - 1] }
      }
      return { questionId: q.questionId, answer: rest }
    }
  }

  // 3. Bare number.
  const bareNum = trimmed.match(/^(\d+)$/)
  if (bareNum) {
    const n = parseInt(bareNum[1], 10)
    const first = pending[0]
    const firstOpts = first.options || []
    if (firstOpts.length > 0 && n >= 1 && n <= firstOpts.length) {
      return { questionId: first.questionId, answer: firstOpts[n - 1] }
    }
    const q = pending[n - 1]
    if (q) {
      const opts = q.options || []
      if (opts.length > 0) return { questionId: q.questionId, answer: opts[0] }
      return { questionId: q.questionId, answer: trimmed }
    }
  }

  // 4. Free text for a lone optionless question (never hijacks shell input).
  if (pending.length === 1 && !trimmed.startsWith("/") && !trimmed.startsWith(">")) {
    const q = pending[0]
    const opts = q.options || []
    if (opts.length === 0) return { questionId: q.questionId, answer: trimmed }
  }

  return null
}

export const TERMINAL_HELP = [
  "Available commands:",
  "  <command>          run in the shell (terminal_input)",
  "  /run <request>     delegate to IRIS (dev_cli — IRIS's own agent runs it)",
  "  >term              open/close this terminal",
  "  clear              clear the scrollback",
  "  help               show this help",
  "  <number> [answer]  answer a pending question (see QUESTION blocks above)",
].join("\n")