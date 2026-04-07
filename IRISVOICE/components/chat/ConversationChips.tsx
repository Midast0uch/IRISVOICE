'use client'

import { useRef, useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence, useMotionValue, useTransform, useSpring } from 'framer-motion'
import { AlignJustify, X } from 'lucide-react'
import type { ConversationChip } from '@/types/iris'

interface ConversationChipsProps {
  chips: ConversationChip[]
  glowColor: string
  onChipClick: (messageId: string) => void
}

// Individual chip row — scales up when scrolled to center of the list
function ChipRow({
  chip,
  index,
  glowColor,
  scrollContainerRef,
  onSelect,
}: {
  chip: ConversationChip
  index: number
  glowColor: string
  scrollContainerRef: React.RefObject<HTMLDivElement>
  onSelect: (id: string) => void
}) {
  const rowRef = useRef<HTMLButtonElement>(null)
  const [scale, setScale] = useState(0.94)
  const [brightness, setBrightness] = useState(0.45)

  const updateScale = useCallback(() => {
    const container = scrollContainerRef.current
    const row = rowRef.current
    if (!container || !row) return

    const cRect = container.getBoundingClientRect()
    const rRect = row.getBoundingClientRect()

    const containerMid = cRect.top + cRect.height / 2
    const rowMid = rRect.top + rRect.height / 2
    const dist = Math.abs(containerMid - rowMid)
    const maxDist = cRect.height / 2

    // 0 = centered, 1 = at edge
    const t = Math.min(dist / maxDist, 1)
    setScale(0.94 + (1 - t) * 0.1)          // 0.94 → 1.04
    setBrightness(0.35 + (1 - t) * 0.55)    // 0.35 → 0.90
  }, [scrollContainerRef])

  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    updateScale()
    container.addEventListener('scroll', updateScale, { passive: true })
    return () => container.removeEventListener('scroll', updateScale)
  }, [updateScale, scrollContainerRef])

  return (
    <motion.button
      ref={rowRef}
      onClick={() => onSelect(chip.messageId)}
      className="w-full text-left px-2.5 py-2 text-[11px] font-medium
                 flex items-start gap-2.5 origin-left"
      animate={{ scale, opacity: 0.4 + (scale - 0.94) / 0.10 * 0.6 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      style={{
        background: 'transparent',
        border: `1px solid transparent`,
        color: `rgba(255,255,255,${brightness})`,
        borderRadius: 0,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = `${glowColor}12`
        e.currentTarget.style.borderColor = `${glowColor}40`
        e.currentTarget.style.color = 'rgba(255,255,255,0.92)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.borderColor = 'transparent'
        e.currentTarget.style.color = `rgba(255,255,255,${brightness})`
      }}
    >
      <span
        className="shrink-0 text-[8px] font-mono mt-0.5 w-3.5 text-right tabular-nums"
        style={{ color: `${glowColor}50` }}
      >
        {index + 1}
      </span>
      <span className="truncate leading-snug">{chip.label}</span>
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
        className="flex items-center gap-1 px-2 py-1.5 mb-2 transition-all duration-150 flex-shrink-0"
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
        <AlignJustify size={13} style={{ color: isOpen ? glowColor : `${glowColor}80` }} />
        <span
          className="text-[9px] font-mono leading-none"
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
                backdropFilter: 'blur(3px)',
                WebkitBackdropFilter: 'blur(3px)',
                background: 'rgba(4,4,8,0.45)',
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
              <div
                className="overflow-hidden"
                style={{
                  backdropFilter: 'blur(20px) saturate(1.5)',
                  WebkitBackdropFilter: 'blur(20px) saturate(1.5)',
                  background: 'rgba(8, 8, 12, 0.82)',
                  border: `1px solid ${glowColor}28`,
                  boxShadow: `0 -8px 40px rgba(0,0,0,0.6), 0 0 0 0.5px ${glowColor}15, inset 0 1px 0 ${glowColor}12`,
                  borderRadius: 0,
                }}
              >
                {/* Header — icon + close only */}
                <div
                  className="flex items-center justify-between px-2.5 py-2 border-b"
                  style={{ borderColor: `${glowColor}18` }}
                >
                  <AlignJustify size={11} style={{ color: glowColor }} />
                  <button
                    onClick={() => setIsOpen(false)}
                    className="p-0.5 transition-opacity opacity-40 hover:opacity-100"
                    style={{ color: 'rgba(255,255,255,0.7)' }}
                  >
                    <X size={11} />
                  </button>
                </div>

                {/* Scrollable list — items scale based on distance from center */}
                <div className="relative">
                  {/* Top fade */}
                  <div
                    className="absolute top-0 left-0 right-0 h-5 pointer-events-none z-10"
                    style={{ background: `linear-gradient(to bottom, rgba(8,8,12,0.95), transparent)` }}
                  />

                  <div
                    ref={scrollRef}
                    className="overflow-y-auto"
                    style={{
                      maxHeight: '220px',
                      scrollbarWidth: 'thin',
                      scrollbarColor: `${glowColor}25 transparent`,
                    }}
                  >
                    <div className="px-1.5 py-3 flex flex-col gap-0.5">
                      {chips.map((chip, i) => (
                        <ChipRow
                          key={chip.messageId}
                          chip={chip}
                          index={i}
                          glowColor={glowColor}
                          scrollContainerRef={scrollRef as React.RefObject<HTMLDivElement>}
                          onSelect={handleSelect}
                        />
                      ))}
                    </div>
                  </div>

                  {/* Bottom fade */}
                  <div
                    className="absolute bottom-0 left-0 right-0 h-5 pointer-events-none"
                    style={{ background: `linear-gradient(to top, rgba(8,8,12,0.95), transparent)` }}
                  />
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
