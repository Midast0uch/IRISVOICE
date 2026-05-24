'use client'

import { useState } from 'react'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { RotateCcw, Archive } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

export function ArchiveDock() {
  const { archived, unarchiveCard, tabs } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)

  const isEmpty = archived.length === 0

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
              archived.map((item) => {
                const isHovered = hoveredId === item.cardId
                const tab = tabs.find((t) => t.id === item.tabId)
                const tabLabel = tab?.label || item.tabId.slice(0, 12)

                return (
                  <button
                    key={item.cardId}
                    onClick={() => unarchiveCard(item.cardId)}
                    onMouseEnter={() => setHoveredId(item.cardId)}
                    onMouseLeave={() => setHoveredId(null)}
                    className="flex items-center gap-1.5 px-2 py-1 rounded-md transition-all duration-150"
                    style={{
                      background: isHovered ? `${glowColor}15` : 'rgba(255,255,255,0.03)',
                      border: isHovered ? `1px solid ${glowColor}30` : '1px solid rgba(255,255,255,0.06)',
                    }}
                    title={`Restore: ${tabLabel}`}
                  >
                    <RotateCcw
                      size={11}
                      style={{
                        color: isHovered ? glowColor : 'rgba(255,255,255,0.35)',
                        transition: 'color 0.15s',
                      }}
                    />
                    <span
                      className="text-[9px] truncate max-w-[80px]"
                      style={{
                        color: isHovered ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.45)',
                        transition: 'color 0.15s',
                      }}
                    >
                      {tabLabel}
                    </span>
                  </button>
                )
              })
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
