'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import { useWorkspaceStore, type WorkspaceState } from '@/stores/workspaceStore'

const SAVE_DEBOUNCE_MS = 2000
const STORAGE_KEY = 'iris_workspace_state'
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

interface PendingOp {
  type: 'save'
  payload: { conversationId: string; state: WorkspaceState }
}

export function useWorkspacePersistence(conversationId?: string) {
  const store = useWorkspaceStore()
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSavedRef = useRef<string>('')
  const pendingQueueRef = useRef<PendingOp[]>([])
  const [isOnline, setIsOnline] = useState(true)
  const [isRestoring, setIsRestoring] = useState(false)

  const persistKey = conversationId ? `${STORAGE_KEY}_${conversationId}` : STORAGE_KEY

  // ── Restore on mount: try backend first, fallback to localStorage ──
  useEffect(() => {
    if (!conversationId) {
      // No conversation ID — just load from localStorage
      restoreFromLocalStorage()
      return
    }

    setIsRestoring(true)
    // Try backend first
    fetch(`${BACKEND_URL}/api/workspace/${encodeURIComponent(conversationId)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => {
        if (data.state) {
          applyState(data.state as WorkspaceState)
        }
      })
      .catch(() => {
        // Backend unavailable — fallback to localStorage
        restoreFromLocalStorage()
      })
      .finally(() => setIsRestoring(false))
  }, [conversationId])

  function restoreFromLocalStorage() {
    const raw = localStorage.getItem(persistKey)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw) as WorkspaceState
      applyState(parsed)
    } catch {
      // Invalid persisted state, ignore
    }
  }

  function applyState(parsed: WorkspaceState) {
    if (parsed.tabs) store.addTab = store.addTab // touch store to init
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
    }, false)
  }

  // ── Sync pending queue when coming back online ──
  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true)
      flushPendingQueue()
    }
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    setIsOnline(navigator.onLine)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [conversationId])

  async function flushPendingQueue() {
    if (!conversationId || pendingQueueRef.current.length === 0) return
    const queue = [...pendingQueueRef.current]
    pendingQueueRef.current = []
    for (const op of queue) {
      try {
        await fetch(`${BACKEND_URL}/api/workspace/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(op.payload),
        })
      } catch {
        // Put back in queue if still failing
        pendingQueueRef.current.push(op)
        break
      }
    }
  }

  // ── Debounced save to backend + localStorage ──
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
      if (json === lastSavedRef.current) return
      lastSavedRef.current = json

      // Always save to localStorage
      localStorage.setItem(persistKey, json)

      // Also save to backend if we have a conversation ID
      if (conversationId) {
        const op: PendingOp = {
          type: 'save',
          payload: { conversationId, state: payload },
        }
        if (isOnline) {
          fetch(`${BACKEND_URL}/api/workspace/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(op.payload),
          }).catch(() => {
            // Backend failed — queue for retry
            pendingQueueRef.current.push(op)
          })
        } else {
          pendingQueueRef.current.push(op)
        }
      }
    }, SAVE_DEBOUNCE_MS)
  }, [persistKey, conversationId, isOnline])

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

  return { persistKey, isOnline, isRestoring, pendingCount: pendingQueueRef.current.length }
}
