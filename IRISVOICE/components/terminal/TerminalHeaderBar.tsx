'use client'

import { useState } from 'react'
import { Monitor, Maximize2, Minimize2, FileText, Trash2 } from 'lucide-react'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useTerminal } from '@/contexts/TerminalContext'

interface TerminalHeaderBarProps {
  workdir?: string
  onClear?: () => void
}

const ACCENT_FALLBACK = '#60a5fa'

export function TerminalHeaderBar({ workdir, onClear }: TerminalHeaderBarProps) {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || ACCENT_FALLBACK
  const { isFloating, setIsFloating, isFileActivityOpen, toggleFileActivity } = useTerminal()

  return (
    <div
      className="flex items-center justify-between px-3 py-1.5 select-none shrink-0"
      style={{
        borderBottom: `1px solid ${glowColor}20`,
        background: 'rgba(10, 10, 15, 0.6)',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Left: label */}
      <div className="flex items-center gap-2">
        <Monitor size={14} style={{ color: glowColor }} />
        <span className="text-xs font-medium text-white/70">Terminal</span>
      </div>

      {/* Center: working directory */}
      {workdir && (
        <div className="flex-1 mx-4 text-center">
          <span
            className="text-[11px] font-mono truncate max-w-[300px] inline-block"
            style={{ color: `${glowColor}90` }}
            title={workdir}
          >
            {workdir}
          </span>
        </div>
      )}

      {/* Right: action buttons */}
      <div className="flex items-center gap-1">
        {/* File activity toggle */}
        <button
          onClick={toggleFileActivity}
          className="p-1 rounded hover:bg-white/10 transition-colors"
          title={isFileActivityOpen ? 'Hide file activity' : 'Show file activity'}
        >
          <FileText
            size={14}
            style={{ color: isFileActivityOpen ? glowColor : 'rgba(255,255,255,0.5)' }}
          />
        </button>

        {/* Clear terminal */}
        {onClear && (
          <button
            onClick={onClear}
            className="p-1 rounded hover:bg-white/10 transition-colors"
            title="Clear terminal"
          >
            <Trash2 size={14} style={{ color: 'rgba(255,255,255,0.5)' }} />
          </button>
        )}

        {/* Float / Dock toggle */}
        <button
          onClick={() => setIsFloating(!isFloating)}
          className="p-1 rounded hover:bg-white/10 transition-colors"
          title={isFloating ? 'Dock terminal' : 'Float terminal'}
        >
          {isFloating ? (
            <Minimize2 size={14} style={{ color: glowColor }} />
          ) : (
            <Maximize2 size={14} style={{ color: 'rgba(255,255,255,0.5)' }} />
          )}
        </button>
      </div>
    </div>
  )
}
