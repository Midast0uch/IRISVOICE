'use client'

import { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore, KanbanCard as KanbanCardType } from '@/stores/workspaceStore'
import { KanbanCard } from './KanbanCard'
import { ChevronLeft, ChevronRight, GripVertical } from 'lucide-react'

export function KanbanSection({ section }: { section: ReturnType<typeof useWorkspaceStore.getState>['sections'][number] }) {
  const { updateSectionWidth, toggleSectionCollapse, removeSection } = useWorkspaceStore()
  const [isResizing, setIsResizing] = useState(false)
  const { setNodeRef, isOver } = useDroppable({ id: section.id })

  function handleResizeStart(e: React.MouseEvent) {
    e.preventDefault()
    setIsResizing(true)

    const startX = e.clientX
    const startWidth = section.width

    function onMouseMove(moveEvent: MouseEvent) {
      const delta = moveEvent.clientX - startX
      updateSectionWidth(section.id, startWidth + delta)
    }

    function onMouseUp() {
      setIsResizing(false)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  const width = section.isCollapsed ? 40 : Math.max(200, Math.min(section.width, 800))

  return (
    <div
      ref={setNodeRef}
      className={`
        flex flex-col shrink-0 border-r border-white/5 transition-colors
        ${isOver ? 'bg-white/[0.03]' : ''}
        ${isResizing ? 'select-none' : ''}
      `}
      style={{ width: `${width}px`, minWidth: section.isCollapsed ? 40 : 200 }}
    >
      {/* Section Header */}
      <div className="shrink-0 flex items-center justify-between px-2 py-1.5 border-b border-white/5">
        <div className="flex items-center gap-1 overflow-hidden">
          <GripVertical size={10} className="text-white/20 shrink-0" />
          {!section.isCollapsed && (
            <span className="text-[10px] text-white/50 truncate">{section.title}</span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => toggleSectionCollapse(section.id)}
            className="p-0.5 text-white/30 hover:text-white/60 transition-colors"
          >
            {section.isCollapsed ? <ChevronRight size={10} /> : <ChevronLeft size={10} />}
          </button>
        </div>
      </div>

      {/* Cards */}
      {!section.isCollapsed && (
        <div className="flex-1 flex flex-col gap-1 p-1.5 overflow-y-auto">
          {section.cards.length === 0 ? (
            <span className="text-[9px] text-white/15 italic text-center mt-4">Drop cards here</span>
          ) : (
            section.cards.map((card: KanbanCardType) => <KanbanCard key={card.id} card={card} />)
          )}
        </div>
      )}

      {/* Resize Handle */}
      {!section.isCollapsed && (
        <div
          onMouseDown={handleResizeStart}
          className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-white/10"
          style={{ position: 'relative' }}
        />
      )}
    </div>
  )
}
