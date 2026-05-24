import { create } from 'zustand'
import { temporal } from 'zundo'

export type TabType = 'file' | 'folder' | 'conversation' | 'document' | 'terminal'

export interface WorkspaceTab {
  id: string
  type: TabType
  path: string
  label: string
  icon: string
  isVirtual: boolean
}

export type CardState = 'maximized' | 'minimized' | 'archived'
export type ViewMode = 'preview' | 'mindmap' | 'rendered' | 'raw' | 'code'

export interface KanbanCard {
  id: string
  tabId: string
  sectionId: string
  state: CardState
  viewMode: ViewMode
  scrollPosition: number
}

export interface KanbanSection {
  id: string
  title: string
  width: number
  isCollapsed: boolean
  cards: KanbanCard[]
}

export interface ArchiveDockItem {
  cardId: string
  tabId: string
  originalSectionId: string
}

export type FocusPreset = 'full' | 'work' | 'chat' | 'zen'

export interface WorkspaceState {
  tabs: WorkspaceTab[]
  sections: KanbanSection[]
  archived: ArchiveDockItem[]
  activeTabId: string | null
  isTerminalExpanded: boolean
  isFocusMode: boolean
  focusPreset: FocusPreset
  showTerminal: boolean
  showArchive: boolean
  showKanban: boolean
  kanbanCompact: boolean
}

interface TemporalApi {
  pastStates: Partial<WorkspaceStore>[]
  futureStates: Partial<WorkspaceStore>[]
  undo: (steps?: number) => void
  redo: (steps?: number) => void
  clear: () => void
  isTracking: boolean
  pause: () => void
  resume: () => void
}

interface WorkspaceStore extends WorkspaceState {
  // Tab actions
  addTab: (tab: WorkspaceTab) => void
  removeTab: (tabId: string) => void
  setActiveTab: (tabId: string | null) => void

  // Section actions
  addSection: (section: KanbanSection) => void
  removeSection: (sectionId: string) => void
  updateSectionWidth: (sectionId: string, width: number) => void
  toggleSectionCollapse: (sectionId: string) => void

  // Card actions
  addCard: (card: KanbanCard) => void
  moveCard: (cardId: string, targetSectionId: string) => void
  updateCardState: (cardId: string, state: CardState) => void
  archiveCard: (cardId: string) => void
  unarchiveCard: (cardId: string) => void
  removeCard: (cardId: string) => void
  closeCard: (cardId: string) => void

  // Terminal
  toggleTerminal: () => void
  setTerminalExpanded: (expanded: boolean) => void

  // Focus mode
  toggleFocusMode: () => void
  setFocusPreset: (preset: FocusPreset) => void

  // Section visibility
  toggleSectionVisible: (section: 'terminal' | 'archive' | 'kanban') => void
  toggleKanbanCompact: () => void

  // Snapshot
  takeSnapshot: () => void
  restoreSnapshot: () => void
  snapshot: WorkspaceState | null

  // Undo/redo (added by zundo)
  temporal?: TemporalApi
}

export const useWorkspaceStore = create<WorkspaceStore>()(
  temporal(
    (set, get) => ({
      tabs: [],
      sections: [],
      archived: [],
      activeTabId: null,
      isTerminalExpanded: true,
      isFocusMode: false,
      focusPreset: 'full',
      showTerminal: true,
      showArchive: true,
      showKanban: true,
      kanbanCompact: false,
      snapshot: null,

  addTab: (tab: WorkspaceTab) =>
    set((state: WorkspaceStore) => ({
      tabs: [...state.tabs, tab],
      activeTabId: tab.id,
    })),

  removeTab: (tabId: string) =>
    set((state: WorkspaceStore) => ({
      tabs: state.tabs.filter((t: WorkspaceTab) => t.id !== tabId),
      activeTabId: state.activeTabId === tabId ? null : state.activeTabId,
    })),

  setActiveTab: (tabId: string | null) => set({ activeTabId: tabId }),

  addSection: (section: KanbanSection) =>
    set((state: WorkspaceStore) => ({
      sections: [...state.sections, section],
    })),

  removeSection: (sectionId: string) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.filter((s: KanbanSection) => s.id !== sectionId),
      archived: state.archived.filter(
        (a: ArchiveDockItem) => a.originalSectionId !== sectionId
      ),
    })),

  updateSectionWidth: (sectionId: string, width: number) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.map((s: KanbanSection) =>
        s.id === sectionId ? { ...s, width: Math.max(200, Math.min(width, 800)) } : s
      ),
    })),

  toggleSectionCollapse: (sectionId: string) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.map((s: KanbanSection) =>
        s.id === sectionId ? { ...s, isCollapsed: !s.isCollapsed } : s
      ),
    })),

  addCard: (card: KanbanCard) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.map((s: KanbanSection) =>
        s.id === card.sectionId ? { ...s, cards: [...s.cards, card] } : s
      ),
    })),

  moveCard: (cardId: string, targetSectionId: string) =>
    set((state: WorkspaceStore) => {
      const card = state.sections
        .flatMap((s: KanbanSection) => s.cards)
        .find((c: KanbanCard) => c.id === cardId)
      if (!card) return state
      return {
        sections: state.sections.map((s: KanbanSection) => {
          if (s.id === card.sectionId) {
            return { ...s, cards: s.cards.filter((c: KanbanCard) => c.id !== cardId) }
          }
          if (s.id === targetSectionId) {
            return { ...s, cards: [...s.cards, { ...card, sectionId: targetSectionId }] }
          }
          return s
        }),
      }
    }),

  updateCardState: (cardId: string, newState: CardState) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.map((s: KanbanSection) => ({
        ...s,
        cards: s.cards.map((c: KanbanCard) =>
          c.id === cardId ? { ...c, state: newState } : c
        ),
      })),
    })),

  archiveCard: (cardId: string) =>
    set((state: WorkspaceStore) => {
      const card = state.sections
        .flatMap((s: KanbanSection) => s.cards)
        .find((c: KanbanCard) => c.id === cardId)
      if (!card) return state
      return {
        sections: state.sections.map((s: KanbanSection) => ({
          ...s,
          cards: s.cards.filter((c: KanbanCard) => c.id !== cardId),
        })),
        archived: [
          ...state.archived,
          {
            cardId: card.id,
            tabId: card.tabId,
            originalSectionId: card.sectionId,
          },
        ],
      }
    }),

  unarchiveCard: (cardId: string) =>
    set((state: WorkspaceStore) => {
      const archiveItem = state.archived.find((a: ArchiveDockItem) => a.cardId === cardId)
      if (!archiveItem) return state
      const tab = state.tabs.find((t: WorkspaceTab) => t.id === archiveItem.tabId)
      const section = state.sections.find(
        (s: KanbanSection) => s.id === archiveItem.originalSectionId
      )
      const targetSectionId = section ? section.id : state.sections[0]?.id
      if (!targetSectionId) return state
      return {
        archived: state.archived.filter((a: ArchiveDockItem) => a.cardId !== cardId),
        sections: state.sections.map((s: KanbanSection) =>
          s.id === targetSectionId
            ? {
                ...s,
                cards: [
                  ...s.cards,
                  {
                    id: cardId,
                    tabId: archiveItem.tabId,
                    sectionId: targetSectionId,
                    state: 'maximized' as CardState,
                    viewMode: 'preview' as ViewMode,
                    scrollPosition: 0,
                  },
                ],
              }
            : s
        ),
      }
    }),

  removeCard: (cardId: string) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.map((s: KanbanSection) => ({
        ...s,
        cards: s.cards.filter((c: KanbanCard) => c.id !== cardId),
      })),
      archived: state.archived.filter((a: ArchiveDockItem) => a.cardId !== cardId),
    })),

  closeCard: (cardId: string) =>
    set((state: WorkspaceStore) => ({
      sections: state.sections.map((s: KanbanSection) => ({
        ...s,
        cards: s.cards.filter((c: KanbanCard) => c.id !== cardId),
      })),
    })),

  toggleTerminal: () =>
    set((state: WorkspaceStore) => ({ isTerminalExpanded: !state.isTerminalExpanded })),

  setTerminalExpanded: (expanded: boolean) => set({ isTerminalExpanded: expanded }),

  toggleFocusMode: () =>
    set((state: WorkspaceStore) => {
      const presets: FocusPreset[] = ['full', 'work', 'chat', 'zen']
      const idx = presets.indexOf(state.focusPreset)
      const next = presets[(idx + 1) % presets.length]
      const configs: Record<FocusPreset, Partial<WorkspaceStore>> = {
        full: { showTerminal: true, showArchive: true, showKanban: true, kanbanCompact: false, isTerminalExpanded: true },
        work: { showTerminal: true, showArchive: false, showKanban: true, kanbanCompact: false, isTerminalExpanded: true },
        chat: { showTerminal: false, showArchive: false, showKanban: true, kanbanCompact: true, isTerminalExpanded: false },
        zen: { showTerminal: false, showArchive: false, showKanban: false, kanbanCompact: false, isTerminalExpanded: false },
      }
      return { focusPreset: next, isFocusMode: true, ...configs[next] }
    }),

  setFocusPreset: (preset: FocusPreset) =>
    set((state: WorkspaceStore) => {
      const configs: Record<FocusPreset, Partial<WorkspaceStore>> = {
        full: { showTerminal: true, showArchive: true, showKanban: true, kanbanCompact: false, isTerminalExpanded: true },
        work: { showTerminal: true, showArchive: false, showKanban: true, kanbanCompact: false, isTerminalExpanded: true },
        chat: { showTerminal: false, showArchive: false, showKanban: true, kanbanCompact: true, isTerminalExpanded: false },
        zen: { showTerminal: false, showArchive: false, showKanban: false, kanbanCompact: false, isTerminalExpanded: false },
      }
      return { focusPreset: preset, isFocusMode: true, ...configs[preset] }
    }),

  toggleSectionVisible: (section: 'terminal' | 'archive' | 'kanban') =>
    set((state: WorkspaceStore) => {
      const key = section === 'terminal' ? 'showTerminal' : section === 'archive' ? 'showArchive' : 'showKanban'
      return { [key]: !state[key as keyof WorkspaceStore] } as Partial<WorkspaceStore>
    }),

  toggleKanbanCompact: () =>
    set((state: WorkspaceStore) => ({ kanbanCompact: !state.kanbanCompact })),

  takeSnapshot: () => {
    const state = get()
    set({ snapshot: { ...state, snapshot: null } as WorkspaceState })
  },

  restoreSnapshot: () => {
    const state = get()
    if (state.snapshot) {
      set({ ...state.snapshot, snapshot: state.snapshot })
    }
  },
}),
  {
    limit: 50,
    partialize: (state: WorkspaceStore) => ({
      tabs: state.tabs,
      sections: state.sections,
      archived: state.archived,
      activeTabId: state.activeTabId,
      isTerminalExpanded: state.isTerminalExpanded,
      isFocusMode: state.isFocusMode,
      focusPreset: state.focusPreset,
      showTerminal: state.showTerminal,
      showArchive: state.showArchive,
      showKanban: state.showKanban,
      kanbanCompact: state.kanbanCompact,
    }),
  }
))

// ── Temporal hooks for undo/redo ───────────────────────────────────────────
export function useTemporalStore() {
  return useWorkspaceStore((state: WorkspaceStore) => state.temporal!)
}

export function useCanUndo() {
  return useWorkspaceStore((state: WorkspaceStore) => (state.temporal?.pastStates.length ?? 0) > 0)
}

export function useCanRedo() {
  return useWorkspaceStore((state: WorkspaceStore) => (state.temporal?.futureStates.length ?? 0) > 0)
}

export function useUndoCount() {
  return useWorkspaceStore((state: WorkspaceStore) => state.temporal?.pastStates.length ?? 0)
}

export function useRedoCount() {
  return useWorkspaceStore((state: WorkspaceStore) => state.temporal?.futureStates.length ?? 0)
}
