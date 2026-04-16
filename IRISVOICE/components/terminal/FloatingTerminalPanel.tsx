'use client'

import { useRef, useCallback } from 'react'
import { motion, AnimatePresence, useDragControls } from 'framer-motion'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useTerminal } from '@/contexts/TerminalContext'
import { useFloatingPanel } from '@/hooks/useFloatingPanel'
import { TerminalHeaderBar } from './TerminalHeaderBar'
import { FileActivityPanel } from './FileActivityPanel'
import { TERMINAL_FLOATING_ID } from './TerminalWidget'

const ACCENT_FALLBACK = '#60a5fa'

export function FloatingTerminalPanel() {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || ACCENT_FALLBACK
  const { isFloating } = useTerminal()
  const { position, size, onDragEnd, onResize } = useFloatingPanel()
  const dragControls = useDragControls()
  const resizeStartRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null)

  const handleResizePointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    resizeStartRef.current = { x: e.clientX, y: e.clientY, w: size.width, h: size.height }

    const onMove = (ev: PointerEvent) => {
      if (!resizeStartRef.current) return
      const dw = ev.clientX - resizeStartRef.current.x
      const dh = ev.clientY - resizeStartRef.current.y
      onResize(
        resizeStartRef.current.w + dw - size.width,
        resizeStartRef.current.h + dh - size.height
      )
    }

    const onUp = () => {
      resizeStartRef.current = null
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
    }

    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
  }, [size.width, size.height, onResize])

  return (
    <AnimatePresence>
      {isFloating && (
        <div
          className="fixed inset-0 pointer-events-none"
          style={{ zIndex: 40 }}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            drag
            dragControls={dragControls}
            dragMomentum={false}
            dragListener={false}
            dragConstraints={{ left: 0, top: 0, right: window.innerWidth - size.width, bottom: window.innerHeight - size.height }}
            onDragEnd={onDragEnd}
            style={{
              position: 'absolute',
              left: position.x,
              top: position.y,
              width: size.width,
              height: size.height,
              pointerEvents: 'auto',
            }}
            className="flex flex-col rounded-lg overflow-hidden shadow-2xl"
          >
            {/* Glass background */}
            <div
              className="absolute inset-0 rounded-lg"
              style={{
                background: 'rgba(10, 10, 15, 0.85)',
                backdropFilter: 'blur(20px)',
                border: `1px solid ${glowColor}30`,
                boxShadow: `0 0 30px ${glowColor}10, 0 25px 50px rgba(0,0,0,0.5)`,
              }}
            />

            {/* Content (relative, above glass bg) */}
            <div className="relative flex flex-col h-full">
              {/* Drag handle = header bar. onPointerDown starts drag on outer motion.div */}
              <div
                className="shrink-0"
                style={{ cursor: 'grab', touchAction: 'none' }}
                onPointerDown={(e) => dragControls.start(e)}
              >
                <TerminalHeaderBar />
              </div>

              {/* Terminal content area */}
              <div className="flex-1 flex min-h-0">
                {/* Portal target for xterm */}
                <div id={TERMINAL_FLOATING_ID} className="flex-1 flex flex-col min-h-0 min-w-0" />
                <FileActivityPanel />
              </div>
            </div>

            {/* Resize handle */}
            <div
              onPointerDown={handleResizePointerDown}
              className="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize"
              style={{
                background: `linear-gradient(135deg, transparent 50%, ${glowColor}40 50%)`,
                borderRadius: '0 0 8px 0',
              }}
            />
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
