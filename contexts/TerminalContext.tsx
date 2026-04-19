'use client'

import React, { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import { useNavigation } from '@/contexts/NavigationContext'

// ── Types ────────────────────────────────────────────────────────────────────

export interface FileActivityEntry {
  path: string
  change: 'edit' | 'create' | 'delete'
  timestamp: number
}

interface TerminalContextValue {
  isFloating: boolean
  setIsFloating: (floating: boolean) => void
  autoFloat: () => void
  fileActivity: FileActivityEntry[]
  clearFileActivity: () => void
  isFileActivityOpen: boolean
  toggleFileActivity: () => void
  sendMessage: (type: string, payload?: Record<string, unknown>) => boolean | void
}

const TerminalContext = createContext<TerminalContextValue | null>(null)

// ── Provider ─────────────────────────────────────────────────────────────────

const MAX_FILE_ACTIVITY = 50

export function TerminalProvider({ children }: { children: ReactNode }) {
  const { sendMessage } = useNavigation()
  const [isFloating, setIsFloating] = useState(false)
  const [fileActivity, setFileActivity] = useState<FileActivityEntry[]>([])
  const [isFileActivityOpen, setIsFileActivityOpen] = useState(false)

  // Track whether terminal tab is currently the active tab (set by dashboard)
  const isVisibleRef = useRef(false)

  // Auto-float: surface the terminal when agent starts CLI work,
  // but only if it's not already visible (docked + active tab)
  const autoFloat = useCallback(() => {
    if (!isFloating && !isVisibleRef.current) {
      setIsFloating(true)
    }
  }, [isFloating])

  // Listen for CLI started events → auto-float
  useEffect(() => {
    const onCliStarted = () => { autoFloat() }
    window.addEventListener('iris:cli_started', onCliStarted)
    return () => { window.removeEventListener('iris:cli_started', onCliStarted) }
  }, [autoFloat])

  // Listen for file activity events → append to list
  useEffect(() => {
    const onFileActivity = (e: Event) => {
      const detail = (e as CustomEvent).detail as { path?: string; change?: string; timestamp?: number }
      if (detail?.path && detail?.change) {
        const entry: FileActivityEntry = {
          path: detail.path,
          change: detail.change as FileActivityEntry['change'],
          timestamp: detail.timestamp ?? Date.now(),
        }
        setFileActivity(prev => [entry, ...prev].slice(0, MAX_FILE_ACTIVITY))
      }
    }
    window.addEventListener('iris:file_activity', onFileActivity)
    return () => { window.removeEventListener('iris:file_activity', onFileActivity) }
  }, [])

  const clearFileActivity = useCallback(() => setFileActivity([]), [])
  const toggleFileActivity = useCallback(() => setIsFileActivityOpen(prev => !prev), [])

  const value: TerminalContextValue = {
    isFloating,
    setIsFloating,
    autoFloat,
    fileActivity,
    clearFileActivity,
    isFileActivityOpen,
    toggleFileActivity,
    sendMessage,
  }

  return (
    <TerminalContext.Provider value={value}>
      {children}
    </TerminalContext.Provider>
  )
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useTerminal(): TerminalContextValue {
  const ctx = useContext(TerminalContext)
  if (!ctx) throw new Error('useTerminal must be used within TerminalProvider')
  return ctx
}
