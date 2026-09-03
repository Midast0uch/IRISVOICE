'use client'

import { useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { KanbanSection } from './KanbanSection'
import { AgentKanbanBoard } from './AgentKanbanBoard'

interface KanbanCanvasProps {
  onPopOut?: (cardId: string, tabId: string) => void
}

export function KanbanCanvas({ onPopOut }: KanbanCanvasProps) {
  const { sections, kanbanCompact } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const { setNodeRef, isOver } = useDroppable({ id: 'kanban-canvas' })

  if (sections.length === 0) {
    return (
      <div
        className="flex-1 flex flex-col items-stretch justify-start p-3 overflow-y-auto"
        style={{
          background: 'linear-gradient(180deg, rgba(10,11,22,0.3) 0%, rgba(6,7,14,0.5) 100%)',
        }}
      >
        {/* T9 (REQ-5): live multi-agent task board — primary content even
            before any file sections exist. */}
        <AgentKanbanBoard />
        <div className="flex-1 flex items-center justify-center py-6">
          <span className="text-[10px] text-white/20 italic">No sections — drag tabs here</span>
        </div>
      </div>
    )
  }

  return (
    <div
      ref={setNodeRef}
      className="flex-1 flex overflow-y-auto overflow-x-hidden gap-2 p-3 flex-col"
      style={{
        background: 'linear-gradient(180deg, rgba(10,11,22,0.4) 0%, rgba(6,7,14,0.6) 100%)',
        borderTop: `1px solid ${glowColor}08`,
      }}
    >
      {/* T9 (REQ-5): live multi-agent task board above the file sections */}
      <AgentKanbanBoard />
      <div className="flex gap-2 overflow-x-auto overflow-y-hidden pb-1">
        {sections.map((section) => (
          <KanbanSection key={section.id} section={section} glowColor={glowColor} compact={kanbanCompact} onPopOut={onPopOut} />
        ))}
      </div>
    </div>
  )
}
