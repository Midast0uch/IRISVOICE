'use client'

import { useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { KanbanSection } from './KanbanSection'

export function KanbanCanvas() {
  const { sections } = useWorkspaceStore()
  const { setNodeRef, isOver } = useDroppable({ id: 'kanban-canvas' })

  if (sections.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-[10px] text-white/20 italic">No sections — drag tabs here</span>
      </div>
    )
  }

  return (
    <div
      ref={setNodeRef}
      className={`
        flex-1 flex overflow-x-auto overflow-y-hidden gap-1 p-2
        ${isOver ? 'bg-white/[0.02]' : ''}
      `}
    >
      {sections.map((section) => (
        <KanbanSection key={section.id} section={section} />
      ))}
    </div>
  )
}
