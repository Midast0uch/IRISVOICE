'use client'

import { useEffect, useRef, useCallback } from 'react'
import { useWorkspaceStore, type WorkspaceState } from '@/stores/workspaceStore'

const SAVE_DEBOUNCE_MS = 2000
const STORAGE_KEY = 'iris_workspace_state'

export function useWorkspacePersistence(conversationId?: string) {
  const store = useWorkspaceStore()
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSavedRef = useRef<string>('')

  const persistKey = conversationId ? `${STORAGE_KEY}_${conversationId}` : STORAGE_KEY

  // Restore on mount
  useEffect(() => {
    const raw = localStorage.getItem(persistKey)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw) as WorkspaceState
      if (parsed.tabs) store.addTab = store.addTab // touch store to init
      // Merge restored state without triggering temporal tracking
      useWorkspaceStore.setState({
        tabs: parsed.tabs || [],
        sections: parsed.sections || [],
        archived: parsed.archived || [],
        activeTabId: parsed.activeTabId ?? null,
        isTerminalExpanded: parsed.isTerminalExpanded ?? true,
        isFocusMode: parsed.isFocusMode ?? false,
        focusPreset: parsed.focusPreset ?? 'full',
        showTerminal: parsed.showTerminal ?? true,
        showArchive: parsed.showArchive ?? true,
        showKanban: parsed.showKanban ?? true,
        kanbanCompact: parsed.kanbanCompact ?? false,
      }, false) // false = don't notify subscribers yet
    } catch {
      // Invalid persisted state, ignore
    }
  }, [persistKey])

  // Debounced save
  const scheduleSave = useCallback(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => {
      const state = useWorkspaceStore.getState()
      const payload: WorkspaceState = {
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
      }
      const json = JSON.stringify(payload)
      if (json !== lastSavedRef.current) {
        localStorage.setItem(persistKey, json)
        lastSavedRef.current = json
      }
    }, SAVE_DEBOUNCE_MS)
  }, [persistKey])

  // Subscribe to all store changes and schedule save
  useEffect(() => {
    const unsubscribe = useWorkspaceStore.subscribe(() => {
      scheduleSave()
    })
    return () => {
      unsubscribe()
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    }
  }, [scheduleSave])

  return { persistKey }
}
