import { create } from 'zustand'

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

export interface WorkspaceState {
  tabs: WorkspaceTab[]
  sections: KanbanSection[]
  archived: ArchiveDockItem[]
  activeTabId: string | null
  isTerminalExpanded: boolean
  isFocusMode: boolean
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

  // Terminal
  toggleTerminal: () => void
  setTerminalExpanded: (expanded: boolean) => void

  // Focus mode
  toggleFocusMode: () => void
}

export const useWorkspaceStore = create<WorkspaceStore>((set, get) => ({
  tabs: [],
  sections: [],
  archived: [],
  activeTabId: null,
  isTerminalExpanded: true,
  isFocusMode: false,

  addTab: (tab) =>
    set((state) => ({
      tabs: [...state.tabs, tab],
      activeTabId: tab.id,
    })),

  removeTab: (tabId) =>
    set((state) => ({
      tabs: state.tabs.filter((t) => t.id !== tabId),
      activeTabId: state.activeTabId === tabId ? null : state.activeTabId,
    })),

  setActiveTab: (tabId) => set({ activeTabId: tabId }),

  addSection: (section) =>
    set((state) => ({
      sections: [...state.sections, section],
    })),

  removeSection: (sectionId) =>
    set((state) => ({
      sections: state.sections.filter((s) => s.id !== sectionId),
      archived: state.archived.filter(
        (a) => a.originalSectionId !== sectionId
      ),
    })),

  updateSectionWidth: (sectionId, width) =>
    set((state) => ({
      sections: state.sections.map((s) =>
        s.id === sectionId ? { ...s, width: Math.max(200, Math.min(width, 800)) } : s
      ),
    })),

  toggleSectionCollapse: (sectionId) =>
    set((state) => ({
      sections: state.sections.map((s) =>
        s.id === sectionId ? { ...s, isCollapsed: !s.isCollapsed } : s
      ),
    })),

  addCard: (card) =>
    set((state) => ({
      sections: state.sections.map((s) =>
        s.id === card.sectionId ? { ...s, cards: [...s.cards, card] } : s
      ),
    })),

  moveCard: (cardId, targetSectionId) =>
    set((state) => {
      const card = state.sections
        .flatMap((s) => s.cards)
        .find((c) => c.id === cardId)
      if (!card) return state
      return {
        sections: state.sections.map((s) => {
          if (s.id === card.sectionId) {
            return { ...s, cards: s.cards.filter((c) => c.id !== cardId) }
          }
          if (s.id === targetSectionId) {
            return { ...s, cards: [...s.cards, { ...card, sectionId: targetSectionId }] }
          }
          return s
        }),
      }
    }),

  updateCardState: (cardId, newState) =>
    set((state) => ({
      sections: state.sections.map((s) => ({
        ...s,
        cards: s.cards.map((c) =>
          c.id === cardId ? { ...c, state: newState } : c
        ),
      })),
    })),

  archiveCard: (cardId) =>
    set((state) => {
      const card = state.sections
        .flatMap((s) => s.cards)
        .find((c) => c.id === cardId)
      if (!card) return state
      return {
        sections: state.sections.map((s) => ({
          ...s,
          cards: s.cards.filter((c) => c.id !== cardId),
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

  unarchiveCard: (cardId) =>
    set((state) => {
      const archiveItem = state.archived.find((a) => a.cardId === cardId)
      if (!archiveItem) return state
      const tab = state.tabs.find((t) => t.id === archiveItem.tabId)
      const section = state.sections.find(
        (s) => s.id === archiveItem.originalSectionId
      )
      const targetSectionId = section ? section.id : state.sections[0]?.id
      if (!targetSectionId) return state
      return {
        archived: state.archived.filter((a) => a.cardId !== cardId),
        sections: state.sections.map((s) =>
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

  removeCard: (cardId) =>
    set((state) => ({
      sections: state.sections.map((s) => ({
        ...s,
        cards: s.cards.filter((c) => c.id !== cardId),
      })),
      archived: state.archived.filter((a) => a.cardId !== cardId),
    })),

  toggleTerminal: () =>
    set((state) => ({ isTerminalExpanded: !state.isTerminalExpanded })),

  setTerminalExpanded: (expanded) => set({ isTerminalExpanded: expanded }),

  toggleFocusMode: () =>
    set((state) => ({ isFocusMode: !state.isFocusMode })),
}))
