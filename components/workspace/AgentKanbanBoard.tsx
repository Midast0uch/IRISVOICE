'use client'

/**
 * AgentKanbanBoard — cli-workspace-unification T8/T9 (REQ-5, REQ-6).
 *
 * Multi-agent Kanban board inside the Visual Workspace Hub. Cards are live
 * agent tasks wired to backend task lifecycle events via useAgentTaskEvents,
 * tagged by the BACKEND-emitted (projectId, conversationId, agentId).
 *
 * Focus Mode (T8, REQ-6) controls filtering/density:
 *   full    — all four columns, all project folders
 *   active  — currently executing agent tasks only
 *   project — grouped by project folder
 *   compact — high-density minimized card strips
 *
 * Column mapping: task:start/progress -> IN PROGRESS; task:done ->
 * CRYSTALLIZED; task:fail -> REVIEW (needs attention — never dropped, never
 * dishonestly shown as crystallized). BACKLOG renders empty until a queued
 * (not yet started) event source exists.
 */

import { useMemo } from 'react'
import { useWorkspaceStore, type AgentKanbanTask } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { openAgentThread } from '@/hooks/useAgentTaskEvents'
import { CircleDashed, CircleDot, Eye, Sparkles } from 'lucide-react'

const COLUMNS: Array<{ id: string; label: string; icon: typeof CircleDashed }> = [
  { id: 'backlog', label: 'BACKLOG', icon: CircleDashed },
  { id: 'in_progress', label: 'IN PROGRESS', icon: CircleDot },
  { id: 'review', label: 'REVIEW', icon: Eye },
  { id: 'crystallized', label: 'CRYSTALLIZED', icon: Sparkles },
]

function statusOf(task: AgentKanbanTask): string {
  if (task.failed) return 'review'
  return task.status === 'crystallized' ? 'crystallized' : 'in_progress'
}

function TaskCard({ task, compact, glowColor }: { task: AgentKanbanTask; compact: boolean; glowColor: string }) {
  const clickable = !!task.conversationId
  return (
    <button
      onClick={() => openAgentThread(task.conversationId)}
      disabled={!clickable}
      title={
        clickable
          ? `Open thread ${task.conversationId}${task.agentId ? ` (agent ${task.agentId})` : ''}`
          : task.title
      }
      className={`w-full text-left rounded-md transition-all ${compact ? 'px-1.5 py-0.5' : 'px-2 py-1.5'}`}
      style={{
        background: task.failed ? 'rgba(239,68,68,0.06)' : 'rgba(255,255,255,0.03)',
        border: `1px solid ${task.failed ? 'rgba(239,68,68,0.25)' : `${glowColor}18`}`,
        cursor: clickable ? 'pointer' : 'default',
      }}
      onMouseEnter={(e) => { if (clickable) e.currentTarget.style.borderColor = `${glowColor}45` }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = task.failed ? 'rgba(239,68,68,0.25)' : `${glowColor}18` }}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <span
          className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{
            background: task.failed ? '#ef4444' : task.status === 'crystallized' ? '#34d399' : glowColor,
            boxShadow: task.status === 'in_progress' && !task.failed ? `0 0 6px ${glowColor}` : 'none',
          }}
        />
        {!compact && (
          <span className="text-[10px] font-medium text-white/85 truncate flex-1">{task.title}</span>
        )}
        {compact && (
          <span className="text-[9px] font-medium text-white/70 truncate flex-1">{task.title}</span>
        )}
        <span className="text-[8px] tabular-nums text-white/35 flex-shrink-0">
          {task.currentStep}/{task.totalSteps || '—'}
        </span>
      </div>
      {!compact && (task.projectId || task.agentId) && (
        <div className="mt-0.5 flex items-center gap-1 pl-3">
          {task.projectId && (
            <span className="text-[8px] px-1 rounded" style={{ background: `${glowColor}12`, color: `${glowColor}90` }}>
              {task.projectId}
            </span>
          )}
          {task.agentId && (
            <span className="text-[8px] px-1 rounded bg-white/5 text-white/40">{task.agentId}</span>
          )}
        </div>
      )}
    </button>
  )
}

export function AgentKanbanBoard() {
  const { agentTasks, focusPreset } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const compact = focusPreset === 'compact'

  const visible = useMemo(() => {
    if (focusPreset === 'active') return agentTasks.filter((t) => t.status === 'in_progress')
    return agentTasks
  }, [agentTasks, focusPreset])

  // PROJECT preset: group cards by project folder into labelled bands.
  const projectGroups = useMemo(() => {
    if (focusPreset !== 'project') return null
    const groups = new Map<string, AgentKanbanTask[]>()
    for (const t of visible) {
      const k = t.projectId || '(no project)'
      if (!groups.has(k)) groups.set(k, [])
      groups.get(k)!.push(t)
    }
    return Array.from(groups.entries())
  }, [visible, focusPreset])

  if (visible.length === 0) {
    return (
      <div className="flex items-center justify-center py-6">
        <span className="text-[10px] text-white/20 italic">
          No agent tasks yet — run a task in developer mode and it appears here live
        </span>
      </div>
    )
  }

  const renderBoard = (tasks: AgentKanbanTask[], label?: string) => (
    <div className="min-w-0">
      {label && (
        <div className="text-[9px] font-bold tracking-wider uppercase mb-1" style={{ color: `${glowColor}80` }}>
          {label}
        </div>
      )}
      <div className={`grid gap-2 ${compact ? 'grid-cols-4' : 'grid-cols-2 lg:grid-cols-4'}`}>
        {COLUMNS.map((col) => {
          const colTasks = tasks.filter((t) => statusOf(t) === col.id)
          return (
            <div
              key={col.id}
              className="rounded-lg p-1.5 min-h-[64px]"
              style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}
            >
              <div className="flex items-center gap-1 mb-1 px-0.5">
                <col.icon size={9} style={{ color: `${glowColor}70` }} />
                <span className="text-[8px] font-bold tracking-wider text-white/40">{col.label}</span>
                <span className="text-[8px] tabular-nums text-white/25 ml-auto">{colTasks.length}</span>
              </div>
              <div className="flex flex-col gap-1">
                {colTasks.map((t) => (
                  <TaskCard key={t.key} task={t} compact={compact} glowColor={glowColor} />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )

  return (
    <div
      className="rounded-xl p-2"
      style={{
        background: 'linear-gradient(180deg, rgba(10,11,22,0.4) 0%, rgba(6,7,14,0.6) 100%)',
        border: `1px solid ${glowColor}10`,
      }}
    >
      {projectGroups
        ? projectGroups.map(([label, tasks]) => (
            <div key={label} className="mb-2 last:mb-0">
              {renderBoard(tasks, label)}
            </div>
          ))
        : renderBoard(visible)}
    </div>
  )
}
