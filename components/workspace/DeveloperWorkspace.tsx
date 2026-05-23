'use client'

import React, { lazy, Suspense } from 'react'
import { DndContext, DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { useWorkspaceStore, WorkspaceTab } from '@/stores/workspaceStore'
import { WorkspaceTabBar } from './WorkspaceTabBar'
import { KanbanCanvas } from './KanbanCanvas'
import { ArchiveDock } from './ArchiveDock'
import { WorkspaceToolbar } from './WorkspaceToolbar'

const TerminalWidget = lazy(() => import('../terminal/TerminalWidget'))

function TerminalSection() {
  const { isTerminalExpanded, toggleTerminal } = useWorkspaceStore()

  return (
    <div className="shrink-0 border-b border-white/5">
      <button
        onClick={toggleTerminal}
        className="w-full flex items-center justify-between px-4 py-1.5 text-[11px] text-white/40 hover:text-white/70 transition-colors"
      >
        <span>Terminal</span>
        <span>{isTerminalExpanded ? '▾' : '▸'}</span>
      </button>
      {isTerminalExpanded && (
        <div className="h-48 border-t border-white/5">
          <Suspense fallback={
            <div className="w-full h-full flex items-center justify-center text-[10px] text-white/20">
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

export function DeveloperWorkspace() {
  const { tabs, setActiveTab } = useWorkspaceStore()
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
      <div className="flex flex-col h-full w-full" style={{ background: 'rgba(6,7,14,0.99)' }}>
        <WorkspaceTabBar />
        <TerminalSection />
        <ArchiveDock />
        <KanbanCanvas />
        <WorkspaceToolbar />
      </div>
    </DndContext>
  )
}

export default DeveloperWorkspace
