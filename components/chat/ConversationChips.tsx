'use client'

import { useRef, useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { AlignJustify } from 'lucide-react'
import type { ConversationChip } from '@/types/iris'

interface ConversationChipsProps {
  chips: ConversationChip[]
  glowColor: string
  onChipClick: (messageId: string) => void
  containerRef?: React.RefObject<HTMLElement | null>
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
    setScrollScale(0.94 + (1 - t) * 0.06)
  }, [scrollContainerRef])

  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    updateScale()
    container.addEventListener('scroll', updateScale, { passive: true })
    return () => container.removeEventListener('scroll', updateScale)
  }, [updateScale, scrollContainerRef])

  const finalScale = hovered ? 1.06 : scrollScale
  const finalColor = hovered
    ? 'rgba(255,255,255,0.95)'
    : `rgba(255,255,255,${0.35 + (scrollScale - 0.94) / 0.06 * 0.45})`

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
  containerRef,
}: ConversationChipsProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [hovered, setHovered] = useState(false)
  // Refs — set synchronously before setIsOpen so the re-render reads correct values
  const triggerRectRef = useRef<DOMRect | null>(null)
  const containerRectRef = useRef<DOMRect | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Only portal after hydration
  useEffect(() => { setMounted(true) }, [])

  // Capture rects synchronously then toggle — guarantees values exist on first render
  function handleToggle() {
    if (!isOpen) {
      triggerRectRef.current = triggerRef.current?.getBoundingClientRect() ?? null
      containerRectRef.current = containerRef?.current?.getBoundingClientRect() ?? null
    }
    setIsOpen(o => !o)
  }

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

  const hasChips = chips.length > 0

  function handleSelect(messageId: string) {
    setIsOpen(false)
    onChipClick(messageId)
  }

  // Panel anchored to trigger via viewport coords — escapes any CSS transform
  const tr = triggerRectRef.current
  const cr = containerRectRef.current
  const panelRight = tr ? window.innerWidth - tr.right + 48 : 0
  const panelBottom = tr ? window.innerHeight - tr.top + 8 : 0

  const overlay = (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Panel — fixed at captured trigger coords */}
          <motion.div
            ref={panelRef}
            key="panel"
            initial={{ opacity: 0, y: 12, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.96 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            style={{
              position: 'fixed',
              bottom: panelBottom,
              right: panelRight,
              width: '208px',
              zIndex: 9050,
              transformOrigin: 'bottom right',
            }}
          >
            <div
              style={{
                backdropFilter: 'blur(8px)',
                WebkitBackdropFilter: 'blur(8px)',
                background: `linear-gradient(160deg, rgba(14,14,24,0.96) 0%, rgba(8,8,16,0.95) 60%, ${glowColor}0a 100%)`,
                border: `1px solid ${glowColor}35`,
                boxShadow: `0 -4px 20px rgba(0,0,0,0.6), 0 0 0 0.5px ${glowColor}20`,
                borderRadius: '6px',
              }}
            >
              <div className="overflow-hidden relative" style={{ borderRadius: '6px' }}>
                {/* Top fade */}
                <div
                  className="absolute top-0 left-0 right-0 h-5 pointer-events-none z-10"
                  style={{ background: `linear-gradient(to bottom, rgba(8,8,12,0.85), transparent)` }}
                />
                <div
                  ref={scrollRef}
                  className="overflow-y-auto"
                  style={{ maxHeight: '105px', scrollbarWidth: 'none' }}
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
  )

  return (
    <div className="relative flex-shrink-0">
      {/* Trigger button — minimal, no container chrome */}
      <motion.button
        ref={triggerRef}
        onClick={hasChips ? handleToggle : undefined}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        className="relative flex items-center px-1 py-1 transition-all duration-150 flex-shrink-0"
        style={{
          color: isOpen ? glowColor : hasChips ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.25)',
          background: 'transparent',
          border: 'none',
          cursor: hasChips ? 'pointer' : 'default',
          opacity: hasChips ? 1 : 0.5,
        }}
        whileHover={hasChips ? { scale: 1.05 } : {}}
        whileTap={hasChips ? { scale: 0.95 } : {}}
        title={hasChips ? `Conversation history (${chips.length})` : 'No conversation history yet'}
      >
        <AlignJustify size={13} />
      </motion.button>

      {/* Hover pill — shows chip count, positioned to the right of the icon */}
      {hasChips && hovered && (
        <span
          className="absolute top-1/2 -translate-y-1/2 left-full ml-1 text-[8px] font-semibold tracking-wide whitespace-nowrap px-1.5 py-px pointer-events-none z-50"
          style={{
            background: isOpen ? `${glowColor}25` : 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
            border: `1px solid ${isOpen ? `${glowColor}50` : `${glowColor}15`}`,
            borderRadius: '9999px',
            color: isOpen ? glowColor : 'rgba(255,255,255,0.7)',
            boxShadow: isOpen ? `0 0 8px ${glowColor}30` : 'none',
          }}
        >
          {chips.length}
        </span>
      )}

      {/* Portal: renders outside any CSS transform at document.body */}
      {mounted && createPortal(overlay, document.body)}
    </div>
  )
}
