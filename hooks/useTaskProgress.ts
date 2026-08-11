"use client"

import { useEffect, useRef, useState } from "react"

export type TaskStepStatus =
  /** Step has no event record at all â€” semantically absent but visually pending. */
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
   * The PLAN text â€” what the agent set out to do. Stable for the life of the
   * step. Live progress never overwrites this; it goes to `activeDetail` so the
   * dropdown keeps showing the plan while the card header shows the activity.
   */
  description: string
  status: TaskStepStatus
  toolName?: string
  /**
   * Live, rotating detail for the step currently executing â€” the source being
   * read (e.g. "example.com"), shown beside `toolName`. Cleared when the step
   * resolves, so a finished step never appears to still be working on a page.
   */
  activeDetail?: string
  /** Progress within the active detail, e.g. "2/5". */
  activeProgress?: string
  /**
   * pin_517dfcbda150 (F1): the URL of the page currently being read â€”
   * the crawler's per-page TASK_PROGRESS carries `detail_url`; previously
   * the frontend dropped it (only `detail`/title was consumed).
   */
  url?: string
  resultPreview?: string
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
}

const MAX_STEPS = 50

interface TaskUpdateDetail {
  type: string
  task_id?: string
  description?: string
  plan_title?: string
  action?: string
  update_step?: boolean
  /** Structured live detail (host/title being read) â€” preferred over parsing `description`. */
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
  /** pin_517dfcbda150: unique backend step id for add_step / step_done â€” plan
   * steps carry planner ids (r1, step_1), split children carry parent_s{i}. */
  step_id?: string
  result_summary?: string
  error?: string
  outcome?: string
  steps_completed?: number
  /** REQ-4: structured phase label from the crawl pipeline. */
  phase?: string
  /** Stable phase sequence number (1..N) for disambiguating re-emission. */
  phase_sequence?: number
  /** REQ-8: honest learning signal from `task:learning`. */
  signal?: "avoided" | "retried" | "crystallized" | null
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
// like "direct"/"agentic") — treated as placeholders; the label is DERIVED
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
 * web step NEVER reads as bare "Tool" — the label stays meaningful for every
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

/**
 * Centralizes task progress derived from `iris:task_update` CustomEvents
 * (dispatched by useIRISWebSocket for task:start/progress/milestone/done/fail
 * and tool:call/result/error). Consumed by XurOrb (OrbBadge) and chat-view
 * (TaskListCard) so there is a single source of truth.
 */
export function useTaskProgress(): TaskProgress {
  const [state, setState] = useState<TaskProgress>({
    isWorking: false,
    currentStep: 0,
    totalSteps: 0,
    steps: [],
    currentAction: undefined,
    planTitle: undefined,
  })
  const ref = useRef(state)
  ref.current = state

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<TaskUpdateDetail>).detail
      if (!d) return
      const prev = ref.current

      switch (d.type) {
        case "task:start": {
          const incoming = (d.steps || [])
            .slice(0, MAX_STEPS)
            // REQ-1 AC5: honor the backend-provided status; default to "unknown" for
            // steps without a record. "unknown" renders identically to "pending" but
            // is semantically distinct â€” it means no tool:call event was ever received.
            .map((s) => ({ ...s, status: (s.status as TaskStepStatus) ?? "unknown" as TaskStepStatus }))
          // If a task is already active with the same id, RECONCILE instead of
          // wiping. The backend emits task:start twice for one task â€” an early
          // LLM-plan skeleton at plan time, then the DER queue at execution
          // start. A full reset there makes the plan card flicker. Merging also
          // lets the agent revise the plan at any time: a later task:start
          // updates step descriptions / appends newly-discovered steps without
          // losing live progress (currentStep, already-done steps).
          const sameActiveTask =
            prev.turnId === d.task_id && prev.isWorking && prev.steps.length > 0
          if (sameActiveTask && incoming.length > 0) {
            const existingById = new Map(prev.steps.map((s) => [s.id, s]))
            const merged: TaskStep[] = []
            for (const step of incoming) {
              const existing = existingById.get(step.id)
              if (existing) {
                // Keep live status; refresh plan text/tool from the new plan.
                merged.push({
                  ...existing,
                  description: step.description,
                  toolName: step.toolName,
                })
              } else {
                merged.push(step)
              }
            }
            // Preserve any steps discovered live (add_step) that aren't in the
            // incoming plan snapshot.
            for (const s of prev.steps) {
              if (!incoming.some((inc) => inc.id === s.id)) merged.push(s)
            }
            setState({
              ...prev,
              isWorking: true,
              steps: merged,
              totalSteps: Math.max(merged.length, prev.currentStep),
              mode: d.mode ?? prev.mode,
              turnId: d.task_id,
              planTitle: d.plan_title || prev.planTitle,
            })
          } else {
            setState({
              isWorking: true,
              currentStep: 0,
              totalSteps: d.total_steps ?? incoming.length,
              steps: incoming,
              mode: d.mode,
              turnId: d.task_id,
              planTitle: d.plan_title,
            })
          }
          break
        }
        case "tool:call": {
          const next = { ...prev }
          // Dynamic action title: reflect what the agent is actually doing
          // (WebSearch / Drafting / Creating Agent) instead of a static "Plan".
          if (d.tool_name) {
            next.planTitle = TOOL_TITLES[d.tool_name] || titleCaseTool(d.tool_name)
          }
          if (d.step_number != null) {
            const idx = d.step_number - 1
            const steps = prev.steps.slice()
            if (steps[idx]) {
              // Adopt the RESOLVED tool name. The planner emits task:start
              // before tool resolution runs, so the step's initial toolName is
              // the planner's guess; tool:call carries what DER actually
              // resolved (e.g. "crawler_query"). Without this the card shows
              // the pre-resolution value for the whole task.
              steps[idx] = {
                ...steps[idx],
                status: "working",
                toolName: d.tool_name || steps[idx].toolName,
              }
              const done = steps.filter((s) => s.status === "done").length
              next.steps = steps
              next.currentStep = done
            }
          }
          next.isWorking = true
          next.currentAction = d.description || prev.currentAction
          setState(next)
          break
        }
        case "tool:result": {
          if (d.step_number == null) break
          const idx = d.step_number - 1
          const steps = prev.steps.slice()
          if (steps[idx]) {
            steps[idx] = {
              ...steps[idx],
              status: "done",
              resultPreview: d.result_summary,
              // Live detail belongs to an in-flight step only.
              activeDetail: undefined,
              url: undefined,
              activeProgress: undefined,
            }
            const done = steps.filter((s) => s.status === "done").length
            setState({ ...prev, steps, currentStep: done, isWorking: true })
          }
          break
        }
        case "tool:error": {
          if (d.step_number == null) break
          const idx = d.step_number - 1
          const steps = prev.steps.slice()
          if (steps[idx]) {
            steps[idx] = {
              ...steps[idx],
              status: "fail",
              resultPreview: d.error,
              activeDetail: undefined,
              url: undefined,
              activeProgress: undefined,
            }
            setState({ ...prev, steps, isWorking: true })
          }
          break
        }
        case "task:progress": {
          // DER finished a step â€” check it off in the to-do list.
          if (d.step_done) {
            // pin_517dfcbda150 (F3): look up by the backend's unique step_id
            // first (plan steps carry ids like r1/step_1; split children carry
            // parent_s{i}); fall back to the legacy der-N convention for older
            // emitters. Previously only der-N matched, so plan steps never
            // visually completed while the task was running.
            const id = d.step_id || `der-${d.step_number ?? prev.steps.length}`
            const steps = prev.steps.slice()
            const idx = steps.findIndex((s) => s.id === id)
            if (idx >= 0) {
              steps[idx] = {
                ...steps[idx],
                status: d.success === false ? "error" : "done",
                activeDetail: undefined,
              url: undefined,
                activeProgress: undefined,
              }
            }
            setState({ ...prev, steps })
            break
          }
          // DER discovered a new step â€” append it to the to-do list so the user
          // sees the agent's live plan (e.g. the actual search queries) as it is
          // built, not just the upfront planner plan.
          if (d.add_step) {
            // pin_517dfcbda150 (F2): key on the backend's unique step_id when
            // present. Split children share the parent's step_number but carry
            // distinct ids (parent_s{i}); the old der-N key made every child of
            // one parent collide and silently drop all but the first.
            const id = d.step_id || `der-${d.step_number ?? prev.steps.length + 1}`
            const steps = prev.steps.slice()
            if (!steps.find((s) => s.id === id)) {
              steps.push({
                id,
                description: d.description || "Workingâ€¦",
                status: "working",
                toolName: d.tool_name,
              })
            }
            // Keep the orb badge denominator in sync: DER discovers live steps
            // (e.g. per-page web research) after task:start, so totalSteps must
            // grow with the list or the badge reads 3/1 instead of 3/3.
            setState({
              ...prev,
              steps,
              totalSteps: Math.max(prev.totalSteps, steps.length),
              isWorking: true,
            })
            break
          }
          // Live action update. Generic tool calls set currentAction only; the
          // crawler passes update_step=true with the source being read.
          //
          // This writes `activeDetail`, NOT `description`. Overwriting the
          // description replaced the agent's plan text ("Search for recent
          // Python 3.13 features") with transient progress ("Reading
          // example.com (2/5)") â€” the plan was destroyed as it executed and the
          // dropdown could never show what the agent set out to do.
          const action = d.description || d.action
          if (!action) break
          const steps = prev.steps.slice()
          if (d.update_step) {
            const workingIdx = steps.findIndex((s) => s.status === "working")
            if (workingIdx >= 0) {
              steps[workingIdx] = {
                ...steps[workingIdx],
                // Prefer the structured field; fall back to the sentence for
                // emitters that predate `detail`.
                activeDetail: d.detail || action,
                activeProgress: d.detail_progress,
                // pin_517dfcbda150 (F1): the crawler streams the source URL on
                // every page event; surface it on the card (subtitle/hover).
                url: d.detail_url,
              }
            }
          }
          // REQ-4 AC2: capture structured phase label from the crawl pipeline.
          const next: Partial<TaskProgress> = { steps, currentAction: action, isWorking: true }
          if (d.phase) {
            next.phase = d.phase
            next.phaseSequence = d.phase_sequence ?? (prev.phaseSequence ?? 0)
          }
          setState({ ...prev, ...next })
          break
        }
        case "task:done":
        case "task:fail": {
          // Keep steps + planTitle for display; clear the working flag + live
          // action + phase + learning signal. Also strip any live detail left
          // on a step that never got a terminal event â€” otherwise a finished
          // card keeps advertising a page it is no longer reading.
          setState({
            ...prev,
            isWorking: false,
            currentAction: undefined,
            phase: undefined,
            phaseSequence: undefined,
            learningSignal: undefined,
            steps: prev.steps.map((s) =>
              s.activeDetail
                ? { ...s, activeDetail: undefined,
              url: undefined, activeProgress: undefined }
                : s
            ),
          })
          break
        }
        case "task:learning": {
          // REQ-8: honest learning signal. Surface it for the card border
          // particles; do NOT clear steps or working state.
          const sig = d.signal as
            | "avoided"
            | "retried"
            | "crystallized"
            | null
            | undefined
          setState({ ...prev, learningSignal: sig ?? null, isWorking: true })
          break
        }
        default:
          break
      }
    }

    window.addEventListener("iris:task_update", handler)
    return () => window.removeEventListener("iris:task_update", handler)
  }, [])

  // REQ-12 AC4 (T19): while the browser panel is closed the orb must still
  // reflect crawl progress. The crawl's phase arrives over the SSE fallback as
  // `iris:task:event` (ux_map CRAWLER_PHASE -> msg_type "task:event") and the
  // in-flight stage message as `iris:crawler_progress` — neither is an
  // `iris:task_update` message, so they would never flip the orb working state.
  // Terminal `iris:crawler_complete` / `iris:crawler_error` clear it (the
  // SSE-only path has no task:done/fail to do so).
  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<{
        phase?: string
        phase_sequence?: number
        stage?: string
        message?: string
      }>).detail
      if (!d) return
      const prev = ref.current
      const next: Partial<TaskProgress> = { isWorking: true }
      if (d.phase) {
        next.phase = d.phase
        next.phaseSequence = d.phase_sequence ?? (prev.phaseSequence ?? 0)
      }
      if (d.message) next.currentAction = d.message
      setState({ ...prev, ...next })
    }
    const done = () => {
      const prev = ref.current
      setState({
        ...prev,
        isWorking: false,
        currentAction: undefined,
        phase: undefined,
        phaseSequence: undefined,
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

  return state
}
