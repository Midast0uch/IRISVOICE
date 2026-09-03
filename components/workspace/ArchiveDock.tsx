'use client'

import { useState, useRef } from 'react'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { RotateCcw, Archive, FileText, Folder, MessageSquare, ScrollText, Terminal } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

const TAB_TYPE_ICONS: Record<string, React.ComponentType<{ size?: number; style?: React.CSSProperties }>> = {
  file: FileText,
  folder: Folder,
  conversation: MessageSquare,
  document: ScrollText,
  terminal: Terminal,
}

interface ArchiveDockProps {
  dragLocked?: boolean
}

export function ArchiveDock({ dragLocked = false }: ArchiveDockProps) {
  const { archived, unarchiveCard, tabs } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const dockRef = useRef<HTMLDivElement>(null)

  const isEmpty = archived.length === 0

  // macOS-style magnification: hovered = 1.6x, neighbors = 1.1x, others = 1.0x
  function getScale(index: number): number {
    if (dragLocked || hoveredIndex === null) return 1
    const dist = Math.abs(index - hoveredIndex)
    if (dist === 0) return 1.6
    if (dist === 1) return 1.1
    return 1
  }

  return (
    <div
      className="shrink-0 relative"
      onMouseEnter={() => isEmpty && setIsExpanded(true)}
      onMouseLeave={() => isEmpty && setIsExpanded(false)}
    >
      {/* Collapsed glow line when empty */}
      {isEmpty && !isExpanded && (
        <div
          className="h-[2px] w-full cursor-pointer"
          style={{
            background: `linear-gradient(90deg, transparent, ${glowColor}20, transparent)`,
          }}
        />
      )}

      <AnimatePresence>
        {(!isEmpty || isExpanded) && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            ref={dockRef}
            className="flex items-center gap-2 px-3 py-2 overflow-x-auto overflow-y-hidden"
            style={{
              background: 'linear-gradient(180deg, rgba(10,11,22,0.5) 0%, rgba(6,7,14,0.3) 100%)',
              borderBottom: `1px solid ${glowColor}10`,
            }}
          >
            <Archive size={10} style={{ color: `${glowColor}50` }} />
            <span className="text-[9px] font-medium tracking-wide uppercase mr-1" style={{ color: `${glowColor}60` }}>
              Archive
            </span>
            {isEmpty ? (
              <span className="text-[9px] text-white/20 italic">Empty</span>
            ) : (
              archived.map((item, index) => {
                const scale = getScale(index)
                const isHovered = hoveredIndex === index
                const tab = tabs.find((t) => t.id === item.tabId)
                const tabLabel = tab?.label || item.tabId.slice(0, 12)
                const Icon = TAB_TYPE_ICONS[tab?.type || 'file'] || FileText
                const iconColor = isHovered ? glowColor : 'rgba(255,255,255,0.35)'

                return (
                  <motion.button
                    key={item.cardId}
                    onClick={() => unarchiveCard(item.cardId)}
                    onMouseEnter={() => setHoveredIndex(index)}
                    onMouseLeave={() => setHoveredIndex(null)}
                    animate={{ scale }}
                    transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                    className="flex flex-col items-center gap-0.5 px-1.5 py-1 rounded-md relative"
                    style={{
                      background: isHovered ? `${glowColor}15` : 'rgba(255,255,255,0.03)',
                      border: isHovered ? `1px solid ${glowColor}30` : '1px solid rgba(255,255,255,0.06)',
                      transformOrigin: 'bottom center',
                      cursor: dragLocked ? 'default' : 'pointer',
                      opacity: dragLocked ? 0.6 : 1,
                    }}
                    title={`Restore: ${tabLabel}`}
                  >
                    <Icon size={14} style={{ color: iconColor, transition: 'color 0.15s' }} />
                    <span
                      className="text-[8px] truncate max-w-[60px]"
                      style={{
                        color: isHovered ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.45)',
                        transition: 'color 0.15s',
                      }}
                    >
                      {tabLabel}
                    </span>
                    {/* Tooltip on hover */}
                    {isHovered && !dragLocked && (
                      <motion.div
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="absolute -top-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-[9px] whitespace-nowrap pointer-events-none"
                        style={{
                          background: 'rgba(14,14,24,0.9)',
                          border: `1px solid ${glowColor}20`,
                          color: 'rgba(255,255,255,0.8)',
                        }}
                      >
                        {tabLabel}
                      </motion.div>
                    )}
                  </motion.button>
                )
              })
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
