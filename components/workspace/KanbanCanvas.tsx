'use client'

import { useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { KanbanSection } from './KanbanSection'

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
        className="flex-1 flex items-center justify-center"
        style={{
          background: 'linear-gradient(180deg, rgba(10,11,22,0.3) 0%, rgba(6,7,14,0.5) 100%)',
        }}
      >
        <span className="text-[10px] text-white/20 italic">No sections — drag tabs here</span>
      </div>
    )
  }

  return (
    <div
      ref={setNodeRef}
      className="flex-1 flex overflow-x-auto overflow-y-hidden gap-2 p-3"
      style={{
        background: 'linear-gradient(180deg, rgba(10,11,22,0.4) 0%, rgba(6,7,14,0.6) 100%)',
        borderTop: `1px solid ${glowColor}08`,
      }}
    >
      {sections.map((section) => (
        <KanbanSection key={section.id} section={section} glowColor={glowColor} compact={kanbanCompact} onPopOut={onPopOut} />
      ))}
    </div>
  )
}
