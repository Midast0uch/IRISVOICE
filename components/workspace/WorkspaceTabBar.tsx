'use client'

import React from 'react'
import { useDraggable, useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { FileText, Folder, MessageSquare, ScrollText, Terminal } from 'lucide-react'

const TAB_TYPE_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  file: FileText,
  folder: Folder,
  conversation: MessageSquare,
  document: ScrollText,
  terminal: Terminal,
}

const TAB_TYPE_COLORS: Record<string, string> = {
  file: '#60a5fa',
  folder: '#a78bfa',
  conversation: '#34d399',
  document: '#fbbf24',
  terminal: '#f87171',
}

function TabItem({ tab, isActive }: { tab: ReturnType<typeof useWorkspaceStore.getState>['tabs'][number]; isActive: boolean }) {
  const { attributes, listeners, setNodeRef: dragRef, transform, isDragging } = useDraggable({
    id: tab.id,
    data: { type: 'tab', tab },
  })

  const { setNodeRef: dropRef, isOver } = useDroppable({
    id: tab.id,
    data: { type: 'tab', tab },
  })

  const Icon = TAB_TYPE_ICONS[tab.type] || FileText
  const color = TAB_TYPE_COLORS[tab.type] || '#60a5fa'

  const style: React.CSSProperties = {
    transform: transform ? `translate(${transform.x}px, ${transform.y}px)` : undefined,
    opacity: isDragging ? 0.4 : 1,
    borderBottom: isActive ? `2px solid ${color}` : '2px solid transparent',
  }

  return (
    <div ref={dropRef} style={style}>
      <button
        ref={dragRef}
        {...listeners}
        {...attributes}
        className={`
          flex items-center gap-1.5 px-3 py-1.5 text-[11px] whitespace-nowrap
          transition-colors hover:bg-white/5
          ${isActive ? 'text-white' : 'text-white/40'}
        `}
      >
        <span style={{ color }}><Icon size={12} /></span>
        <span>{tab.label}</span>
      </button>
    </div>
  )
}

export function WorkspaceTabBar() {
  const { tabs, activeTabId, setActiveTab } = useWorkspaceStore()

  if (tabs.length === 0) {
    return (
      <div className="shrink-0 flex items-center px-4 py-2 border-b border-white/5">
        <span className="text-[10px] text-white/20 italic">No tabs open</span>
      </div>
    )
  }

  return (
    <div className="shrink-0 flex items-center border-b border-white/5 overflow-x-auto">
      {tabs.map((tab) => (
        <div key={tab.id} onClick={() => setActiveTab(tab.id)}>
          <TabItem tab={tab} isActive={tab.id === activeTabId} />
        </div>
      ))}
    </div>
  )
}
