'use client'

import { useRef, useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlignJustify } from 'lucide-react'
import type { ConversationChip } from '@/types/iris'

interface ConversationChipsProps {
  chips: ConversationChip[]
  glowColor: string
  onChipClick: (messageId: string) => void
}

// Individual chip row — scales up when scrolled to center of the list
function ChipRow({
  chip,
  glowColor,
  scrollContainerRef,
  onSelect,
}: {
  chip: ConversationChip
  glowColor: string
  scrollContainerRef: React.RefObject<HTMLDivElement>
  onSelect: (id: string) => void
}) {
  const rowRef = useRef<HTMLButtonElement>(null)
  const [hovered, setHovered] = useState(false)
  const [scrollScale, setScrollScale] = useState(0.94)

  const updateScale = useCallback(() => {
    const container = scrollContainerRef.current
    const row = rowRef.current
    if (!container || !row) return
    const cRect = container.getBoundingClientRect()
    const rRect = row.getBoundingClientRect()
    const dist = Math.abs((cRect.top + cRect.height / 2) - (rRect.top + rRect.height / 2))
    const t = Math.min(dist / (cRect.height / 2), 1)
    setScrollScale(0.94 + (1 - t) * 0.06)   // 0.94 → 1.00 based on scroll position
  }, [scrollContainerRef])

  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    updateScale()
    container.addEventListener('scroll', updateScale, { passive: true })
    return () => container.removeEventListener('scroll', updateScale)
  }, [updateScale, scrollContainerRef])

  // Hover wins: scale up to 1.06 and brighten text
  const finalScale = hovered ? 1.06 : scrollScale
  const finalColor = hovered ? 'rgba(255,255,255,0.95)' : `rgba(255,255,255,${0.35 + (scrollScale - 0.94) / 0.06 * 0.45})`

  return (
    <motion.button
      ref={rowRef}
      onClick={() => onSelect(chip.messageId)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="w-full text-left px-2.5 py-2 text-[11px] font-medium origin-left"
      animate={{ scale: finalScale }}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      style={{
        background: hovered ? `${glowColor}14` : 'transparent',
        border: `1px solid ${hovered ? `${glowColor}45` : 'transparent'}`,
        color: finalColor,
        borderRadius: 0,
      }}
    >
      <span className="truncate leading-snug block">{chip.label}</span>
    </motion.button>
  )
}

export function ConversationChips({
  chips,
  glowColor,
  onChipClick,
}: ConversationChipsProps) {
  const [isOpen, setIsOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return
    function onOutside(e: MouseEvent) {
      if (
        panelRef.current?.contains(e.target as Node) ||
        triggerRef.current?.contains(e.target as Node)
      ) return
      setIsOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [isOpen])

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setIsOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen])

  if (chips.length === 0) return null

  function handleSelect(messageId: string) {
    setIsOpen(false)
    onChipClick(messageId)
  }

  return (
    <div className="relative flex-shrink-0">
      {/* ── Compact trigger — AlignJustify lines in brand/glow color ── */}
      <motion.button
        ref={triggerRef}
        onClick={() => setIsOpen(o => !o)}
        className="flex items-center gap-2 px-3 py-2 mb-1 transition-all duration-150 flex-shrink-0"
        style={{
          color: isOpen ? glowColor : `${glowColor}70`,
          background: isOpen ? `${glowColor}14` : `${glowColor}08`,
          border: `1px solid ${isOpen ? `${glowColor}55` : `${glowColor}25`}`,
          borderRadius: 0,
        }}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        title={`Conversation history (${chips.length})`}
      >
        <AlignJustify size={16} style={{ color: isOpen ? glowColor : `${glowColor}80` }} />
        <span
          className="text-[11px] font-mono leading-none"
          style={{ color: isOpen ? glowColor : `${glowColor}70` }}
        >
          {chips.length}
        </span>
      </motion.button>

      {/* ── Overlay panel ───────────────────────────────────────── */}
      <AnimatePresence>
        {isOpen && (
          <>
            {/* Dark blur scrim */}
            <motion.div
              key="scrim"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 z-40 pointer-events-none"
              style={{
                backdropFilter: 'blur(10px)',
                WebkitBackdropFilter: 'blur(10px)',
                background: 'rgba(4,4,10,0.72)',
              }}
            />

            {/* Panel */}
            <motion.div
              ref={panelRef}
              key="panel"
              initial={{ opacity: 0, y: 12, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.96 }}
              transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
              className="absolute bottom-full right-0 mb-3 z-50 w-52"
              style={{ transformOrigin: 'bottom right' }}
            >
              {/* Blur layer — no overflow:hidden here, that kills backdrop-filter in Chromium */}
              <div
                style={{
                  backdropFilter: 'blur(20px) saturate(1.6)',
                  WebkitBackdropFilter: 'blur(20px) saturate(1.6)',
                  background: `linear-gradient(160deg, rgba(16,16,28,0.96) 0%, rgba(10,10,18,0.93) 60%, ${glowColor}0d 100%)`,
                  border: `1px solid ${glowColor}40`,
                  boxShadow: `0 -8px 40px rgba(0,0,0,0.7), 0 0 0 0.5px ${glowColor}25, inset 0 1px 0 ${glowColor}20`,
                  borderRadius: 0,
                }}
              >
                {/* Clipping wrapper — separate from blur layer so they don't conflict */}
                <div className="overflow-hidden relative">
                  {/* Top fade */}
                  <div
                    className="absolute top-0 left-0 right-0 h-5 pointer-events-none z-10"
                    style={{ background: `linear-gradient(to bottom, rgba(8,8,12,0.85), transparent)` }}
                  />

                  <div
                    ref={scrollRef}
                    className="overflow-y-auto"
                    style={{
                      maxHeight: '105px',
                      scrollbarWidth: 'none',
                    }}
                  >
                    <div className="px-1.5 py-2 flex flex-col gap-0.5">
                      {chips.map((chip) => (
                        <ChipRow
                          key={chip.messageId}
                          chip={chip}
                          glowColor={glowColor}
                          scrollContainerRef={scrollRef as React.RefObject<HTMLDivElement>}
                          onSelect={handleSelect}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
