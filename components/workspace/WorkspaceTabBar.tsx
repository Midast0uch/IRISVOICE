'use client'

import React from 'react'
import { useDraggable, useDroppable } from '@dnd-kit/core'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { FileText, Folder, MessageSquare, ScrollText, Terminal, Plus } from 'lucide-react'

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

function TabItem({ tab, isActive, glowColor }: { tab: ReturnType<typeof useWorkspaceStore.getState>['tabs'][number]; isActive: boolean; glowColor: string }) {
  const { attributes, listeners, setNodeRef: dragRef, transform, isDragging } = useDraggable({
    id: tab.id,
    data: { type: 'tab', tab },
  })

  const { setNodeRef: dropRef } = useDroppable({
    id: tab.id,
    data: { type: 'tab', tab },
  })

  const Icon = TAB_TYPE_ICONS[tab.type] || FileText
  const color = TAB_TYPE_COLORS[tab.type] || glowColor

  const style: React.CSSProperties = {
    transform: transform ? `translate(${transform.x}px, ${transform.y}px)` : undefined,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div ref={dropRef} style={style}>
      <button
        ref={dragRef}
        {...listeners}
        {...attributes}
        className="relative flex items-center gap-1.5 px-3 py-2 text-[11px] whitespace-nowrap transition-all duration-150 rounded-t"
        style={{
          color: isActive ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.35)',
          background: isActive ? 'rgba(255,255,255,0.05)' : 'transparent',
        }}
        onMouseEnter={(e) => {
          if (!isActive) {
            e.currentTarget.style.color = 'rgba(255,255,255,0.7)'
            e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
          }
        }}
        onMouseLeave={(e) => {
          if (!isActive) {
            e.currentTarget.style.color = 'rgba(255,255,255,0.35)'
            e.currentTarget.style.background = 'transparent'
          }
        }}
      >
        {/* Active indicator bar */}
        {isActive && (
          <span
            className="absolute bottom-0 left-1.5 right-1.5 h-[2px] rounded-full"
            style={{ background: color }}
          />
        )}
        <span style={{ color }}><Icon size={12} /></span>
        <span className="font-medium">{tab.label}</span>
      </button>
    </div>
  )
}

export function WorkspaceTabBar() {
  const { tabs, activeTabId, setActiveTab, addTab } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'

  function handleAddTab() {
    const id = `tab-${Date.now()}`
    const n = tabs.length + 1
    addTab({ id, label: `File ${n}`, type: 'file', path: `/untitled-${n}.txt`, icon: 'file', isVirtual: true })
  }

  return (
    <div
      className="shrink-0 flex items-center overflow-x-auto"
      style={{
        background: 'linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%)',
        borderBottom: `1px solid ${glowColor}15`,
      }}
    >
      {tabs.length === 0 && (
        <span className="px-3 py-2 text-[10px] text-white/20 italic">No tabs open</span>
      )}
      {tabs.map((tab) => (
        <div key={tab.id} onClick={() => setActiveTab(tab.id)}>
          <TabItem tab={tab} isActive={tab.id === activeTabId} glowColor={glowColor} />
        </div>
      ))}
      <button
        onClick={handleAddTab}
        title="Add tab"
        className="flex-shrink-0 ml-1 p-1.5 rounded-md text-[10px] font-medium transition-all duration-150 flex items-center gap-1"
        style={{
          color: `${glowColor}90`,
          background: `${glowColor}10`,
          border: `1px solid ${glowColor}20`,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = `${glowColor}20`
          e.currentTarget.style.color = glowColor
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = `${glowColor}10`
          e.currentTarget.style.color = `${glowColor}90`
        }}
      >
        <Plus size={12} />
        <span>New</span>
      </button>
    </div>
  )
}
