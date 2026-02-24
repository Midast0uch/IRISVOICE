'use client'

import React from 'react'
import { useTransition, type TransitionType } from '@/contexts/TransitionContext'

const TRANSITION_LABELS: Record<TransitionType, string> = {
  'radial-spin': 'Radial Spin',
  'pure-fade': 'Pure Fade',
  'pop-out': 'Pop Out',
  'clockwork': 'Clockwork',
  'holographic': 'Holographic'
}

export function TransitionIndicator() {
  const { currentTransition, cycleTransition, resetToDefault, isHydrated } = useTransition()

  // Only show in development and after hydration to avoid SSR mismatch
  if (process.env.NODE_ENV === 'production' || !isHydrated) {
    return null
  }

  return (
    <div 
      className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 rounded-lg backdrop-blur-md border border-white/10 bg-black/60 text-xs font-mono transition-all duration-200 hover:bg-black/80"
      style={{ pointerEvents: 'auto' }}
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-white/60">Transition:</span>
          <span className="text-cyan-400 font-medium">
            {TRANSITION_LABELS[currentTransition]}
          </span>
        </div>
        <div className="flex items-center gap-1 text-white/40 text-[10px]">
          <kbd className="px-1 py-0.5 rounded bg-white/10">Ctrl</kbd>
          <span>+</span>
          <kbd className="px-1 py-0.5 rounded bg-white/10">Shift</kbd>
          <span>+</span>
          <kbd className="px-1 py-0.5 rounded bg-white/10">T</kbd>
          <span>to cycle</span>
        </div>
      </div>
      <div className="flex flex-col gap-1 ml-2">
        <button
          onClick={cycleTransition}
          className="px-2 py-1 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 transition-colors"
        >
          Next
        </button>
        <button
          onClick={resetToDefault}
          className="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-white/60 transition-colors"
        >
          Reset
        </button>
      </div>
    </div>
  )
}
