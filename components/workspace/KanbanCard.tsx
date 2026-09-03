'use client'

import { useDraggable } from '@dnd-kit/core'
import { useWorkspaceStore, type CardState } from '@/stores/workspaceStore'
import { CardContentRenderer } from './CardContentRenderer'
import { Maximize2, Minimize2, Archive, X, GripVertical, ExternalLink } from 'lucide-react'

const TAB_TYPE_COLORS: Record<string, string> = {
  file: '#60a5fa',
  folder: '#a78bfa',
  conversation: '#34d399',
  document: '#fbbf24',
  terminal: '#f87171',
}

interface KanbanCardProps {
  card: ReturnType<typeof useWorkspaceStore.getState>['sections'][number]['cards'][number]
  glowColor: string
  onPopOut?: (cardId: string, tabId: string) => void
}

export function KanbanCard({ card, glowColor, onPopOut }: KanbanCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: card.id,
    data: { type: 'card', card },
  })

  const { updateCardState, archiveCard, closeCard } = useWorkspaceStore()

  const style: React.CSSProperties = {
    transform: transform ? `translate(${transform.x}px, ${transform.y}px)` : undefined,
    opacity: isDragging ? 0.4 : 1,
  }

  const tab = useWorkspaceStore((state) => state.tabs.find((t) => t.id === card.tabId))
  const accentColor = TAB_TYPE_COLORS[tab?.type || 'file'] || glowColor

  function handleStateToggle() {
    const nextState: CardState = card.state === 'maximized' ? 'minimized' : 'maximized'
    updateCardState(card.id, nextState)
  }

  return (
    <div
      ref={setNodeRef}
      className={`group flex flex-col gap-1 rounded-md transition-all duration-150 ${card.state === 'minimized' ? 'opacity-50' : ''}`}
      style={{
        ...style,
        background: 'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
        border: `1px solid rgba(255,255,255,0.06)`,
        borderLeft: `3px solid ${accentColor}`,
        boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.03)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = `${glowColor}20`
        e.currentTarget.style.background = 'linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)'
        e.currentTarget.style.background = 'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)'
      }}
    >
      {/* Card Header */}
      <div className="flex items-center justify-between px-2 py-1.5">
        <div className="flex items-center gap-1.5 overflow-hidden min-w-0" {...listeners} {...attributes}>
          <GripVertical size={10} className="text-white/20 shrink-0 cursor-grab" />
          <span className="text-[10px] font-medium truncate" style={{ color: 'rgba(255,255,255,0.75)' }}>
            {tab?.label || 'Untitled'}
          </span>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <button
            onClick={handleStateToggle}
            className="p-0.5 rounded transition-colors hover:bg-white/5"
            style={{ color: 'rgba(255,255,255,0.3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
          >
            {card.state === 'maximized' ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
          </button>
          <button
            onClick={() => archiveCard(card.id)}
            className="p-0.5 rounded transition-colors hover:bg-white/5"
            style={{ color: 'rgba(255,255,255,0.3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
          >
            <Archive size={10} />
          </button>
          {onPopOut && (
            <button
              onClick={() => onPopOut(card.id, card.tabId)}
              className="p-0.5 rounded transition-colors hover:bg-white/5"
              style={{ color: 'rgba(255,255,255,0.3)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
              title="Pop out"
            >
              <ExternalLink size={10} />
            </button>
          )}
          <button
            onClick={() => closeCard(card.id)}
            className="p-0.5 rounded transition-colors hover:bg-white/5"
            style={{ color: 'rgba(255,255,255,0.3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(239,68,68,0.7)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
            title="Close card (returns to tab bar)"
          >
            <X size={10} />
          </button>
        </div>
      </div>

      {/* Card Body */}
      {card.state === 'maximized' && tab && (
        <div className="px-2 pb-2 min-h-0 flex-1 overflow-hidden">
          <CardContentRenderer
            cardId={card.id}
            tabId={card.tabId}
            viewMode={card.viewMode}
          />
        </div>
      )}
    </div>
  )
}
