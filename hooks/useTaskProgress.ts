"use client"

import { useEffect, useRef, useState } from "react"

export type TaskStepStatus =
  | "pending"
  | "working"
  | "done"
  | "skipped"
  | "vetoed"
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
}

const MAX_STEPS = 50

interface TaskUpdateDetail {
  type: string
  task_id?: string
  description?: string
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
          const steps = (d.steps || []).slice(0, MAX_STEPS).map((s) => ({
            ...s,
            status: "pending" as TaskStepStatus,
          }))
          setState({
            isWorking: true,
            currentStep: 0,
            totalSteps: d.total_steps ?? steps.length,
            steps,
            mode: d.mode,
            turnId: d.task_id,
          })
          break
        }
        case "tool:call": {
          if (d.step_number == null) break
          const idx = d.step_number - 1
          const steps = prev.steps.slice()
          if (steps[idx]) {
            steps[idx] = { ...steps[idx], status: "working" }
            const done = steps.filter((s) => s.status === "done").length
            setState({ ...prev, steps, currentStep: done, isWorking: true })
          }
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
        case "task:done":
        case "task:fail": {
          // Keep steps for display; clear the working flag.
          setState({ ...prev, isWorking: false })
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
