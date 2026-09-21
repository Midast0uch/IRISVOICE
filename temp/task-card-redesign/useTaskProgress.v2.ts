"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { 
  MyceliumTaskState, 
  MyceliumNode, 
  NodeEnergyState,
  NutrientBlock 
} from "./types"
import { parseAction } from "./actionParser"

const MAX_TASK_HISTORY = 10

const createInitialMyceliumTask = (id: string, objective?: string, turnId?: string): MyceliumTaskState => ({
  taskId: id,
  turnId,
  objective: objective || "Executing Mycelium Network",
  nodes: [],
  branches: [],
  isThinking: false,
  currentThought: "",
  thoughtHistory: "",
  phaseState: "STABLE",
  hasCrystallized: false,
  hasRerouted: false,
  energyPulseSpeed: 1.0,
  createdAt: Date.now(),
})

export interface UseTaskProgressV2Return {
  activeTask: MyceliumTaskState | null
  taskHistory: MyceliumTaskState[]
  isWorking: boolean
  clearTasks: () => void
}

export function useTaskProgressV2(): UseTaskProgressV2Return {
  const [tasks, setTasks] = useState<MyceliumTaskState[]>([])
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  
  const tasksRef = useRef(tasks)
  tasksRef.current = tasks
  const activeIdRef = useRef(activeTaskId)
  activeIdRef.current = activeTaskId

  // Reset on thread / conversation switches
  useEffect(() => {
    const handleReset = () => {
      setTasks([])
      setActiveTaskId(null)
    }
    window.addEventListener("iris:new_conversation", handleReset)
    window.addEventListener("iris:conversation_switched", handleReset)
    return () => {
      window.removeEventListener("iris:new_conversation", handleReset)
      window.removeEventListener("iris:conversation_switched", handleReset)
    }
  }, [])

  // ── Living Thought Filament Listener ──────────────────────────────────
  useEffect(() => {
    const handleThinkingChunk = (e: Event) => {
      const detail = (e as CustomEvent<{
        task_id?: string
        chunk: string
        turn_id?: string
        is_complete?: boolean
      }>).detail
      if (!detail?.chunk) return

      setTasks((prev) => {
        const targetId = detail.task_id || activeIdRef.current
        if (!targetId) {
          const newTaskId = `task-${Date.now()}`
          activeIdRef.current = newTaskId
          setActiveTaskId(newTaskId)
          const newTask = createInitialMyceliumTask(newTaskId, "Synthesizing Objective", detail.turn_id)
          newTask.isThinking = true
          newTask.currentThought = detail.chunk
          newTask.thoughtHistory = detail.chunk
          newTask.energyPulseSpeed = 1.8
          return [...prev.slice(-MAX_TASK_HISTORY + 1), newTask]
        }

        return prev.map((task) => {
          if (task.taskId !== targetId) return task
          const isDone = detail.is_complete === true
          const nextHistory = task.thoughtHistory + detail.chunk
          return {
            ...task,
            isThinking: !isDone,
            currentThought: isDone ? "" : detail.chunk,
            thoughtHistory: nextHistory,
            energyPulseSpeed: isDone ? 1.0 : 1.8,
          }
        })
      })
    }

    const handleThinkingDone = (e: Event) => {
      const detail = (e as CustomEvent<{ task_id?: string }>).detail
      const targetId = detail?.task_id || activeIdRef.current
      if (!targetId) return

      setTasks((prev) =>
        prev.map((t) =>
          t.taskId === targetId
            ? {
                ...t,
                isThinking: false,
                currentThought: "",
                energyPulseSpeed: 1.0,
              }
            : t
        )
      )
    }

    window.addEventListener("iris:thinking_chunk", handleThinkingChunk)
    window.addEventListener("iris:thinking_done", handleThinkingDone)
    return () => {
      window.removeEventListener("iris:thinking_chunk", handleThinkingChunk)
      window.removeEventListener("iris:thinking_done", handleThinkingDone)
    }
  }, [])

  // ── Biological Caducean Phase Plane Effects ───────────────────────────
  useEffect(() => {
    const handleCaduceanState = (e: Event) => {
      const detail = (e as CustomEvent<{
        task_id?: string
        phase_plane?: "EXPAND" | "COMPRESS" | "STABLE"
        u?: number
        xi?: number
      }>).detail
      if (!detail?.phase_plane) return

      setTasks((prev) => {
        const targetId = detail.task_id || activeIdRef.current
        if (!targetId) return prev

        return prev.map((t) => {
          if (t.taskId !== targetId) return t
          return {
            ...t,
            phaseState: detail.phase_plane || "STABLE",
            energyPulseSpeed: detail.phase_plane === "EXPAND" ? 1.6 : 1.0,
          }
        })
      })
    }

    window.addEventListener("iris:caducean_state", handleCaduceanState)
    return () => window.removeEventListener("iris:caducean_state", handleCaduceanState)
  }, [])

  // ── DER Loop Events & Hypha Spore Nodes ───────────────────────────────
  useEffect(() => {
    const handleTaskUpdate = (e: Event) => {
      const d = (e as CustomEvent<{
        type: string
        task_id?: string
        plan_title?: string
        description?: string
        steps?: any[]
        step_id?: string
        step_number?: number
        tool_name?: string
        success?: boolean
        error?: string
        detail?: string
        detail_url?: string
        output_block?: NutrientBlock
        branch_id?: string
        branch_label?: string
        signal?: "avoided" | "retried" | "crystallized" | null
      }>).detail
      if (!d) return

      const taskId = d.task_id || activeIdRef.current || `task-${Date.now()}`

      setTasks((prev) => {
        const existingIdx = prev.findIndex((t) => t.taskId === taskId)

        switch (d.type) {
          case "task:start": {
            activeIdRef.current = taskId
            setActiveTaskId(taskId)

            const incomingNodes: MyceliumNode[] = (d.steps || []).map((s, idx) => {
              const parsed = parseAction({ toolName: s.toolName || s.tool_name, description: s.description })
              return {
                id: s.id || `node-${idx + 1}`,
                verb: parsed.verb,
                target: parsed.target || s.description || "target",
                state: "dormant",
                branchId: s.branch_id,
                branchLabel: s.branch_label,
              }
            })

            if (existingIdx >= 0) {
              const existing = prev[existingIdx]
              const merged = [...prev]
              merged[existingIdx] = {
                ...existing,
                objective: d.plan_title || existing.objective,
                nodes: incomingNodes.length > 0 ? incomingNodes : existing.nodes,
              }
              return merged
            } else {
              const newTask: MyceliumTaskState = {
                taskId,
                objective: d.plan_title || "Executing Mycelium Network",
                nodes: incomingNodes,
                branches: [],
                isThinking: false,
                currentThought: "",
                thoughtHistory: "",
                phaseState: "STABLE",
                hasCrystallized: false,
                hasRerouted: false,
                energyPulseSpeed: 1.0,
                createdAt: Date.now(),
              }
              return [...prev.slice(-MAX_TASK_HISTORY + 1), newTask]
            }
          }

          case "tool:call": {
            if (existingIdx < 0) return prev
            const targetTask = prev[existingIdx]
            const nodes = [...targetTask.nodes]
            const sIdx = d.step_number != null ? d.step_number - 1 : nodes.findIndex((n) => n.state === "pulsing")

            const parsed = parseAction({
              toolName: d.tool_name,
              description: d.description,
              detail: d.detail,
              url: d.detail_url,
            })

            if (sIdx >= 0 && nodes[sIdx]) {
              nodes[sIdx] = {
                ...nodes[sIdx],
                verb: parsed.verb,
                target: parsed.target || nodes[sIdx].target,
                state: "pulsing",
                liveDetail: d.detail || d.description,
                branchId: d.branch_id || nodes[sIdx].branchId,
                branchLabel: d.branch_label || nodes[sIdx].branchLabel,
              }
            } else {
              nodes.push({
                id: d.step_id || `node-${nodes.length + 1}`,
                verb: parsed.verb,
                target: parsed.target || d.description || "target",
                state: "pulsing",
                liveDetail: d.detail || d.description,
                branchId: d.branch_id,
                branchLabel: d.branch_label,
              })
            }

            const updatedTasks = [...prev]
            updatedTasks[existingIdx] = {
              ...targetTask,
              nodes,
              energyPulseSpeed: 2.0,
            }
            return updatedTasks
          }

          case "tool:result":
          case "tool:error": {
            if (existingIdx < 0) return prev
            const targetTask = prev[existingIdx]
            const nodes = [...targetTask.nodes]
            const sIdx = d.step_number != null ? d.step_number - 1 : nodes.findIndex((n) => n.state === "pulsing")

            if (sIdx >= 0 && nodes[sIdx]) {
              const isSuccess = d.type === "tool:result"
              nodes[sIdx] = {
                ...nodes[sIdx],
                state: isSuccess ? "fused" : "wilted",
                nutrientOut: d.output_block,
                errorReason: d.error,
                liveDetail: undefined,
              }
            }

            const updatedTasks = [...prev]
            updatedTasks[existingIdx] = {
              ...targetTask,
              nodes,
              energyPulseSpeed: 1.0,
            }
            return updatedTasks
          }

          case "task:learning": {
            if (existingIdx < 0) return prev
            const targetTask = prev[existingIdx]
            const updatedTasks = [...prev]
            updatedTasks[existingIdx] = {
              ...targetTask,
              hasCrystallized: d.signal === "crystallized",
              hasRerouted: d.signal === "avoided",
              energyPulseSpeed: d.signal === "crystallized" ? 2.5 : 1.2,
            }
            return updatedTasks
          }

          case "task:done":
          case "task:fail": {
            if (existingIdx < 0) return prev
            const targetTask = prev[existingIdx]
            const isSuccess = d.type === "task:done"

            const resolvedNodes = targetTask.nodes.map((n) => {
              if (n.state === "pulsing") {
                return { ...n, state: (isSuccess ? "fused" : "wilted") as NodeEnergyState }
              }
              if (n.state === "dormant") {
                return { ...n, state: "dormant" as NodeEnergyState }
              }
              return n
            })

            const updatedTasks = [...prev]
            updatedTasks[existingIdx] = {
              ...targetTask,
              completedAt: Date.now(),
              nodes: resolvedNodes,
              isThinking: false,
              energyPulseSpeed: 0.8,
            }
            return updatedTasks
          }

          default:
            return prev
        }
      })
    }

    window.addEventListener("iris:task_update", handleTaskUpdate)
    return () => window.removeEventListener("iris:task_update", handleTaskUpdate)
  }, [])

  const clearTasks = useCallback(() => {
    setTasks([])
    setActiveTaskId(null)
  }, [])

  const activeTask = tasks.find((t) => t.taskId === activeTaskId) || tasks[tasks.length - 1] || null
  const isWorking = tasks.some((t) => t.isThinking || t.nodes.some((n) => n.state === "pulsing"))

  return {
    activeTask,
    taskHistory: tasks,
    isWorking,
    clearTasks,
  }
}
