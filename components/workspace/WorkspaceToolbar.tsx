'use client'

import { useWorkspaceStore } from '@/stores/workspaceStore'
import { Focus, Undo2, Redo2, Camera } from 'lucide-react'

export function WorkspaceToolbar() {
  const { isFocusMode, toggleFocusMode } = useWorkspaceStore()

  return (
    <div className="shrink-0 flex items-center justify-between px-3 py-1.5 border-t border-white/5">
      <div className="flex items-center gap-2">
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
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-white/20">Workspace v1</span>
      </div>
    </div>
  )
}
