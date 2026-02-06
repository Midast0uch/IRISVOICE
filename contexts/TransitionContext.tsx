'use client'

import React, { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react'

// === TYPES ===
export type TransitionType = 
  | 'radial-spin' 
  | 'pure-fade' 
  | 'pop-out' 
  | 'clockwork' 
  | 'holographic'

export interface TransitionContextType {
  currentTransition: TransitionType
  cycleTransition: () => void
  setTransition: (transition: TransitionType) => void
  resetToDefault: () => void
  isHydrated: boolean
}

// === DEFAULT VALUES ===
const DEFAULT_TRANSITION: TransitionType = 'radial-spin'

const TRANSITION_ORDER: TransitionType[] = [
  'radial-spin',
  'pure-fade',
  'pop-out',
  'clockwork',
  'holographic'
]

const STORAGE_KEY = 'iris-transition-type'

// === CONTEXT ===
const TransitionContext = createContext<TransitionContextType | undefined>(undefined)

// === PROVIDER ===
export function TransitionProvider({ children }: { children: React.ReactNode }) {
  // Always start with default for SSR consistency
  const [currentTransition, setCurrentTransition] = useState<TransitionType>(DEFAULT_TRANSITION)
  const [isHydrated, setIsHydrated] = useState(false)

  // Load from localStorage after hydration
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && TRANSITION_ORDER.includes(stored as TransitionType)) {
      setCurrentTransition(stored as TransitionType)
    }
    setIsHydrated(true)
  }, [])

  // Persist transition preference to localStorage
  useEffect(() => {
    if (isHydrated) {
      localStorage.setItem(STORAGE_KEY, currentTransition)
    }
  }, [currentTransition, isHydrated])

  const cycleTransition = useCallback(() => {
    setCurrentTransition(prev => {
      const currentIndex = TRANSITION_ORDER.indexOf(prev)
      const nextIndex = (currentIndex + 1) % TRANSITION_ORDER.length
      const nextTransition = TRANSITION_ORDER[nextIndex]
      return nextTransition
    })
  }, [])

  const setTransition = useCallback((transition: TransitionType) => {
    if (TRANSITION_ORDER.includes(transition)) {
      setCurrentTransition(transition)
    }
  }, [])

  const resetToDefault = useCallback(() => {
    setCurrentTransition(DEFAULT_TRANSITION)
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Shift+T: Cycle to next transition
      if (e.ctrlKey && e.shiftKey && e.key === 'T') {
        e.preventDefault()
        cycleTransition()
      }
      // Ctrl+Shift+R: Reset to default
      if (e.ctrlKey && e.shiftKey && e.key === 'R') {
        e.preventDefault()
        resetToDefault()
      }
      // Ctrl+Shift+1-5: Jump to specific transition
      if (e.ctrlKey && e.shiftKey && ['1', '2', '3', '4', '5'].includes(e.key)) {
        e.preventDefault()
        const index = parseInt(e.key) - 1
        if (index >= 0 && index < TRANSITION_ORDER.length) {
          setTransition(TRANSITION_ORDER[index])
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [cycleTransition, resetToDefault, setTransition])

  const value = useMemo(() => ({
    currentTransition,
    cycleTransition,
    setTransition,
    resetToDefault,
    isHydrated
  }), [currentTransition, cycleTransition, setTransition, resetToDefault, isHydrated])

  return (
    <TransitionContext.Provider value={value}>
      {children}
    </TransitionContext.Provider>
  )
}

// === HOOK ===
export function useTransition() {
  const context = useContext(TransitionContext)
  if (context === undefined) {
    throw new Error('useTransition must be used within a TransitionProvider')
  }
  return context
}

// === UTILITIES ===
export function getTransitionIndex(transition: TransitionType): number {
  return TRANSITION_ORDER.indexOf(transition)
}

export function getTransitionByIndex(index: number): TransitionType | undefined {
  return TRANSITION_ORDER[index]
}
