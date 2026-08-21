"use client"

/**
 * useAgentTaskEvents — cli-workspace-unification T9 (REQ-5 AC1).
 *
 * Wires the multi-agent Kanban board to the backend task lifecycle by
 * consuming the SAME window events the chat cards consume
 * (`iris:task_update`, dispatched by useIRISWebSocket for task:start /
 * task:progress / tool:call / tool:result / tool:error / task:done /
 * task:fail) and upserting `AgentKanbanTask` rows into workspaceStore.
 *
 * TAG PROVENANCE (REQ-5 AC1): (projectId, conversationId, agentId) come from
 * the backend payload — emitted at agent_kernel._task_start_payload. The
 * frontend NEVER fabricates them. When the tags are absent (older emitter),
 * cards fall back to conversationId-only keying and we log ONCE per session
 * (design.md Error Handling: never drop the Kanban card).
 *
 * Mount once per dashboard surface (DeveloperWorkspace). Listener is
 * window-scoped and cleaned up on unmount; no polling, no extra WS channel.
 */

import { useEffect } from "react"
import { useWorkspaceStore, type AgentKanbanTask, type AgentTaskStatus } from "@/stores/workspaceStore"
import { logStructured } from "@/lib/logger"

interface TaskUpdateDetail {
  type?: string
  task_id?: string
  card_id?: string
  description?: string
  plan_title?: string
  currentStep?: number
  total_steps?: number
  step_number?: number
  success?: boolean
  outcome?: string
  failed_steps?: Array<{ step_id?: string; description?: string }>
  // Backend-emitted multi-agent tags (T9a)
  agent_id?: string | null
  project_id?: string | null
  conversation_id?: string | null
}

let warnedMissingTags = false

function resolveKey(detail: TaskUpdateDetail): string {
  if (detail.card_id) return detail.card_id
  return detail.task_id || "unknown"
}

function deriveStatus(type: string, detail: TaskUpdateDetail): { status: AgentTaskStatus; failed: boolean } {
  switch (type) {
    case "task:done":
      return { status: "crystallized", failed: false }
    case "task:fail":
      // Failed tasks land in REVIEW for inspection — never silently dropped,
      // never dishonestly shown as crystallized.
      return { status: "review", failed: true }
    default:
      return { status: "in_progress", failed: detail.success === false }
  }
}

export function upsertFromTaskUpdate(detail: TaskUpdateDetail): void {
  if (!detail || typeof detail.type !== "string") return
  const store = useWorkspaceStore.getState()

  if (detail.agent_id == null && detail.project_id == null && !warnedMissingTags) {
    warnedMissingTags = true
    console.warn(
      "[useAgentTaskEvents] task event without agent_id/project_id — falling back to conversationId-only keying"
    )
  }

  const existing = store.agentTasks.find((t) => t.key === resolveKey(detail))
  const { status, failed } = deriveStatus(detail.type, detail)

  const next: AgentKanbanTask = {
    key: resolveKey(detail),
    taskId: detail.task_id || existing?.taskId || "unknown",
    title:
      detail.plan_title ||
      detail.description ||
      existing?.title ||
      "Agent task",
    status,
    failed,
    currentStep:
      typeof detail.step_number === "number"
        ? detail.step_number
        : existing?.currentStep ?? 0,
    totalSteps:
      typeof detail.total_steps === "number"
        ? detail.total_steps
        : existing?.totalSteps ?? 0,
    projectId: detail.project_id ?? existing?.projectId ?? null,
    conversationId: detail.conversation_id ?? existing?.conversationId ?? null,
    agentId: detail.agent_id ?? existing?.agentId ?? null,
    updatedAt: Date.now(),
  }

  store.upsertAgentTask(next)

  // T11 (REQ-8 AC1): multi-agent card event log — ISO ts + conversation id.
  logStructured("kanban_card_event", {
    conversation_id: next.conversationId,
    key: next.key,
    task_id: next.taskId,
    type: detail.type,
    status: next.status,
    failed: next.failed,
    agent_id: next.agentId,
    project_id: next.projectId,
  })
}

/** REQ-5 AC3: deep-link from a Kanban card to its conversation thread in
 *  ChatView. ChatView listens for `iris:open_conversation`. */
export function openAgentThread(conversationId: string | null): void {
  if (!conversationId || typeof window === "undefined") return
  window.dispatchEvent(
    new CustomEvent("iris:open_conversation", { detail: { conversation_id: conversationId } })
  )
}

export function useAgentTaskEvents(): void {
  useEffect(() => {
    if (typeof window === "undefined") return
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<TaskUpdateDetail>).detail
      try {
        upsertFromTaskUpdate(detail)
      } catch (err) {
        console.warn("[useAgentTaskEvents] handler failed:", err)
      }
    }
    window.addEventListener("iris:task_update", handler as EventListener)
    return () => window.removeEventListener("iris:task_update", handler as EventListener)
  }, [])
}
