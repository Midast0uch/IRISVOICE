'use client'

import { useState } from 'react'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { ArchiveRestore, Package } from 'lucide-react'

export function ArchiveDock() {
  const { archived, unarchiveCard } = useWorkspaceStore()
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  if (archived.length === 0) {
    return (
      <div className="shrink-0 flex items-center justify-center py-1 border-b border-white/5">
        <span className="text-[9px] text-white/15 italic">Archive empty</span>
      </div>
    )
  }

  return (
    <div className="shrink-0 flex items-center gap-1 px-3 py-1 border-b border-white/5 overflow-x-auto">
      {archived.map((item, index) => {
        const isHovered = hoveredIndex === index
        const scale = isHovered ? 1.6 : hoveredIndex !== null ? 0.9 : 1.0

        return (
          <button
            key={item.cardId}
            onClick={() => unarchiveCard(item.cardId)}
            onMouseEnter={() => setHoveredIndex(index)}
            onMouseLeave={() => setHoveredIndex(null)}
            className="flex flex-col items-center gap-0.5 p-1 rounded hover:bg-white/5 transition-all"
            style={{
              transform: `scale(${scale})`,
              transformOrigin: 'bottom center',
            }}
            title={`Unarchive: ${item.tabId}`}
          >
            <Package size={isHovered ? 20 : 14} className="text-white/30 transition-all" />
            <span className="text-[8px] text-white/30 truncate max-w-[48px]">
              {item.cardId.slice(0, 6)}
            </span>
          </button>
        )
      })}
    </div>
  )
}
