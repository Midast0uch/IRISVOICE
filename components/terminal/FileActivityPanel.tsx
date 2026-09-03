'use client'

import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FilePlus, FileEdit, FileX, Trash2 } from 'lucide-react'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useTerminal } from '@/contexts/TerminalContext'

const CHANGE_ICON = {
  create: { icon: FilePlus, color: '#68d391' },
  edit: { icon: FileEdit, color: '#f6e05e' },
  delete: { icon: FileX, color: '#fc8181' },
} as const

function relativePath(fullPath: string): string {
  // Strip common prefixes for display
  const idx = fullPath.lastIndexOf('IRISVOICE/')
  return idx >= 0 ? fullPath.slice(idx + 10) : fullPath.split(/[/\\]/).slice(-3).join('/')
}

function timeAgo(ts: number): string {
  const diff = Math.floor((Date.now() - ts) / 1000)
  if (diff < 5) return 'now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

const ACCENT_FALLBACK = '#60a5fa'

export function FileActivityPanel() {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || ACCENT_FALLBACK
  const { fileActivity, isFileActivityOpen, clearFileActivity } = useTerminal()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to top (newest) when new entries arrive
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [fileActivity.length])

  return (
    <AnimatePresence>
      {isFileActivityOpen && (
        <motion.div
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 200, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: 'easeInOut' }}
          className="shrink-0 flex flex-col overflow-hidden"
          style={{
            borderLeft: `1px solid ${glowColor}20`,
            background: 'rgba(10, 10, 15, 0.4)',
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-2 py-1.5 shrink-0"
            style={{ borderBottom: `1px solid ${glowColor}15` }}
          >
            <span className="text-[10px] font-medium text-white/60 uppercase tracking-wider">
              File Activity
            </span>
            {fileActivity.length > 0 && (
              <button
                onClick={clearFileActivity}
                className="p-0.5 rounded hover:bg-white/10 transition-colors"
                title="Clear activity"
              >
                <Trash2 size={10} style={{ color: 'rgba(255,255,255,0.4)' }} />
              </button>
            )}
          </div>

          {/* Activity list */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
            {fileActivity.length === 0 ? (
              <div className="px-2 py-4 text-center">
                <span className="text-[10px] text-white/30">No file changes yet</span>
              </div>
            ) : (
              fileActivity.map((entry, i) => {
                const cfg = CHANGE_ICON[entry.change] ?? CHANGE_ICON.edit
                const Icon = cfg.icon
                return (
                  <div
                    key={`${entry.path}-${entry.timestamp}-${i}`}
                    className="flex items-start gap-1.5 px-2 py-1 hover:bg-white/5 transition-colors"
                  >
                    <Icon size={11} style={{ color: cfg.color, marginTop: 2, flexShrink: 0 }} />
                    <div className="min-w-0 flex-1">
                      <div
                        className="text-[10px] font-mono truncate"
                        style={{ color: 'rgba(255,255,255,0.7)' }}
                        title={entry.path}
                      >
                        {relativePath(entry.path)}
                      </div>
                      <div className="text-[9px] text-white/30">
                        {timeAgo(entry.timestamp)}
                      </div>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
