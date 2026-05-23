'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { Lightbulb, X } from 'lucide-react'
import type { Suggestion } from '@/types/iris'

interface SuggestionPillsProps {
  suggestions: Suggestion[]
  onSelect: (suggestion: Suggestion) => void
  onDismiss?: () => void
  mode?: 'developer' | 'personal'
  glowColor?: string
  fontColor?: string
}

export function SuggestionPills({
  suggestions,
  onSelect,
  onDismiss,
  mode = 'personal',
  glowColor = '#818cf8',
  fontColor = 'white',
}: SuggestionPillsProps) {
  if (!suggestions || suggestions.length === 0) return null

  const isDev = mode === 'developer'

  return (
    <div className="flex items-center gap-1 flex-wrap">
      <AnimatePresence>
        {suggestions.map((s, i) => (
          <motion.button
            key={`${s.message}-${i}`}
            initial={{ opacity: 0, y: 8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            transition={{ delay: i * 0.06, duration: 0.2 }}
            onClick={() => onSelect(s)}
            className={`
              inline-flex items-center gap-1.5 px-3 py-1.5 mr-2 mb-2
              rounded-full text-[11px] font-medium
              border transition-all cursor-pointer
              ${isDev
                ? 'bg-white/5 border-white/10 text-white/60 hover:text-white/90 hover:bg-white/10 hover:border-white/20'
                : 'bg-white/80 border-white/20 text-slate-600 hover:text-slate-900 hover:bg-white hover:border-slate-300'
              }
            `}
            style={isDev ? {} : { borderColor: `${glowColor}30` }}
          >
            <Lightbulb size={12} className="text-amber-400/70 shrink-0" />
            <span className="truncate max-w-[200px]">{s.label || s.message}</span>
          </motion.button>
        ))}
      </AnimatePresence>
      {onDismiss && (
        <motion.button
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.8 }}
          onClick={onDismiss}
          className="p-1 rounded-full text-white/30 hover:text-white/60 transition-colors"
          title="Dismiss suggestions"
        >
          <X size={12} />
        </motion.button>
      )}
    </div>
  )
}
