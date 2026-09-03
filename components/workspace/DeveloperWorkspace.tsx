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
import { Xur } from '@/components/Xur'
import { HelpPanel } from '@/components/terminal/HelpPanel'
import { FloatingPanel } from './FloatingPanel'
import { useAgentTaskEvents } from '@/hooks/useAgentTaskEvents'
import { Focus, Terminal, Eye, EyeOff, Archive as ArchiveIcon, LayoutGrid, HelpCircle, Undo2, Redo2, Camera, RotateCcw } from 'lucide-react'
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

// T8 (REQ-6): Focus presets now control multi-agent card filtering and
// board density — FULL / ACTIVE / PROJECT / COMPACT.
const PRESET_LABELS: Record<string, string> = {
  full: 'FULL',
  active: 'ACTIVE',
  project: 'PROJECT',
  compact: 'COMPACT',
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
  const { tabs, showArchive, showKanban, addTab, removeTab, sections, isProcessing, takeSnapshot, restoreSnapshot } = useWorkspaceStore()
  const temporal = (useWorkspaceStore as any).temporal ?? null
  const canUndo = (useWorkspaceStore as any).canUndo ?? false
  const canRedo = (useWorkspaceStore as any).canRedo ?? false
  const [draggedTabId, setDraggedTabId] = React.useState<string | null>(null)
  const [helpOpen, setHelpOpen] = React.useState(false)
  const [cliTools, setCliTools] = React.useState<{ name: string; display_name: string; when_to_use: string; available: boolean; reason: string | null }[]>([])
  const handleHelp = React.useCallback(async () => {
    try {
      const res = await fetch('/api/dev/cli-tools')
      if (res.ok) {
        const d = await res.json()
        setCliTools(Array.isArray(d?.tools) ? d.tools : [])
      } else setCliTools([])
    } catch { setCliTools([]) }
    setHelpOpen((v) => !v)
  }, [])
  React.useEffect(() => {
    const h = () => handleHelp()
    window.addEventListener('iris:toggle_help', h)
    return () => window.removeEventListener('iris:toggle_help', h)
  }, [handleHelp])
  const [floatingPanels, setFloatingPanels] = React.useState<PoppedOutCard[]>([])

  // ── Persistence: auto-save/restore workspace state ──
  const { isOnline, isRestoring } = useWorkspacePersistence(conversationId)

  // T9 (REQ-5 AC1): wire the multi-agent Kanban board to backend task
  // lifecycle events (task:start / progress / done) with backend-emitted tags.
  useAgentTaskEvents()

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
        {/* Top toolbar — ONE row, 32px compact (not 40px). Help + history + snapshots in one line. */}
        <div
          className="shrink-0 flex items-center gap-2 px-2 py-1 relative"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', minHeight: '32px' }}
        >
          <FocusToggle />
          <div className="flex-1 min-w-0">
            <WorkspaceTabBar />
          </div>
          <div className="h-4 w-px bg-white/10 shrink-0" />
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => window.dispatchEvent(new CustomEvent('iris:toggle_help'))}
              title="Command reference (/help)"
              className="flex items-center gap-1 px-1.5 py-1 rounded text-[9px] transition-all"
              style={{ background: 'transparent', color: 'rgba(255,255,255,0.45)', border: '1px solid rgba(255,255,255,0.06)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.75)'; e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.45)'; e.currentTarget.style.background = 'transparent'; }}
            >
              <HelpCircle size={9} /> <span className="hidden sm:inline">Help</span>
            </button>
            <SectionToggle section="archive" label="Arch" icon={ArchiveIcon} />
            <SectionToggle section="kanban" label="Board" icon={LayoutGrid} />
          </div>
          <div className="h-4 w-px bg-white/10 shrink-0" />
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={() => (useWorkspaceStore as any).getState?.().temporal?.undo?.()} disabled={!canUndo} title="Undo" className={`p-1 rounded text-[10px] ${canUndo ? 'text-white/40 hover:text-white/70 hover:bg-white/5' : 'text-white/10 cursor-not-allowed'}`}><Undo2 size={10} /></button>
            <button onClick={() => (useWorkspaceStore as any).getState?.().temporal?.redo?.()} disabled={!canRedo} title="Redo" className={`p-1 rounded text-[10px] ${canRedo ? 'text-white/40 hover:text-white/70 hover:bg-white/5' : 'text-white/10 cursor-not-allowed'}`}><Redo2 size={10} /></button>
            <div className="w-px h-3 bg-white/10 mx-1" />
            <button onClick={takeSnapshot} title="Save snapshot" className="flex items-center gap-1 px-1.5 py-1 rounded text-[9px] text-white/30 hover:text-white/60 hover:bg-white/5"><Camera size={10} /><span className="hidden sm:inline">Snap</span></button>
            <button onClick={restoreSnapshot} title="Restore snapshot" className="flex items-center gap-1 px-1.5 py-1 rounded text-[9px] text-white/30 hover:text-white/60 hover:bg-white/5"><RotateCcw size={10} /><span className="hidden sm:inline">Restore</span></button>
            {isProcessing && <span style={{ color: '#60a5fa' }}><Xur size={12} /></span>}
            <span className="text-[9px] text-white/20 ml-1">Workspace v1</span>
          </div>
          {helpOpen && (
            <div className="absolute top-full right-2 mt-2 z-30 w-[380px] max-h-[60vh] overflow-y-auto shadow-2xl">
              <HelpPanel tools={cliTools} onClose={() => setHelpOpen(false)} />
            </div>
          )}
        </div>

        {/* TerminalSection removed — ChatWing now owns the single hybrid CLI (TerminalSlideOver) via terminalScrollback store. Workspace's Term tab was duplicate. */}

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
