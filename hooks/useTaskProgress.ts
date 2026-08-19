"use client"

import { useEffect, useMemo, useRef, useState } from "react"

export type TaskStepStatus =
  /** Step has no event record at all - semantically absent but visually pending. */
  | "unknown"
  | "pending"
  | "working"
  | "done"
  | "skipped"
  | "vetoed"
  | "error"
  | "fail"

export interface TaskStep {
  id: string
  /**
   * The PLAN text - what the agent set out to do. Stable for the life of the
   * step. Live progress never overwrites this; it goes to `activeDetail` so the
   * dropdown keeps showing the plan while the card header shows the activity.
   */
  description: string
  status: TaskStepStatus
  toolName?: string
  /**
   * Live, rotating detail for the step currently executing - the source being
   * read (e.g. "example.com"), shown beside `toolName`. Cleared when the step
   * resolves, so a finished step never appears to still be working on a page.
   */
  activeDetail?: string
  /** Progress within the active detail, e.g. "2/5". */
  activeProgress?: string
  /**
   * pin_517dfcbda150 (F1): the URL of the page currently being read -
   * the crawler's per-page TASK_PROGRESS carries `detail_url`; previously
   * the frontend dropped it (only `detail`/title was consumed).
   */
  url?: string
  resultPreview?: string
}

/**
 * Which step number to display as "current".
 *
 * OFF BY ONE UNTIL 2026-08-17: this was a plain count of `done` steps, so while
 * step 3 of 4 was executing the card read "2/4" and the orb radial sat a step
 * behind the work the user could see happening. It was easy to miss when every
 * step took ~90 s; once the turn dropped to ~45 s the lag became the obvious
 * symptom.
 *
 * A step that is RUNNING is the step you are on, so it counts. Falls back to the
 * completed count when nothing is in flight (start of turn, and after the last
 * step resolves) - so the card still finishes on N/N rather than claiming a step
 * that never ran.
 */
export function deriveCurrentStep(steps: TaskStep[]): number {
  const workingIdx = steps.findIndex((s) => s.status === "working")
  if (workingIdx >= 0) return workingIdx + 1
  return steps.filter((s) => s.status === "done").length
}

/**
 * One task's execution surface (T6, REQ-3/REQ-4). Everything a card needs to
 * render on its own, plus the identity the backend declared for it
 * (`_task_start_payload` / `_resolve_card_identity`, agent_kernel.py:7660).
 */
export interface TaskCard {
  cardId: string
  /** Which conversation this card belongs to (REQ-4 AC3: a card must never
   * appear in a conversation it was not created in). `null` for cards seen
   * before any conversation id was known. */
  conversationId: string | null
  isWorking: boolean
  currentStep: number
  totalSteps: number
  steps: TaskStep[]
  mode?: string
  turnId?: string
  planTitle?: string
  currentAction?: string
  phase?: string
  phaseSequence?: number
  learningSignal?: "avoided" | "retried" | "crystallized" | null
  /**
   * T7a (REQ-4 AC5): the persisted store's terminal state, present ONLY on a
   * card that arrived via rehydration (`get_cards`) — a live card never sets
   * this. Carries `"done" | "fail" | "terminated_unknown"` straight through
   * from `ConversationContextStore.get_cards_for_conversation`, which already
   * resolves a card orphaned mid-run ("running" on read) into
   * "terminated_unknown" — that decision is made once, on the backend, and
   * transported here verbatim rather than re-derived on the frontend.
   */
  terminalState?: string
}

export interface TaskProgress {
  isWorking: boolean
  currentStep: number
  totalSteps: number
  steps: TaskStep[]
  mode?: string
  turnId?: string
  planTitle?: string
  /** Live action text from `task:progress` (e.g. "Reading example.com (2/5)"). */
  currentAction?: string
  /**
   * REQ-4: structured phase label from the crawl pipeline (searching / fetching /
   * extracting / citing). Consumed by ContextPill to show the user what stage
   * the agent is in. Cleared when the task ends.
   */
  phase?: string
  /** Monotonic sequence number for the phase, stable per label. */
  phaseSequence?: number
  /**
   * REQ-8: honest learning signal from `task:learning` (avoided / retried /
   * crystallized). Drives the Pacman OrbCanvas particles on the TaskListCard
   * border. `null` when no live signal this task.
   */
  learningSignal?: "avoided" | "retried" | "crystallized" | null
  /**
   * T6 (REQ-3/REQ-4): every card belonging to the conversation currently being
   * viewed, in the order they were created/first seen. The single-card fields
   * above are DERIVED from the active card in this list (see `deriveActiveCard`)
   * purely so consumers that predate multi-card (XurOrb, several tests) keep
   * reading a coherent single card without change.
   */
  cards: TaskCard[]
}

const MAX_STEPS = 50
// Per-conversation card cap (REQ-4 edge case): a conversation that never stops
// producing cards must not leak memory one entry per task forever. Eviction
// drops the OLDEST card WHOLE, never a partial one.
const MAX_CARDS_PER_CONVERSATION = 30
// How many conversations' card maps this hook keeps in memory at once. Bounds
// total footprint for a long session that visits many conversations - the
// least-recently-touched conversation's ENTIRE card map is dropped, never a
// partial one, same rule as the per-conversation cap above.
const MAX_TRACKED_CONVERSATIONS = 20
// Sentinel bucket for events that arrive before any conversation id is known
// (fresh mount, or a legacy payload with neither card_id nor conversation_id).
const NO_CONVERSATION = "__no_conversation__"

interface TaskUpdateDetail {
  type: string
  task_id?: string
  description?: string
  plan_title?: string
  action?: string
  update_step?: boolean
  /** Structured live detail (host/title being read) - preferred over parsing `description`. */
  detail?: string
  detail_url?: string
  detail_progress?: string
  /** When true, append a new step (DER discovered a live step). */
  add_step?: boolean
  /** When true, mark the step (der-{step_number}) as done/error. */
  step_done?: boolean
  /** Step outcome for step_done (false => error state). */
  success?: boolean
  mode?: string
  steps?: TaskStep[]
  total_steps?: number
  tool_name?: string
  step_number?: number
  /** pin_517dfcbda150: unique backend step id for add_step / step_done - plan
   * steps carry planner ids (r1, step_1), split children carry parent_s{i}. */
  step_id?: string
  result_summary?: string
  error?: string
  outcome?: string
  steps_completed?: number
  /** Steps the DER loop recorded as failed, sent on task:done / task:fail. The
   * backend has always sent this and the card ignored it, so a run that failed a
   * step showed no sign of it once the card stopped moving. */
  failed_steps?: Array<{ step_id?: string; description?: string }>
  cancelled?: boolean
  /** REQ-4: structured phase label from the crawl pipeline. */
  phase?: string
  /** Stable phase sequence number (1..N) for disambiguating re-emission. */
  phase_sequence?: number
  /** REQ-8: honest learning signal from `task:learning`. */
  signal?: "avoided" | "retried" | "crystallized" | null
  /**
   * T1/T6 (REQ-3): the backend-declared card identity. Carried on
   * `task:start` and every lifecycle event for the same card's life
   * (`_card_envelope`, agent_kernel.py:7786). ABSENT on a legacy payload -
   * see REQ-3's edge case, handled by the legacy fallback below.
   */
  card_id?: string
  /** "new" mints an additional card; "continues" extends the card already
   * bearing `card_id`. Decided entirely on the backend (REQ-3 AC5). */
  card_relation?: "new" | "continues"
  /** T1/T6 (REQ-4): which conversation this event's card belongs to. */
  conversation_id?: string
}

// Maps a tool name to a short, human-readable action title for the plan card.
// Derived from the tool the agent is actually executing (not the user's prompt),
// so the card reads "WebSearch" / "Drafting" / "Creating Agent" instead of "Plan".
const TOOL_TITLES: Record<string, string> = {
  search: "WebSearch",
  web_search: "WebSearch",
  google_search: "WebSearch",
  crawler_query: "WebCrawl",
  write_file: "Writing File",
  draft: "Drafting",
  create_agent: "Creating Agent",
  read_file: "Reading File",
  edit_file: "Editing File",
  run_command: "Running Command",
  ask_user_question: "Asking You",
  speak: "Speaking",
}

// Title-case fallback for any tool not in the map above.
function titleCaseTool(tool: string): string {
  return tool
    .split(/[_\s-]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
}

// Mode names that can leak as tool_name (the step ran as REASON under a mode
// like "direct"/"agentic") - treated as placeholders; the label is DERIVED
// from the step description instead (pin_42ddd255162d: a web step must never
// read as bare "Tool", for any task type).
const MODE_PLACEHOLDERS = new Set([
  "tool",
  "direct",
  "auto",
  "background",
  "tool_execution",
  "agentic",
  "quick",
  "none",
])

/**
 * pin_42ddd255162d: human-readable tool label for the plan card.
 * Known tools use the TOOL_TITLES map; a placeholder/unknown tool name
 * ("tool", missing, or a mode name) is DERIVED from the step description so a
 * web step NEVER reads as bare "Tool" - the label stays meaningful for every
 * task type, not just websearch.
 */
export function toolLabel(step: TaskStep): string {
  const t = (step.toolName ?? "").trim()
  if (t && !MODE_PLACEHOLDERS.has(t.toLowerCase())) {
    return TOOL_TITLES[t] ?? titleCaseTool(t)
  }
  const d = (step.description ?? "").toLowerCase()
  if (/(search|web|research|find|look up|documentation|information about|crawl|browse)/.test(d)) {
    return "WebSearch"
  }
  if (/(summar|synthesi[sz]e|analy[sz]e|explain|compare)/.test(d)) return "Reasoning"
  if (/(write|create|draft|build|compose)/.test(d)) return "Drafting"
  if (/(file|read|edit|code)/.test(d)) return "File"
  return "Tool"
}

const EMPTY_PROGRESS: TaskProgress = {
  isWorking: false,
  currentStep: 0,
  totalSteps: 0,
  steps: [],
  currentAction: undefined,
  planTitle: undefined,
  cards: [],
}

// ── T6 internal card-collection model (REQ-3, REQ-4) ─────────────────────────
//
// Replaces the old single-card `TaskProgress` state. Cards are scoped per
// conversation so switching away and back RESTORES what was there instead of
// wiping it (REQ-4 AC2) - the conversation's card map is simply left alone
// while a different one is being viewed.

interface ConversationCardState {
  /** Insertion order - the order cards were first seen, per REQ-4 AC2 ("in order"). */
  order: string[]
  byId: Record<string, TaskCard>
  /**
   * REQ-3 edge case: pointer to the "current" card for LEGACY payloads (no
   * `card_id`). Reproduces today's single-card merge-by-task_id heuristic
   * without a real backend-declared identity to key on.
   */
  legacyCardId?: string
}

interface CardsState {
  /** The conversation currently being viewed. Only conversation switch/new
   * events change this - task lifecycle events never do, so a background
   * task's events land in ITS conversation's bucket even while a different
   * one is on screen (REQ-4 edge case). */
  activeConversationId: string
  /** LRU order of conversation ids touched, oldest first (bounds memory). */
  convTouchOrder: string[]
  byConversation: Record<string, ConversationCardState>
}

const EMPTY_CARDS_STATE: CardsState = {
  activeConversationId: NO_CONVERSATION,
  convTouchOrder: [],
  byConversation: {},
}

function emptyConversation(): ConversationCardState {
  return { order: [], byId: {} }
}

/** Bounded upsert: adds/replaces one card, evicting the OLDEST card whole
 * (never a partial one) once the per-conversation cap is exceeded. */
function upsertCard(
  conv: ConversationCardState,
  cardId: string,
  card: TaskCard,
): ConversationCardState {
  const existed = !!conv.byId[cardId]
  let order = conv.order
  const byId = { ...conv.byId, [cardId]: card }
  if (!existed) {
    order = [...order, cardId]
    if (order.length > MAX_CARDS_PER_CONVERSATION) {
      const evictId = order[0]
      order = order.slice(1)
      delete byId[evictId]
    }
  }
  return { ...conv, order, byId }
}

/** Touches (creates if missing, bumps to most-recently-used) a conversation
 * bucket, evicting the least-recently-touched conversation's WHOLE card map
 * once the tracked-conversation cap is exceeded. */
function touchConversation(
  prev: CardsState,
  convId: string,
): Pick<CardsState, "byConversation" | "convTouchOrder"> {
  let byConversation = prev.byConversation
  let convTouchOrder = [...prev.convTouchOrder.filter((id) => id !== convId), convId]

  if (!byConversation[convId]) {
    byConversation = { ...byConversation, [convId]: emptyConversation() }
  }

  while (convTouchOrder.length > MAX_TRACKED_CONVERSATIONS) {
    const evictId = convTouchOrder[0]
    if (evictId === convId) break // never evict the conversation we're touching
    convTouchOrder = convTouchOrder.slice(1)
    const rest = { ...byConversation }
    delete rest[evictId]
    byConversation = rest
  }

  return { byConversation, convTouchOrder }
}

function freshStart(
  cardId: string,
  conversationId: string | null,
  incoming: TaskStep[],
  d: TaskUpdateDetail,
): TaskCard {
  return {
    cardId,
    conversationId,
    isWorking: true,
    currentStep: 0,
    totalSteps: d.total_steps ?? incoming.length,
    steps: incoming,
    mode: d.mode,
    turnId: d.task_id,
    planTitle: d.plan_title,
  }
}

// Same merge the single-card model always did: RECONCILE instead of wiping.
// The backend emits task:start twice for one task - an early LLM-plan
// skeleton at plan time, then the DER queue at execution start - and later
// again whenever the plan is revised. A full reset there makes the plan card
// flicker. Merging also lets the agent revise the plan at any time: a later
// task:start updates step descriptions / appends newly-discovered steps
// without losing live progress (currentStep, already-done steps).
function mergeStart(existing: TaskCard, incoming: TaskStep[], d: TaskUpdateDetail): TaskCard {
  const existingById = new Map(existing.steps.map((s) => [s.id, s]))
  const merged: TaskStep[] = []
  for (const step of incoming) {
    const ex = existingById.get(step.id)
    merged.push(ex ? { ...ex, description: step.description, toolName: step.toolName } : step)
  }
  // Preserve any steps discovered live (add_step) that aren't in the
  // incoming plan snapshot.
  for (const s of existing.steps) {
    if (!incoming.some((inc) => inc.id === s.id)) merged.push(s)
  }
  return {
    ...existing,
    isWorking: true,
    steps: merged,
    totalSteps: Math.max(merged.length, existing.currentStep),
    mode: d.mode ?? existing.mode,
    turnId: d.task_id,
    planTitle: d.plan_title || existing.planTitle,
  }
}

function handleTaskStart(prev: CardsState, d: TaskUpdateDetail): CardsState {
  const incoming = (d.steps || [])
    .slice(0, MAX_STEPS)
    // REQ-1 AC5: honor the backend-provided status; default to "unknown" for
    // steps without a record. "unknown" renders identically to "pending" but
    // is semantically distinct - it means no tool:call event was ever received.
    .map((s) => ({ ...s, status: (s.status as TaskStepStatus) ?? ("unknown" as TaskStepStatus) }))

  const convId = d.conversation_id || prev.activeConversationId
  const { byConversation, convTouchOrder } = touchConversation(prev, convId)
  let conv = byConversation[convId]

  if (d.card_id) {
    // REQ-3 AC3/AC4: "continues" extends the card bearing card_id; "new"
    // (or a card_id we have never seen) adds a card and leaves prior cards
    // in the stream intact - trivially true here, since a different card_id
    // is simply a different key in the map.
    const existing = conv.byId[d.card_id]
    const card =
      d.card_relation === "continues" && existing && incoming.length > 0
        ? mergeStart(existing, incoming, d)
        : freshStart(d.card_id, convId, incoming, d)
    conv = upsertCard(conv, d.card_id, card)
  } else {
    // REQ-3 edge case: legacy payload with no card_id - fall back to TODAY'S
    // task_id merge heuristic rather than dropping the card.
    const legacyExisting = conv.legacyCardId ? conv.byId[conv.legacyCardId] : undefined
    const sameActiveTask =
      legacyExisting?.turnId === d.task_id && legacyExisting?.isWorking && legacyExisting.steps.length > 0
    if (sameActiveTask && incoming.length > 0) {
      conv = upsertCard(conv, conv.legacyCardId!, mergeStart(legacyExisting!, incoming, d))
    } else {
      // Full replace, matching the pre-T6 single-card model: the old legacy
      // card (if any) is discarded entirely, not merged.
      const newId = `legacy_${d.task_id || "unknown"}`
      if (conv.legacyCardId && conv.legacyCardId !== newId) {
        const { [conv.legacyCardId]: _drop, ...restById } = conv.byId
        conv = { ...conv, byId: restById, order: conv.order.filter((id) => id !== conv.legacyCardId) }
      }
      conv = upsertCard(conv, newId, freshStart(newId, convId, incoming, d))
      conv = { ...conv, legacyCardId: newId }
    }
  }

  return {
    ...prev,
    convTouchOrder,
    byConversation: { ...byConversation, [convId]: conv },
  }
}

/** Resolves which card in `conv` a non-start event targets: the declared
 * `card_id` if we have already seen it, else the legacy pointer. Returns
 * undefined rather than fabricating a phantom card - a card is only ever
 * created by task:start. */
function resolveTargetCardId(conv: ConversationCardState, d: TaskUpdateDetail): string | undefined {
  if (d.card_id) return conv.byId[d.card_id] ? d.card_id : undefined
  return conv.legacyCardId
}

function blankCard(cardId: string, conversationId: string | null): TaskCard {
  return { cardId, conversationId, isWorking: false, currentStep: 0, totalSteps: 0, steps: [] }
}

/** Applies `updater` to the resolved target card and writes it back.
 * `updater` returning the SAME reference it was given is the "no-op"
 * signal - skips the state write entirely so an event that changes nothing
 * (e.g. task:progress with no matching working step) does not force a
 * render (quality check: no unnecessary work in a render hot path).
 *
 * LEGACY TOLERANCE: a legacy (no card_id) event with no task:start yet is
 * NOT dropped - the pre-T6 single-card model always had a `prev` to apply
 * against (defaulting to EMPTY_PROGRESS), so e.g. a standalone task:learning
 * fired before any task:start must still surface. A card_id-bearing event
 * for a card we have never seen IS dropped: only task:start establishes a
 * new card_id, so fabricating one from a bare lifecycle event would be
 * inventing identity the backend never declared. */
function applyToCard(
  prev: CardsState,
  d: TaskUpdateDetail,
  updater: (card: TaskCard) => TaskCard,
): CardsState {
  const convId = d.conversation_id || prev.activeConversationId
  const existingConv = prev.byConversation[convId]
  let targetId = existingConv ? resolveTargetCardId(existingConv, d) : undefined
  if (!targetId && d.card_id) return prev

  const { byConversation, convTouchOrder } = touchConversation(prev, convId)
  let conv = byConversation[convId]
  let fabricated = false
  if (!targetId) {
    targetId = conv.legacyCardId || "legacy_unknown"
    conv = { ...conv, legacyCardId: targetId }
    if (!conv.byId[targetId]) {
      conv = upsertCard(conv, targetId, blankCard(targetId, convId))
      fabricated = true
    }
  }

  const existing = conv.byId[targetId]
  const updated = updater(existing)
  if (!fabricated && updated === existing) return prev
  const nextConv = upsertCard(conv, targetId, updated)
  return { ...prev, convTouchOrder, byConversation: { ...byConversation, [convId]: nextConv } }
}

// ── T7a card rehydration (REQ-4 AC2/AC4/AC5) ──────────────────────────────
//
// Wire shape sent by `_handle_get_cards` (iris_gateway.py), which is just
// `CardState.to_dict()` from conversation_context_store.py — the same
// snapshot T4/T4a already persist, unpacked here into the hook's internal
// TaskCard model.

interface PersistedCardStep {
  id: string
  description: string
  status: string
  tool_name?: string | null
}

interface PersistedCard {
  card_id: string
  conversation_id: string
  card_relation?: "new" | "continues"
  plan_title?: string | null
  mode?: string | null
  steps?: PersistedCardStep[]
  current_step?: number
  total_steps?: number
  terminal_state?: string
}

/** Idempotent merge of a `get_cards` response into the card-collection state,
 * keyed on `card_id` and bucketed by each card's OWN `conversation_id`
 * (REQ-4 AC3 — a card only ever lands in the conversation that produced it,
 * regardless of which conversation is currently being viewed).
 *
 * CT-4 / "never blank a card that already has content" (the document
 * rehydration guard this extends): a `card_id` already present — whether
 * from a live event this session or a prior hydration — is left COMPLETELY
 * ALONE. Re-hydrating the same conversation twice can therefore never
 * duplicate a card, and a persisted snapshot can never overwrite live
 * progress that has since moved on. Only card_ids the hook has never seen
 * are inserted.
 */
function mergeHydratedCards(prev: CardsState, cards: PersistedCard[]): CardsState {
  let byConversation = prev.byConversation
  let convTouchOrder = prev.convTouchOrder
  for (const p of cards) {
    if (!p.card_id || !p.conversation_id) continue
    const convId = p.conversation_id
    const touched = touchConversation({ ...prev, byConversation, convTouchOrder }, convId)
    byConversation = touched.byConversation
    convTouchOrder = touched.convTouchOrder
    const conv = byConversation[convId]
    if (conv.byId[p.card_id]) continue // already rendered — never overwrite, never duplicate

    const steps: TaskStep[] = (p.steps || []).slice(0, MAX_STEPS).map((s) => ({
      id: s.id,
      description: s.description,
      status: (s.status as TaskStepStatus) ?? "unknown",
      toolName: s.tool_name ?? undefined,
    }))
    const hydrated: TaskCard = {
      cardId: p.card_id,
      conversationId: convId,
      // AC5: a persisted card is, by definition, no longer live — the store
      // has already turned any orphaned "running" row into a terminal state
      // before this ever reaches the wire (see terminal_state below).
      isWorking: false,
      currentStep: p.current_step ?? deriveCurrentStep(steps),
      totalSteps: p.total_steps ?? steps.length,
      steps,
      mode: p.mode ?? undefined,
      planTitle: p.plan_title ?? undefined,
      terminalState: p.terminal_state,
    }
    byConversation = { ...byConversation, [convId]: upsertCard(conv, p.card_id, hydrated) }
  }
  return { ...prev, byConversation, convTouchOrder }
}

function reduceTaskUpdate(prev: CardsState, d: TaskUpdateDetail): CardsState {
  switch (d.type) {
    case "task:start":
      return handleTaskStart(prev, d)

    case "tool:call": {
      return applyToCard(prev, d, (card) => {
        let steps = card.steps
        let currentStep = card.currentStep
        if (d.step_number != null) {
          const idx = d.step_number - 1
          if (steps[idx]) {
            const s = steps.slice()
            // Adopt the RESOLVED tool name. The planner emits task:start
            // before tool resolution runs, so the step's initial toolName is
            // the planner's guess; tool:call carries what DER actually
            // resolved (e.g. "crawler_query"). Without this the card shows
            // the pre-resolution value for the whole task.
            s[idx] = { ...s[idx], status: "working", toolName: d.tool_name || s[idx].toolName }
            steps = s
            currentStep = deriveCurrentStep(steps)
          }
        }
        return {
          ...card,
          steps,
          currentStep,
          isWorking: true,
          currentAction: d.description || card.currentAction,
          // Dynamic action title: reflect what the agent is actually doing
          // (WebSearch / Drafting / Creating Agent) instead of a static "Plan".
          planTitle: d.tool_name ? TOOL_TITLES[d.tool_name] || titleCaseTool(d.tool_name) : card.planTitle,
        }
      })
    }

    case "tool:result": {
      if (d.step_number == null) return prev
      return applyToCard(prev, d, (card) => {
        const idx = d.step_number! - 1
        if (!card.steps[idx]) return card
        const steps = card.steps.slice()
        steps[idx] = {
          ...steps[idx],
          status: "done",
          resultPreview: d.result_summary,
          // Live detail belongs to an in-flight step only.
          activeDetail: undefined,
          url: undefined,
          activeProgress: undefined,
        }
        return { ...card, steps, currentStep: deriveCurrentStep(steps), isWorking: true }
      })
    }

    case "tool:error": {
      if (d.step_number == null) return prev
      return applyToCard(prev, d, (card) => {
        const idx = d.step_number! - 1
        if (!card.steps[idx]) return card
        const steps = card.steps.slice()
        steps[idx] = {
          ...steps[idx],
          status: "fail",
          resultPreview: d.error,
          activeDetail: undefined,
          url: undefined,
          activeProgress: undefined,
        }
        // Recompute here too: a failed step ends the "working" state for
        // that index, and without this the counter froze on the failure.
        return { ...card, steps, currentStep: deriveCurrentStep(steps), isWorking: true }
      })
    }

    case "task:progress": {
      return applyToCard(prev, d, (card) => {
        // DER finished a step - check it off in the to-do list.
        if (d.step_done) {
          // pin_517dfcbda150 (F3): look up by the backend's unique step_id
          // first (plan steps carry ids like r1/step_1; split children carry
          // parent_s{i}); fall back to the legacy der-N convention for older
          // emitters.
          const id = d.step_id || `der-${d.step_number ?? card.steps.length}`
          const idx = card.steps.findIndex((s) => s.id === id)
          if (idx < 0) return card
          const steps = card.steps.slice()
          steps[idx] = {
            ...steps[idx],
            status: d.success === false ? "error" : "done",
            activeDetail: undefined,
            url: undefined,
            activeProgress: undefined,
          }
          return { ...card, steps }
        }
        // DER discovered a new step - append it to the to-do list so the user
        // sees the agent's live plan (e.g. the actual search queries) as it is
        // built, not just the upfront planner plan.
        if (d.add_step) {
          const id = d.step_id || `der-${d.step_number ?? card.steps.length + 1}`
          if (card.steps.find((s) => s.id === id)) return card
          const steps = [
            ...card.steps,
            {
              id,
              description: d.description || "Working...",
              status: "working" as TaskStepStatus,
              toolName: d.tool_name,
            },
          ]
          // Keep the orb badge denominator in sync: DER discovers live steps
          // (e.g. per-page web research) after task:start, so totalSteps must
          // grow with the list or the badge reads 3/1 instead of 3/3.
          return { ...card, steps, totalSteps: Math.max(card.totalSteps, steps.length), isWorking: true }
        }
        // Live action update. Generic tool calls set currentAction only; the
        // crawler passes update_step=true with the source being read.
        //
        // This writes `activeDetail`, NOT `description`. Overwriting the
        // description replaced the agent's plan text ("Search for recent
        // Python 3.13 features") with transient progress ("Reading
        // example.com (2/5)") - the plan was destroyed as it executed and the
        // dropdown could never show what the agent set out to do.
        const action = d.description || d.action
        if (!action) return card
        let steps = card.steps
        if (d.update_step) {
          const workingIdx = steps.findIndex((s) => s.status === "working")
          if (workingIdx >= 0) {
            const s = steps.slice()
            s[workingIdx] = {
              ...s[workingIdx],
              // Prefer the structured field; fall back to the sentence for
              // emitters that predate `detail`.
              activeDetail: d.detail || action,
              activeProgress: d.detail_progress,
              // pin_517dfcbda150 (F1): the crawler streams the source URL on
              // every page event; surface it on the card (subtitle/hover).
              url: d.detail_url,
            }
            steps = s
          }
        }
        const next: Partial<TaskCard> = { steps, currentAction: action, isWorking: true }
        // REQ-4 AC2: capture structured phase label from the crawl pipeline.
        if (d.phase) {
          next.phase = d.phase
          next.phaseSequence = d.phase_sequence ?? card.phaseSequence ?? 0
        }
        return { ...card, ...next }
      })
    }

    case "task:done":
    case "task:fail": {
      return applyToCard(prev, d, (card) => {
        // Keep steps + planTitle for display; clear the working flag + live
        // action + phase + learning signal. Also strip any live detail left
        // on a step that never got a terminal event - otherwise a finished
        // card keeps advertising a page it is no longer reading.
        //
        // RESOLVE every step that is still mid-flight. Stripping activeDetail
        // but leaving `status: "working"` is what left the card spinning after
        // the run had ended: TaskListCard renders a working step's Xur
        // indicator indefinitely, and a step whose completion event was lost
        // never got one.
        //
        // Resolved HONESTLY, not by blanket-marking done:
        //   * a step the backend named in `failed_steps` is a failure, and now
        //     says so instead of quietly reading as finished;
        //   * a step still `working` when the loop reports success did finish,
        //     so it completes - but on a FAILED task it becomes an error, not
        //     a success;
        //   * a step still `pending`/`unknown` never ran, so it is `skipped`.
        const failedIds = new Set(
          (d.failed_steps || []).map((f) => f?.step_id).filter((x): x is string => !!x),
        )
        const taskFailed = d.type === "task:fail" || d.outcome === "cancelled"
        const steps = card.steps.map((s) => {
          const cleared = { ...s, activeDetail: undefined, url: undefined, activeProgress: undefined }
          if (failedIds.has(s.id)) return { ...cleared, status: "fail" as const }
          if (s.status === "working") {
            const resolved: TaskStepStatus = taskFailed ? "error" : "done"
            return { ...cleared, status: resolved }
          }
          if (s.status === "pending" || s.status === "unknown") {
            return { ...cleared, status: "skipped" as const }
          }
          return cleared
        })
        return {
          ...card,
          isWorking: false,
          currentStep: deriveCurrentStep(steps),
          currentAction: undefined,
          phase: undefined,
          phaseSequence: undefined,
          learningSignal: undefined,
          steps,
        }
      })
    }

    case "task:learning": {
      // REQ-8: honest learning signal. Surface it for the card border
      // particles; do NOT clear steps or working state.
      return applyToCard(prev, d, (card) => ({
        ...card,
        learningSignal: (d.signal ?? null) as TaskCard["learningSignal"],
        isWorking: true,
      }))
    }

    default:
      return prev
  }
}

/** Which card in a conversation counts as "the" card for the derived
 * single-card fields (backward compatibility for XurOrb and pre-multi-card
 * tests): the most recently touched WORKING card, else the most recently
 * created card. A running step is the step you are on - same rule
 * `deriveCurrentStep` uses one level up. */
function deriveActiveCard(conv: ConversationCardState | undefined): TaskCard | null {
  if (!conv || conv.order.length === 0) return null
  for (let i = conv.order.length - 1; i >= 0; i--) {
    const c = conv.byId[conv.order[i]]
    if (c?.isWorking) return c
  }
  const lastId = conv.order[conv.order.length - 1]
  return conv.byId[lastId] ?? null
}

function toPublicProgress(state: CardsState): TaskProgress {
  const conv = state.byConversation[state.activeConversationId]
  const cards = conv ? conv.order.map((id) => conv.byId[id]) : []
  const active = deriveActiveCard(conv)
  if (!active) return { ...EMPTY_PROGRESS, cards }
  return {
    isWorking: active.isWorking,
    currentStep: active.currentStep,
    totalSteps: active.totalSteps,
    steps: active.steps,
    mode: active.mode,
    turnId: active.turnId,
    planTitle: active.planTitle,
    currentAction: active.currentAction,
    phase: active.phase,
    phaseSequence: active.phaseSequence,
    learningSignal: active.learningSignal,
    cards,
  }
}

/**
 * Centralizes task progress derived from `iris:task_update` CustomEvents
 * (dispatched by useIRISWebSocket for task:start/progress/milestone/done/fail
 * and tool:call/result/error). Consumed by XurOrb (OrbBadge) and chat-view
 * (TaskListCard) so there is a single source of truth.
 *
 * T6 (REQ-3, REQ-4): state is a `Map<card_id, Card>` SCOPED PER CONVERSATION
 * (`CardsState.byConversation`), not one global card. Switching conversations
 * no longer wipes anything - it just changes which conversation's map is
 * being read (`activeConversationId`), so cards RESTORE instead of vanishing.
 * The single-card fields on the returned `TaskProgress` are derived from the
 * active card for backward compatibility; `cards` is the full collection.
 */
export function useTaskProgress(): TaskProgress {
  const [cardsState, setCardsState] = useState<CardsState>(EMPTY_CARDS_STATE)
  const ref = useRef(cardsState)
  ref.current = cardsState

  // A card belongs to the conversation that produced it. `iris:new_conversation`
  // / `iris:conversation_switched` change which conversation is BEING VIEWED;
  // they no longer erase any conversation's cards (REQ-4 AC2 - restore, not
  // reset). Both fire when the user is looking at a different conversation.
  useEffect(() => {
    const goTo = (convId: string) => {
      setCardsState((prev) => ({ ...prev, activeConversationId: convId, ...touchConversation(prev, convId) }))
    }
    const onNew = () => goTo(NO_CONVERSATION)
    const onSwitched = (e: Event) => {
      const detail = (e as CustomEvent<{ conversation_id?: string }>).detail
      goTo(detail?.conversation_id || NO_CONVERSATION)
    }
    window.addEventListener("iris:new_conversation", onNew)
    window.addEventListener("iris:conversation_switched", onSwitched)
    return () => {
      window.removeEventListener("iris:new_conversation", onNew)
      window.removeEventListener("iris:conversation_switched", onSwitched)
    }
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<TaskUpdateDetail>).detail
      if (!d) return
      setCardsState((prev) => reduceTaskUpdate(prev, d))
    }
    window.addEventListener("iris:task_update", handler)
    return () => window.removeEventListener("iris:task_update", handler)
  }, [])

  // T7a (REQ-4 AC2/AC4/AC5): response to `get_cards`, forwarded by
  // useIRISWebSocket as `iris:cards`. This is the read half of the T4/T4a
  // write path — without it a fresh page load never shows a card that was
  // persisted before the reload, which is the bug REQ-4 exists to fix.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ cards?: PersistedCard[] }>).detail
      const cards = detail?.cards
      if (!cards || cards.length === 0) return
      setCardsState((prev) => mergeHydratedCards(prev, cards))
    }
    window.addEventListener("iris:cards", handler)
    return () => window.removeEventListener("iris:cards", handler)
  }, [])

  // REQ-12 AC4 (T19): while the browser panel is closed the orb must still
  // reflect crawl progress. The crawl's phase arrives over the SSE fallback as
  // `iris:task:event` (ux_map CRAWLER_PHASE -> msg_type "task:event") and the
  // in-flight stage message as `iris:crawler_progress` - neither is an
  // `iris:task_update` message, so they would never flip the orb working state.
  // Terminal `iris:crawler_complete` / `iris:crawler_error` clear it (the
  // SSE-only path has no task:done/fail to do so). Neither carries a card_id,
  // so - like any legacy event - it targets whichever card is "active" in the
  // conversation currently being viewed.
  useEffect(() => {
    const targetCardId = (conv: ConversationCardState | undefined): string | undefined =>
      conv?.legacyCardId ?? (conv && conv.order.length > 0 ? conv.order[conv.order.length - 1] : undefined)

    const handler = (e: Event) => {
      const d = (e as CustomEvent<{
        phase?: string
        phase_sequence?: number
        stage?: string
        message?: string
      }>).detail
      if (!d) return
      setCardsState((prev) => {
        const convId = prev.activeConversationId
        const conv = prev.byConversation[convId]
        const targetId = targetCardId(conv)
        if (!conv || !targetId) return prev
        const card = conv.byId[targetId]
        const next: TaskCard = { ...card, isWorking: true }
        if (d.phase) {
          next.phase = d.phase
          next.phaseSequence = d.phase_sequence ?? card.phaseSequence ?? 0
        }
        if (d.message) next.currentAction = d.message
        return { ...prev, byConversation: { ...prev.byConversation, [convId]: upsertCard(conv, targetId, next) } }
      })
    }
    const done = () => {
      setCardsState((prev) => {
        const convId = prev.activeConversationId
        const conv = prev.byConversation[convId]
        const targetId = targetCardId(conv)
        if (!conv || !targetId) return prev
        const card = conv.byId[targetId]
        const next: TaskCard = {
          ...card,
          isWorking: false,
          currentAction: undefined,
          phase: undefined,
          phaseSequence: undefined,
        }
        return { ...prev, byConversation: { ...prev.byConversation, [convId]: upsertCard(conv, targetId, next) } }
      })
    }
    window.addEventListener("iris:task:event", handler)
    window.addEventListener("iris:crawler_progress", handler)
    window.addEventListener("iris:crawler_complete", done)
    window.addEventListener("iris:crawler_error", done)
    return () => {
      window.removeEventListener("iris:task:event", handler)
      window.removeEventListener("iris:crawler_progress", handler)
      window.removeEventListener("iris:crawler_complete", done)
      window.removeEventListener("iris:crawler_error", done)
    }
  }, [])

  return useMemo(() => toPublicProgress(cardsState), [cardsState])
}
