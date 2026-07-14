"use client"

import { useEffect, useRef, useState } from "react"

export type TaskStepStatus =
  | "pending"
  | "working"
  | "done"
  | "skipped"
  | "vetoed"
  | "error"
  | "fail"

export interface TaskStep {
  id: string
  description: string
  status: TaskStepStatus
  toolName?: string
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
}

const MAX_STEPS = 50

interface TaskUpdateDetail {
  type: string
  task_id?: string
  description?: string
  plan_title?: string
  action?: string
  update_step?: boolean
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
  result_summary?: string
  error?: string
  outcome?: string
  steps_completed?: number
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
  // Mode-name fallbacks for when the backend mode leaks as tool_name.
  agentic: "WebSearch",
  quick: "Respond",
  direct: "Tool",
}

// Title-case fallback for any tool not in the map above.
function titleCaseTool(tool: string): string {
  return tool
    .split(/[_\s-]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
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
            .map((s) => ({ ...s, status: "pending" as TaskStepStatus }))
          // If a task is already active with the same id, RECONCILE instead of
          // wiping. The backend emits task:start twice for one task — an early
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
              steps[idx] = { ...steps[idx], status: "working" }
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
            }
            setState({ ...prev, steps, isWorking: true })
          }
          break
        }
        case "task:progress": {
          // DER finished a step — check it off in the to-do list.
          if (d.step_done) {
            const id = `der-${d.step_number ?? prev.steps.length}`
            const steps = prev.steps.slice()
            const idx = steps.findIndex((s) => s.id === id)
            if (idx >= 0) {
              steps[idx] = {
                ...steps[idx],
                status: d.success === false ? "error" : "done",
              }
            }
            setState({ ...prev, steps })
            break
          }
          // DER discovered a new step — append it to the to-do list so the user
          // sees the agent's live plan (e.g. the actual search queries) as it is
          // built, not just the upfront planner plan.
          if (d.add_step) {
            const id = `der-${d.step_number ?? prev.steps.length + 1}`
            const steps = prev.steps.slice()
            if (!steps.find((s) => s.id === id)) {
              steps.push({
                id,
                description: d.description || "Working…",
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
          // crawler passes update_step=true so the in-progress plan step text is
          // rewritten with the site being read (e.g. "Reading example.com (2/5)").
          const action = d.description || d.action
          if (!action) break
          const steps = prev.steps.slice()
          if (d.update_step) {
            const workingIdx = steps.findIndex((s) => s.status === "working")
            if (workingIdx >= 0) {
              steps[workingIdx] = { ...steps[workingIdx], description: action }
            }
          }
          setState({ ...prev, steps, currentAction: action, isWorking: true })
          break
        }
        case "task:done":
        case "task:fail": {
          // Keep steps + planTitle for display; clear the working flag + live action.
          setState({ ...prev, isWorking: false, currentAction: undefined })
          break
        }
        default:
          break
      }
    }

    window.addEventListener("iris:task_update", handler)
    return () => window.removeEventListener("iris:task_update", handler)
  }, [])

  return state
}
