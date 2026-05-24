'use client'

import { useState, useRef, useCallback } from 'react'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { FileText, Folder, Plus, X, Upload, FolderOpen } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

export type PickedItem = {
  id: string
  label: string
  type: 'file' | 'folder' | 'document'
  path: string
  isVirtual: boolean
  content?: string
}

interface FilePickerModalProps {
  isOpen: boolean
  onClose: () => void
  onPick: (items: PickedItem[]) => void
}

// Virtual workspace items (in-memory documents)
const VIRTUAL_ITEMS: PickedItem[] = [
  { id: 'virt-arch', label: 'architecture.md', type: 'document', path: '/workspace/architecture.md', isVirtual: true },
  { id: 'virt-spec', label: 'spec.md', type: 'document', path: '/workspace/spec.md', isVirtual: true },
  { id: 'virt-notes', label: 'scratch.md', type: 'document', path: '/workspace/scratch.md', isVirtual: true },
]

export function FilePickerModal({ isOpen, onClose, onPick }: FilePickerModalProps) {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || '#60a5fa'
  const [activeTab, setActiveTab] = useState<'local' | 'virtual'>('local')
  const [newDocName, setNewDocName] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dirInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    const items: PickedItem[] = files.map((f) => ({
      id: `file-${Date.now()}-${f.name}`,
      label: f.name,
      type: f.name.endsWith('/') ? 'folder' : 'file',
      path: f.webkitRelativePath || f.name,
      isVirtual: false,
    }))
    if (items.length > 0) {
      onPick(items)
      onClose()
    }
    e.target.value = ''
  }, [onPick, onClose])

  const handleDirSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    // Group by directory
    const dirs = new Map<string, string[]>()
    files.forEach((f) => {
      const dir = f.webkitRelativePath.split('/')[0]
      if (!dirs.has(dir)) dirs.set(dir, [])
      dirs.get(dir)!.push(f.name)
    })

    const items: PickedItem[] = Array.from(dirs.entries()).map(([dir, names]) => ({
      id: `folder-${Date.now()}-${dir}`,
      label: dir,
      type: 'folder',
      path: `./${dir}`,
      isVirtual: false,
    }))

    if (items.length > 0) {
      onPick(items)
      onClose()
    }
    e.target.value = ''
  }, [onPick, onClose])

  const handleCreateVirtual = () => {
    const name = newDocName.trim() || 'untitled.md'
    const id = `virt-${Date.now()}`
    onPick([{
      id,
      label: name,
      type: 'document',
      path: `/workspace/${name}`,
      isVirtual: true,
      content: `# ${name}\n\n`,
    }])
    setNewDocName('')
    onClose()
  }

  const pickVirtual = (item: PickedItem) => {
    onPick([item])
    onClose()
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="w-[480px] max-w-[90vw] rounded-xl overflow-hidden"
            style={{
              background: 'linear-gradient(180deg, #0f1020 0%, #0a0b18 100%)',
              border: `1px solid ${glowColor}20`,
              boxShadow: `0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px ${glowColor}08`,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: `1px solid ${glowColor}10` }}>
              <span className="text-xs font-semibold tracking-wide" style={{ color: `${glowColor}90` }}>
                Add Tab
              </span>
              <button
                onClick={onClose}
                className="p-1 rounded-md transition-colors hover:bg-white/5"
                style={{ color: 'rgba(255,255,255,0.3)' }}
              >
                <X size={14} />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex px-4 pt-3 gap-4">
              <button
                onClick={() => setActiveTab('local')}
                className="text-[11px] pb-1 transition-colors"
                style={{
                  color: activeTab === 'local' ? `${glowColor}90` : 'rgba(255,255,255,0.3)',
                  borderBottom: activeTab === 'local' ? `2px solid ${glowColor}60` : '2px solid transparent',
                }}
              >
                Local Files
              </button>
              <button
                onClick={() => setActiveTab('virtual')}
                className="text-[11px] pb-1 transition-colors"
                style={{
                  color: activeTab === 'virtual' ? `${glowColor}90` : 'rgba(255,255,255,0.3)',
                  borderBottom: activeTab === 'virtual' ? `2px solid ${glowColor}60` : '2px solid transparent',
                }}
              >
                Virtual Workspace
              </button>
            </div>

            {/* Content */}
            <div className="p-4 min-h-[180px]">
              {activeTab === 'local' ? (
                <div className="flex flex-col gap-3">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  <input
                    ref={dirInputRef}
                    type="file"
                    className="hidden"
                    onChange={handleDirSelect}
                    {...{ webkitdirectory: "", directory: "" } as any}
                  />
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 text-left"
                    style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: `1px solid ${glowColor}12`,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.06)'
                      e.currentTarget.style.borderColor = `${glowColor}25`
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
                      e.currentTarget.style.borderColor = `${glowColor}12`
                    }}
                  >
                    <Upload size={16} style={{ color: `${glowColor}70` }} />
                    <div>
                      <div className="text-[11px] font-medium" style={{ color: 'rgba(255,255,255,0.8)' }}>
                        Select Files
                      </div>
                      <div className="text-[9px]" style={{ color: 'rgba(255,255,255,0.3)' }}>
                        Pick one or more files from your computer
                      </div>
                    </div>
                  </button>
                  <button
                    onClick={() => dirInputRef.current?.click()}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 text-left"
                    style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: `1px solid ${glowColor}12`,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.06)'
                      e.currentTarget.style.borderColor = `${glowColor}25`
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
                      e.currentTarget.style.borderColor = `${glowColor}12`
                    }}
                  >
                    <FolderOpen size={16} style={{ color: `${glowColor}70` }} />
                    <div>
                      <div className="text-[11px] font-medium" style={{ color: 'rgba(255,255,255,0.8)' }}>
                        Open Folder
                      </div>
                      <div className="text-[9px]" style={{ color: 'rgba(255,255,255,0.3)' }}>
                        Browse a directory and import all files
                      </div>
                    </div>
                  </button>
                  <div className="text-[9px] px-1" style={{ color: 'rgba(255,255,255,0.2)' }}>
                    Tip: Backend file API not yet wired — selections are client-side only for now.
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  {/* Create new virtual doc */}
                  <div className="flex gap-2">
                    <input
                      value={newDocName}
                      onChange={(e) => setNewDocName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleCreateVirtual()}
                      placeholder="untitled.md"
                      className="flex-1 px-3 py-2 rounded-lg text-[11px] outline-none transition-colors"
                      style={{
                        background: 'rgba(255,255,255,0.04)',
                        border: `1px solid ${glowColor}15`,
                        color: 'rgba(255,255,255,0.8)',
                      }}
                    />
                    <button
                      onClick={handleCreateVirtual}
                      className="px-3 py-2 rounded-lg text-[11px] font-medium transition-colors"
                      style={{
                        background: `${glowColor}15`,
                        color: glowColor,
                        border: `1px solid ${glowColor}25`,
                      }}
                    >
                      <Plus size={14} />
                    </button>
                  </div>
                  {/* Existing virtual docs */}
                  <div className="flex flex-col gap-1">
                    {VIRTUAL_ITEMS.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => pickVirtual(item)}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-150 text-left"
                        style={{
                          background: 'rgba(255,255,255,0.02)',
                          border: '1px solid transparent',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                          e.currentTarget.style.borderColor = `${glowColor}15`
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'rgba(255,255,255,0.02)'
                          e.currentTarget.style.borderColor = 'transparent'
                        }}
                      >
                        <FileText size={12} style={{ color: `${glowColor}60` }} />
                        <span className="text-[11px]" style={{ color: 'rgba(255,255,255,0.7)' }}>
                          {item.label}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
