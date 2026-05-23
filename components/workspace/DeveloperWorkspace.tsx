'use client'

import React, { lazy, Suspense } from 'react'
import { DndContext, DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { useWorkspaceStore, WorkspaceTab } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { WorkspaceTabBar } from './WorkspaceTabBar'
import { KanbanCanvas } from './KanbanCanvas'
import { ArchiveDock } from './ArchiveDock'
import { Focus, Terminal } from 'lucide-react'

const TerminalWidget = lazy(() => import('../terminal/TerminalWidget'))

function TerminalSection() {
  const { isTerminalExpanded, toggleTerminal } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'

  return (
    <div className="shrink-0 px-3 pt-2 pb-2">
      {/* Glass panel wrapper */}
      <div
        className="rounded-lg overflow-hidden"
        style={{
          background: 'linear-gradient(180deg, rgba(10,11,22,0.7) 0%, rgba(6,7,14,0.5) 100%)',
          border: `1px solid ${glowColor}18`,
          boxShadow: `
            inset 0 1px 1px rgba(255,255,255,0.04),
            0 2px 8px rgba(0,0,0,0.3)
          `,
        }}
      >
        {/* Terminal header */}
        <button
          onClick={toggleTerminal}
          className="w-full flex items-center justify-between px-3 py-2 transition-colors"
          style={{
            borderBottom: isTerminalExpanded ? `1px solid ${glowColor}12` : '1px solid transparent',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'transparent'
          }}
        >
          <div className="flex items-center gap-2">
            <Terminal size={12} style={{ color: `${glowColor}80` }} />
            <span className="text-[11px] font-medium tracking-wide" style={{ color: `${glowColor}90` }}>
              Terminal
            </span>
            <span
              className="text-[9px] px-1.5 py-0.5 rounded-full"
              style={{
                background: `${glowColor}15`,
                color: `${glowColor}70`,
                border: `1px solid ${glowColor}20`,
              }}
            >
              active
            </span>
          </div>
          <span style={{ color: 'rgba(255,255,255,0.35)' }}>
            {isTerminalExpanded ? '▾' : '▸'}
          </span>
        </button>

        {isTerminalExpanded && (
          <div className="h-48 relative">
            {/* Subtle top highlight line */}
            <div
              className="absolute top-0 left-0 right-0 h-px"
              style={{ background: `linear-gradient(90deg, transparent, ${glowColor}15, transparent)` }}
            />
            <Suspense fallback={
              <div className="w-full h-full flex items-center justify-center">
                <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.25)' }}>Loading terminal...</span>
              </div>
            }>
              <TerminalWidget />
            </Suspense>
          </div>
        )}
      </div>
    </div>
  )
}

function FocusToggle() {
  const { isFocusMode, toggleFocusMode } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'

  return (
    <button
      onClick={toggleFocusMode}
      title={isFocusMode ? 'Exit focus mode' : 'Enter focus mode'}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] transition-all duration-150"
      style={{
        background: isFocusMode ? `${glowColor}15` : 'transparent',
        color: isFocusMode ? glowColor : 'rgba(255,255,255,0.35)',
        border: `1px solid ${isFocusMode ? `${glowColor}30` : 'transparent'}`,
      }}
      onMouseEnter={(e) => {
        if (!isFocusMode) {
          e.currentTarget.style.color = 'rgba(255,255,255,0.6)'
          e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
        }
      }}
      onMouseLeave={(e) => {
        if (!isFocusMode) {
          e.currentTarget.style.color = 'rgba(255,255,255,0.35)'
          e.currentTarget.style.background = 'transparent'
        }
      }}
    >
      <Focus size={10} />
      <span className="font-medium">Focus</span>
    </button>
  )
}

export function DeveloperWorkspace() {
  const { tabs } = useWorkspaceStore()
  const [draggedTabId, setDraggedTabId] = React.useState<string | null>(null)

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) {
      setDraggedTabId(null)
      return
    }

    const oldIndex = tabs.findIndex((t: WorkspaceTab) => t.id === active.id)
    const newIndex = tabs.findIndex((t: WorkspaceTab) => t.id === over.id)

    if (oldIndex !== -1 && newIndex !== -1) {
      const newTabs = [...tabs]
      const [removed] = newTabs.splice(oldIndex, 1)
      newTabs.splice(newIndex, 0, removed)
      useWorkspaceStore.setState({ tabs: newTabs })
    }

    setDraggedTabId(null)
  }

  return (
    <DndContext
      onDragStart={(e: DragStartEvent) => setDraggedTabId(e.active.id as string)}
      onDragEnd={handleDragEnd}
    >
      <div
        className="flex flex-col h-full w-full relative"
        style={{
          background: 'linear-gradient(180deg, rgba(10,11,22,0.2) 0%, rgba(6,7,14,0.1) 100%)',
        }}
      >
        {/* Top toolbar row: Focus toggle + Tab bar */}
        <div
          className="shrink-0 flex items-center gap-2 px-2 py-1.5"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
        >
          <FocusToggle />
          <div className="flex-1 min-w-0">
            <WorkspaceTabBar />
          </div>
        </div>
        <TerminalSection />
        <ArchiveDock />
        <KanbanCanvas />
      </div>
    </DndContext>
  )
}

export default DeveloperWorkspace
