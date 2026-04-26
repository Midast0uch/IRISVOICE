'use client'

import React from 'react'
import { useTransition, type TransitionType } from '@/contexts/TransitionContext'
import { getTransitionName } from '@/lib/transitions'

const TRANSITIONS: TransitionType[] = [
  'radial-spin',
  'pure-fade', 
  'pop-out',
  'clockwork',
  'holographic'
]

export function TransitionSwitch() {
  const { currentTransition, setTransition, cycleTransition } = useTransition()

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 p-3 rounded-xl backdrop-blur-md border border-white/10 bg-black/70">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-white/80">Transition Style</span>
        <button
          onClick={cycleTransition}
          className="text-[10px] px-2 py-1 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 transition-colors"
        >
          Cycle
        </button>
      </div>
      
      <div className="flex gap-1">
        {TRANSITIONS.map((t, i) => (
          <button
            key={t}
            onClick={() => setTransition(t)}
            className={`w-8 h-8 rounded-lg text-[10px] font-medium transition-all ${
              currentTransition === t
                ? 'bg-cyan-500 text-white shadow-lg shadow-cyan-500/30'
                : 'bg-white/5 text-white/40 hover:bg-white/10 hover:text-white/60'
            }`}
            title={getTransitionName(t)}
          >
            {i + 1}
          </button>
        ))}
      </div>
      
      <div className="text-center">
        <span className="text-xs text-cyan-400 font-medium">
          {getTransitionName(currentTransition)}
        </span>
      </div>
    </div>
  )
}
