'use client'

import { useDraggable } from '@dnd-kit/core'
import { useWorkspaceStore, type CardState } from '@/stores/workspaceStore'
import { Maximize2, Minimize2, Archive, X, GripVertical } from 'lucide-react'

export function KanbanCard({ card }: { card: ReturnType<typeof useWorkspaceStore.getState>['sections'][number]['cards'][number] }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: card.id,
    data: { type: 'card', card },
  })

  const { updateCardState, archiveCard, removeCard } = useWorkspaceStore()

  const style: React.CSSProperties = {
    transform: transform ? `translate(${transform.x}px, ${transform.y}px)` : undefined,
    opacity: isDragging ? 0.4 : 1,
  }

  const tab = useWorkspaceStore((state) => state.tabs.find((t) => t.id === card.tabId))

  function handleStateToggle() {
    const nextState: CardState = card.state === 'maximized' ? 'minimized' : 'maximized'
    updateCardState(card.id, nextState)
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`
        group flex flex-col gap-1 rounded border border-white/5 bg-white/[0.02]
        hover:border-white/10 transition-all
        ${card.state === 'minimized' ? 'opacity-60' : ''}
      `}
    >
      {/* Card Header */}
      <div className="flex items-center justify-between px-2 py-1">
        <div className="flex items-center gap-1 overflow-hidden" {...listeners} {...attributes}>
          <GripVertical size={10} className="text-white/20 shrink-0 cursor-grab" />
          <span className="text-[10px] text-white/60 truncate">{tab?.label || 'Untitled'}</span>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={handleStateToggle}
            className="p-0.5 text-white/30 hover:text-white/60"
          >
            {card.state === 'maximized' ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
          </button>
          <button
            onClick={() => archiveCard(card.id)}
            className="p-0.5 text-white/30 hover:text-white/60"
          >
            <Archive size={10} />
          </button>
          <button
            onClick={() => removeCard(card.id)}
            className="p-0.5 text-white/30 hover:text-red-400/60"
          >
            <X size={10} />
          </button>
        </div>
      </div>

      {/* Card Body */}
      {card.state === 'maximized' && (
        <div className="px-2 pb-1.5 text-[10px] text-white/30">
          {tab?.type === 'file' && <span className="font-mono">{tab.path}</span>}
          {tab?.type === 'conversation' && <span>Conversation content preview...</span>}
          {tab?.type === 'terminal' && <span>Terminal session</span>}
          {!['file', 'conversation', 'terminal'].includes(tab?.type || '') && <span>{tab?.type} content</span>}
        </div>
      )}
    </div>
  )
}
