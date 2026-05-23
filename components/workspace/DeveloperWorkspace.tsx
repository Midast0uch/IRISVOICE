'use client'

import React, { lazy, Suspense } from 'react'
import { DndContext, DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { useWorkspaceStore, WorkspaceTab } from '@/stores/workspaceStore'
import { WorkspaceTabBar } from './WorkspaceTabBar'
import { KanbanCanvas } from './KanbanCanvas'
import { ArchiveDock } from './ArchiveDock'
import { Focus } from 'lucide-react'

const TerminalWidget = lazy(() => import('../terminal/TerminalWidget'))

function TerminalSection() {
  const { isTerminalExpanded, toggleTerminal } = useWorkspaceStore()

  return (
    <div
      className="shrink-0"
      style={{
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%)',
      }}
    >
      <button
        onClick={toggleTerminal}
        className="w-full flex items-center justify-between px-4 py-1.5 text-[11px] transition-colors"
        style={{ color: 'rgba(255,255,255,0.35)' }}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.7)' }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.35)' }}
      >
        <span className="font-medium tracking-wide">Terminal</span>
        <span>{isTerminalExpanded ? '▾' : '▸'}</span>
      </button>
      {isTerminalExpanded && (
        <div
          className="h-48"
          style={{
            borderTop: '1px solid rgba(255,255,255,0.05)',
            background: 'linear-gradient(180deg, rgba(0,0,0,0.2) 0%, transparent 60%)',
          }}
        >
          <Suspense fallback={
            <div className="w-full h-full flex items-center justify-center text-[10px]" style={{ color: 'rgba(255,255,255,0.2)' }}>
              Loading terminal...
            </div>
          }>
            <TerminalWidget />
          </Suspense>
        </div>
      )}
    </div>
  )
}

function FocusToggle() {
  const { isFocusMode, toggleFocusMode } = useWorkspaceStore()
  return (
    <button
      onClick={toggleFocusMode}
      title={isFocusMode ? 'Exit focus mode' : 'Enter focus mode'}
      className="flex items-center gap-1 px-2 py-1 rounded text-[10px] transition-all duration-150"
      style={{
        background: isFocusMode ? 'rgba(255,255,255,0.10)' : 'transparent',
        color: isFocusMode ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.3)',
        border: '1px solid',
        borderColor: isFocusMode ? 'rgba(255,255,255,0.15)' : 'transparent',
      }}
      onMouseEnter={(e) => {
        if (!isFocusMode) e.currentTarget.style.color = 'rgba(255,255,255,0.6)'
      }}
      onMouseLeave={(e) => {
        if (!isFocusMode) e.currentTarget.style.color = 'rgba(255,255,255,0.3)'
      }}
    >
      <Focus size={10} />
      <span>Focus</span>
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
      <div className="flex flex-col h-full w-full relative">
        {/* Top toolbar row: Focus toggle + Tab bar */}
        <div className="shrink-0 flex items-center gap-2 px-2 py-1" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
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
