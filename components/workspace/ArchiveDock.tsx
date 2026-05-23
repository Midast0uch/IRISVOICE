'use client'

import { useState } from 'react'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { RotateCcw } from 'lucide-react'

export function ArchiveDock() {
  const { archived, unarchiveCard } = useWorkspaceStore()
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  if (archived.length === 0) {
    return (
      <div
        className="shrink-0 flex items-center justify-center py-2"
        style={{
          background: 'linear-gradient(180deg, rgba(255,255,255,0.015) 0%, transparent 100%)',
          borderBottom: `1px solid ${glowColor}10`,
        }}
      >
        <span className="text-[9px] text-white/20 italic">Archive empty</span>
      </div>
    )
  }

  return (
    <div
      className="shrink-0 flex items-center gap-2 px-3 py-2 overflow-x-auto"
      style={{
        background: 'linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%)',
        borderBottom: `1px solid ${glowColor}10`,
      }}
    >
      <span className="text-[9px] font-medium tracking-wide uppercase mr-1" style={{ color: `${glowColor}60` }}>
        Archive
      </span>
      {archived.map((item) => {
        const isHovered = hoveredId === item.cardId
        const tabLabel = item.tabId.slice(0, 12)

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
            title={`Restore: ${item.tabId}`}
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
      })}
    </div>
  )
}
