'use client'

import { useRef, useState, useCallback, useEffect } from 'react'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { CardContentRenderer } from './CardContentRenderer'
import { GripVertical, X, Minimize2 } from 'lucide-react'

interface FloatingPanelProps {
  cardId: string
  tabId: string
  initialX?: number
  initialY?: number
  onClose: () => void
}

export function FloatingPanel({ cardId, tabId, initialX = 100, initialY = 100, onClose }: FloatingPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: initialX, y: initialY })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const posStart = useRef({ x: 0, y: 0 })

  const tab = useWorkspaceStore((state) => state.tabs.find((t) => t.id === tabId))
  const { archiveCard } = useWorkspaceStore()
  const glowColor = '#60a5fa'

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.fp-close') || (e.target as HTMLElement).closest('.fp-minimize')) return
    setIsDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    posStart.current = { ...pos }
    e.preventDefault()
  }, [pos])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging) return
    const dx = e.clientX - dragStart.current.x
    const dy = e.clientY - dragStart.current.y
    setPos({
      x: Math.max(0, Math.min(window.innerWidth - 200, posStart.current.x + dx)),
      y: Math.max(0, Math.min(window.innerHeight - 100, posStart.current.y + dy)),
    })
  }, [isDragging])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  // Attach global mouse listeners while dragging
  useEffect(() => {
    if (!isDragging) return
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, handleMouseMove, handleMouseUp])

  const handleClose = () => {
    archiveCard(cardId)
    onClose()
  }

  if (!tab) return null

  return (
    <div
      ref={panelRef}
      className="fixed z-50 rounded-lg overflow-hidden flex flex-col"
      style={{
        left: pos.x,
        top: pos.y,
        width: 380,
        height: 300,
        background: 'linear-gradient(180deg, rgba(14,15,26,0.95) 0%, rgba(8,9,18,0.95) 100%)',
        border: '1px solid rgba(255,255,255,0.08)',
        boxShadow: '0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.04)',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Draggable header */}
      <div
        className="shrink-0 flex items-center justify-between px-2.5 py-1.5 select-none"
        style={{
          background: 'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          cursor: isDragging ? 'grabbing' : 'grab',
        }}
        onMouseDown={handleMouseDown}
      >
        <div className="flex items-center gap-1.5 overflow-hidden min-w-0">
          <GripVertical size={10} className="text-white/20 shrink-0" />
          <span className="text-[10px] font-medium truncate" style={{ color: 'rgba(255,255,255,0.75)' }}>
            {tab.label}
          </span>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            onClick={handleClose}
            className="fp-close p-0.5 rounded transition-colors hover:bg-white/5"
            style={{ color: 'rgba(255,255,255,0.3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(239,68,68,0.7)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
            title="Close (archive)"
          >
            <X size={10} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-hidden p-2">
        <CardContentRenderer cardId={cardId} tabId={tabId} viewMode="preview" />
      </div>
    </div>
  )
}
