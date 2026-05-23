'use client'

import { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore, KanbanCard as KanbanCardType } from '@/stores/workspaceStore'
import { KanbanCard } from './KanbanCard'
import { ChevronLeft, ChevronRight, GripVertical, X } from 'lucide-react'

export function KanbanSection({ section, glowColor }: { section: ReturnType<typeof useWorkspaceStore.getState>['sections'][number]; glowColor: string }) {
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
      className={`flex flex-col shrink-0 rounded-lg transition-colors ${isResizing ? 'select-none' : ''}`}
      style={{
        width: `${width}px`,
        minWidth: section.isCollapsed ? 40 : 200,
        background: 'linear-gradient(180deg, rgba(10,11,22,0.6) 0%, rgba(6,7,14,0.4) 100%)',
        border: `1px solid ${isOver ? `${glowColor}25` : `${glowColor}12`}`,
        boxShadow: isOver
          ? `0 0 12px ${glowColor}15, inset 0 1px 1px rgba(255,255,255,0.03)`
          : 'inset 0 1px 1px rgba(255,255,255,0.03)',
      }}
    >
      {/* Section Header */}
      <div
        className="shrink-0 flex items-center justify-between px-2.5 py-2 rounded-t-lg"
        style={{ borderBottom: `1px solid ${glowColor}10` }}
      >
        <div className="flex items-center gap-1.5 overflow-hidden min-w-0">
          <GripVertical size={10} className="text-white/20 shrink-0 cursor-grab" />
          {!section.isCollapsed && (
            <span className="text-[10px] font-semibold tracking-wide truncate" style={{ color: `${glowColor}90` }}>
              {section.title}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            onClick={() => toggleSectionCollapse(section.id)}
            className="p-0.5 rounded transition-colors hover:bg-white/5"
            style={{ color: 'rgba(255,255,255,0.3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
          >
            {section.isCollapsed ? <ChevronRight size={10} /> : <ChevronLeft size={10} />}
          </button>
          <button
            onClick={() => removeSection(section.id)}
            className="p-0.5 rounded transition-colors hover:bg-white/5"
            style={{ color: 'rgba(255,255,255,0.2)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.5)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.2)' }}
          >
            <X size={10} />
          </button>
        </div>
      </div>

      {/* Cards */}
      {!section.isCollapsed && (
        <div className="flex-1 flex flex-col gap-2 p-2 overflow-y-auto">
          {section.cards.length === 0 ? (
            <div className="flex-1 flex items-center justify-center">
              <span className="text-[9px] text-white/15 italic">Drop cards here</span>
            </div>
          ) : (
            section.cards.map((card: KanbanCardType) => <KanbanCard key={card.id} card={card} glowColor={glowColor} />)
          )}
        </div>
      )}

      {/* Resize Handle */}
      {!section.isCollapsed && (
        <div
          onMouseDown={handleResizeStart}
          className="absolute right-0 top-2 bottom-2 w-1 cursor-col-resize rounded-full transition-colors hover:bg-white/10"
          style={{ position: 'relative' }}
        />
      )}
    </div>
  )
}
