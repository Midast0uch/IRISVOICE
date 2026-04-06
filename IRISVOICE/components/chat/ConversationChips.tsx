'use client'

import { useRef, useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronUp, ChevronDown } from 'lucide-react'
import type { ConversationChip } from '@/types/iris'

interface ConversationChipsProps {
  chips: ConversationChip[]
  glowColor: string
  onChipClick: (messageId: string) => void
}

export function ConversationChips({
  chips,
  glowColor,
  onChipClick,
}: ConversationChipsProps) {
  const [isOpen, setIsOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLDivElement>(null)

  // Close panel when clicking outside
  useEffect(() => {
    if (!isOpen) return
    function handleOutside(e: MouseEvent) {
      if (
        panelRef.current && !panelRef.current.contains(e.target as Node) &&
        triggerRef.current && !triggerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [isOpen])

  if (chips.length === 0) return null

  const recentChips = chips.slice(-3) // show last 3 in the collapsed bar

  function handleChipSelect(messageId: string) {
    setIsOpen(false)
    onChipClick(messageId)
  }

  return (
    <div className="relative px-3 pb-1.5">

      {/* Vertical drop-up panel — appears above the chip bar */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            ref={panelRef}
            key="chip-panel"
            initial={{ opacity: 0, y: 10, scaleY: 0.92 }}
            animate={{ opacity: 1, y: 0, scaleY: 1 }}
            exit={{ opacity: 0, y: 10, scaleY: 0.92 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            style={{ transformOrigin: 'bottom center' }}
            className="absolute bottom-full left-3 right-3 mb-2 z-50
                       overflow-hidden"
          >
            {/* Frosted glass blur backdrop */}
            <div
              className="absolute inset-0 rounded-none"
              style={{
                backdropFilter: 'blur(16px) saturate(1.4)',
                WebkitBackdropFilter: 'blur(16px) saturate(1.4)',
                background: 'rgba(10, 10, 14, 0.78)',
                border: `1px solid ${glowColor}25`,
                boxShadow: `0 -4px 32px rgba(0,0,0,0.5), inset 0 1px 0 ${glowColor}15`,
              }}
            />

            {/* Header */}
            <div
              className="relative flex items-center justify-between px-3 py-2 border-b"
              style={{ borderColor: `${glowColor}20` }}
            >
              <span
                className="text-[10px] uppercase tracking-[0.18em] font-semibold"
                style={{ color: `${glowColor}90` }}
              >
                Conversation history
              </span>
              <span
                className="text-[10px] font-mono"
                style={{ color: `${glowColor}60` }}
              >
                {chips.length} prompt{chips.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Scrollable vertical prompt list */}
            <div
              className="relative overflow-y-auto"
              style={{
                maxHeight: '220px',
                scrollbarWidth: 'thin',
                scrollbarColor: `${glowColor}30 transparent`,
              }}
            >
              {/* Top fade */}
              <div
                className="sticky top-0 left-0 right-0 h-4 pointer-events-none z-10"
                style={{
                  background: `linear-gradient(to bottom, rgba(10,10,14,0.9) 0%, transparent 100%)`,
                }}
              />

              <div className="px-2 pb-2 pt-0 flex flex-col gap-1">
                {chips.map((chip, i) => (
                  <motion.button
                    key={chip.messageId}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.025, duration: 0.12 }}
                    onClick={() => handleChipSelect(chip.messageId)}
                    className="w-full text-left px-3 py-2 text-[12px] font-medium
                               transition-all duration-120 group"
                    style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: `1px solid ${glowColor}18`,
                      color: 'rgba(255,255,255,0.5)',
                      borderRadius: 0,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = `${glowColor}12`
                      e.currentTarget.style.borderColor = `${glowColor}45`
                      e.currentTarget.style.color = 'rgba(255,255,255,0.9)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
                      e.currentTarget.style.borderColor = `${glowColor}18`
                      e.currentTarget.style.color = 'rgba(255,255,255,0.5)'
                    }}
                  >
                    <span className="flex items-start gap-2">
                      <span
                        className="shrink-0 text-[9px] font-mono mt-0.5 w-4 text-right"
                        style={{ color: `${glowColor}50` }}
                      >
                        {i + 1}
                      </span>
                      <span className="truncate leading-relaxed">{chip.label}</span>
                    </span>
                  </motion.button>
                ))}
              </div>

              {/* Bottom fade */}
              <div
                className="sticky bottom-0 left-0 right-0 h-4 pointer-events-none"
                style={{
                  background: `linear-gradient(to top, rgba(10,10,14,0.9) 0%, transparent 100%)`,
                }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Collapsed bar — recent rectangular chips + toggle */}
      <motion.div
        ref={triggerRef}
        className="flex items-center gap-1.5"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.2 }}
      >
        {/* Recent chips — last 3, rectangular */}
        {recentChips.map((chip) => (
          <button
            key={chip.messageId}
            onClick={() => setIsOpen((o) => !o)}
            className="shrink-0 px-2.5 py-[5px] text-[10px] font-medium
                       transition-all duration-150 whitespace-nowrap max-w-[140px] truncate"
            style={{
              background: isOpen ? `${glowColor}18` : 'rgba(255,255,255,0.04)',
              border: `1px solid ${isOpen ? `${glowColor}50` : `${glowColor}25`}`,
              color: isOpen ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.45)',
              borderRadius: 0,
            }}
            title={chip.label}
          >
            {chip.label}
          </button>
        ))}

        {/* Overflow count + toggle chevron */}
        <button
          onClick={() => setIsOpen((o) => !o)}
          className="flex items-center gap-1 px-2 py-[5px] text-[10px] font-mono
                     transition-all duration-150 ml-auto shrink-0"
          style={{
            background: isOpen ? `${glowColor}18` : 'rgba(255,255,255,0.03)',
            border: `1px solid ${isOpen ? `${glowColor}50` : `${glowColor}20`}`,
            color: isOpen ? `${glowColor}` : `${glowColor}70`,
            borderRadius: 0,
          }}
          title={isOpen ? 'Close history' : `Show all ${chips.length} prompts`}
        >
          <span>{chips.length}</span>
          {isOpen
            ? <ChevronDown size={10} />
            : <ChevronUp size={10} />
          }
        </button>
      </motion.div>
    </div>
  )
}
