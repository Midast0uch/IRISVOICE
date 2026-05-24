'use client'

import { useWorkspaceStore, useTemporalStore, useCanUndo, useCanRedo } from '@/stores/workspaceStore'
import { Xur } from '@/components/Xur'
import { Focus, Undo2, Redo2, Camera, Save, RotateCcw } from 'lucide-react'

export function WorkspaceToolbar() {
  const { isFocusMode, toggleFocusMode, takeSnapshot, restoreSnapshot, isProcessing } = useWorkspaceStore()
  const temporal = useTemporalStore()
  const canUndo = useCanUndo()
  const canRedo = useCanRedo()

  return (
    <div className="shrink-0 flex items-center justify-between px-3 py-1.5 border-t border-white/5">
      <div className="flex items-center gap-2">
        {/* Focus Mode toggle */}
        <button
          onClick={toggleFocusMode}
          className={`
            flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors
            ${isFocusMode ? 'bg-white/10 text-white' : 'text-white/30 hover:text-white/60'}
          `}
        >
          <Focus size={10} />
          <span>Focus</span>
        </button>

        {/* Divider */}
        <div className="w-px h-3 bg-white/10" />

        {/* Global Undo */}
        <button
          onClick={() => temporal?.undo()}
          disabled={!canUndo}
          title="Undo"
          className={`
            flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors
            ${canUndo ? 'text-white/40 hover:text-white/70 hover:bg-white/5' : 'text-white/10 cursor-not-allowed'}
          `}
        >
          <Undo2 size={10} />
        </button>

        {/* Global Redo */}
        <button
          onClick={() => temporal?.redo()}
          disabled={!canRedo}
          title="Redo"
          className={`
            flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors
            ${canRedo ? 'text-white/40 hover:text-white/70 hover:bg-white/5' : 'text-white/10 cursor-not-allowed'}
          `}
        >
          <Redo2 size={10} />
        </button>

        {/* Divider */}
        <div className="w-px h-3 bg-white/10" />

        {/* Snapshot */}
        <button
          onClick={takeSnapshot}
          title="Save snapshot"
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
        >
          <Camera size={10} />
          <span>Snap</span>
        </button>

        {/* Restore Snapshot */}
        <button
          onClick={restoreSnapshot}
          title="Restore snapshot"
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
        >
          <RotateCcw size={10} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        {/* Xur workspace operation spinner */}
        {isProcessing && (
          <div style={{ color: '#60a5fa' }}>
            <Xur size={16} />
          </div>
        )}
        <span className="text-[9px] text-white/20">Workspace v1</span>
      </div>
    </div>
  )
}
