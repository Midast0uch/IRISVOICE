'use client'

import React, { lazy, Suspense } from 'react'
import { DndContext, DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { useWorkspaceStore, WorkspaceTab } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useFileWatcher } from '@/hooks/useFileWatcher'
import { useWorkspacePersistence } from '@/hooks/useWorkspacePersistence'
import { WorkspaceTabBar } from './WorkspaceTabBar'
import { KanbanCanvas } from './KanbanCanvas'
import { ArchiveDock } from './ArchiveDock'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { FloatingPanel } from './FloatingPanel'
import { Focus, Terminal, Eye, EyeOff, Archive as ArchiveIcon, LayoutGrid } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

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

        {isTerminalExpanded ? (
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
        ) : (
          /* Collapsed $ strip */
          <div
            className="flex items-center px-3 py-1.5 cursor-pointer"
            onClick={toggleTerminal}
            style={{
              background: 'linear-gradient(180deg, rgba(6,7,14,0.6) 0%, rgba(4,5,10,0.4) 100%)',
            }}
          >
            <span
              className="text-[11px] font-mono mr-2"
              style={{ color: '#34d399', textShadow: '0 0 6px rgba(52,211,153,0.3)' }}
            >
              $
            </span>
            <span
              className="w-2 h-[14px] inline-block animate-pulse"
              style={{
                background: 'rgba(52,211,153,0.6)',
                boxShadow: '0 0 4px rgba(52,211,153,0.3)',
              }}
            />
            <span className="ml-2 text-[9px]" style={{ color: 'rgba(255,255,255,0.2)' }}>
              Click to expand
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

const PRESET_LABELS: Record<string, string> = {
  full: 'Full',
  work: 'Work',
  chat: 'Chat',
  zen: 'Zen',
}

function FocusToggle() {
  const { focusPreset, toggleFocusMode } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const isActive = focusPreset !== 'full'

  return (
    <button
      onClick={toggleFocusMode}
      title={`Focus: ${PRESET_LABELS[focusPreset]} (click to cycle)`}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] transition-all duration-150"
      style={{
        background: isActive ? `${glowColor}15` : 'transparent',
        color: isActive ? glowColor : 'rgba(255,255,255,0.35)',
        border: `1px solid ${isActive ? `${glowColor}30` : 'transparent'}`,
      }}
      onMouseEnter={(e) => {
        if (!isActive) {
          e.currentTarget.style.color = 'rgba(255,255,255,0.6)'
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
      <Focus size={10} />
      <span className="font-medium">{PRESET_LABELS[focusPreset]}</span>
    </button>
  )
}

function SectionToggle({ section, label, icon: Icon }: { section: 'terminal' | 'archive' | 'kanban'; label: string; icon: typeof Eye }) {
  const { showTerminal, showArchive, showKanban, toggleSectionVisible } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const isVisible = section === 'terminal' ? showTerminal : section === 'archive' ? showArchive : showKanban

  return (
    <button
      onClick={() => toggleSectionVisible(section)}
      title={`${isVisible ? 'Hide' : 'Show'} ${label}`}
      className="flex items-center gap-1 px-1.5 py-1 rounded text-[9px] transition-all duration-150"
      style={{
        background: isVisible ? `${glowColor}10` : 'transparent',
        color: isVisible ? `${glowColor}90` : 'rgba(255,255,255,0.2)',
        border: `1px solid ${isVisible ? `${glowColor}20` : 'rgba(255,255,255,0.06)'}`,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = isVisible ? glowColor : 'rgba(255,255,255,0.5)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = isVisible ? `${glowColor}90` : 'rgba(255,255,255,0.2)'
      }}
    >
      {isVisible ? <Eye size={9} /> : <EyeOff size={9} />}
      <span className="hidden sm:inline">{label}</span>
    </button>
  )
}

interface PoppedOutCard {
  cardId: string
  tabId: string
  x: number
  y: number
}

export function DeveloperWorkspace({ conversationId }: { conversationId?: string }) {
  const { tabs, showTerminal, showArchive, showKanban, addTab, removeTab, sections } = useWorkspaceStore()
  const [draggedTabId, setDraggedTabId] = React.useState<string | null>(null)
  const [floatingPanels, setFloatingPanels] = React.useState<PoppedOutCard[]>([])

  // ── Persistence: auto-save/restore workspace state ──
  const { isOnline, isRestoring } = useWorkspacePersistence(conversationId)

  // ── File Watcher: live card updates from external file changes ──
  useFileWatcher({
    onEvent: (event) => {
      // Find any card that references this path and trigger refresh
      const state = useWorkspaceStore.getState()
      const matchingCards = state.sections
        .flatMap((s) => s.cards)
        .filter((c) => {
          const tab = state.tabs.find((t) => t.id === c.tabId)
          return tab && event.path.includes(tab.path)
        })
      if (matchingCards.length > 0) {
        // Cards referencing changed files get a fresh preview
        // (The CardContentRenderer will re-fetch on next render)
        console.log('[FileWatcher] Cards affected:', matchingCards.map((c) => c.tabId))
      }
    },
  })

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

  // ── Pop out card to floating panel ──
  const handlePopOut = (cardId: string, tabId: string) => {
    // Remove card from its section (it lives in floating panel now)
    useWorkspaceStore.setState((state) => ({
      sections: state.sections.map((s) => ({
        ...s,
        cards: s.cards.filter((c) => c.id !== cardId),
      })),
    }))
    setFloatingPanels((prev) => [
      ...prev,
      { cardId, tabId, x: 100 + prev.length * 30, y: 100 + prev.length * 20 },
    ])
  }

  const closeFloatingPanel = (cardId: string) => {
    setFloatingPanels((prev) => prev.filter((p) => p.cardId !== cardId))
  }

  return (
    <>
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
        {/* Top toolbar row: Focus toggle + Tab bar + Section toggles */}
        <div
          className="shrink-0 flex items-center gap-2 px-2 py-1.5"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
        >
          <FocusToggle />
          <div className="flex-1 min-w-0">
            <WorkspaceTabBar />
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <SectionToggle section="terminal" label="Term" icon={Eye} />
            <SectionToggle section="archive" label="Arch" icon={ArchiveIcon} />
            <SectionToggle section="kanban" label="Board" icon={LayoutGrid} />
          </div>
        </div>

        <AnimatePresence initial={false}>
          {showTerminal && (
            <motion.div
              key="terminal"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
              className="shrink-0 overflow-hidden"
            >
              <TerminalSection />
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {showArchive && (
            <motion.div
              key="archive"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
              className="shrink-0 overflow-hidden"
            >
              <ArchiveDock dragLocked={!!draggedTabId} />
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {showKanban && (
            <motion.div
              key="kanban"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex-1 min-h-0"
            >
              <KanbanCanvas onPopOut={handlePopOut} />
            </motion.div>
          )}
        </AnimatePresence>

        <WorkspaceToolbar />
      </div>
    </DndContext>

    {/* Floating panels — rendered outside DndContext so they float above everything */}
    {floatingPanels.map((panel) => (
      <FloatingPanel
        key={panel.cardId}
        cardId={panel.cardId}
        tabId={panel.tabId}
        initialX={panel.x}
        initialY={panel.y}
        onClose={() => closeFloatingPanel(panel.cardId)}
      />
    ))}
    </>
  )
}

export default DeveloperWorkspace
