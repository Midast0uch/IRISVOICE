'use client'

import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { useWorkspaceStore, type ViewMode } from '@/stores/workspaceStore'
import { MindMapView } from './MindMapView'
import { CodePreviewPanel } from './CodePreviewPanel'
import { FileText, Map, Code, Eye, BookOpen } from 'lucide-react'

interface CardContentRendererProps {
  cardId: string
  tabId: string
  viewMode: ViewMode
}

function ViewModeToggle({
  current,
  options,
  onChange,
}: {
  current: ViewMode
  options: ViewMode[]
  onChange: (v: ViewMode) => void
}) {
  const icons: Record<ViewMode, typeof FileText> = {
    preview: FileText,
    mindmap: Map,
    rendered: BookOpen,
    raw: Code,
    code: Eye,
  }
  const labels: Record<ViewMode, string> = {
    preview: 'Preview',
    mindmap: 'Mind Map',
    rendered: 'Rendered',
    raw: 'Raw',
    code: 'Code',
  }
  return (
    <div className="flex items-center gap-0.5 mb-1">
      {options.map((mode) => {
        const Icon = icons[mode]
        const active = current === mode
        return (
          <button
            key={mode}
            onClick={() => onChange(mode)}
            className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] transition-colors ${
              active ? 'bg-white/10 text-white/70' : 'text-white/25 hover:text-white/45 hover:bg-white/5'
            }`}
          >
            <Icon size={8} />
            <span>{labels[mode]}</span>
          </button>
        )
      })}
    </div>
  )
}

export function CardContentRenderer({ cardId, tabId, viewMode }: CardContentRendererProps) {
  const tab = useWorkspaceStore((state) => state.tabs.find((t) => t.id === tabId))
  const { updateCardState, sections } = useWorkspaceStore()
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)

  // Find card to get its current viewMode from store (in case it changed)
  const card = sections.flatMap((s) => s.cards).find((c) => c.id === cardId)
  const currentViewMode = card?.viewMode || viewMode

  // Fetch file content on mount / tab change
  useEffect(() => {
    if (!tab || tab.type === 'conversation' || tab.type === 'terminal') return
    setLoading(true)
    fetch(`/api/file?path=${encodeURIComponent(tab.path)}`)
      .then((res) => res.text())
      .then((text) => setContent(text))
      .catch(() => setContent(`// Could not load: ${tab.path}`))
      .finally(() => setLoading(false))
  }, [tab])

  const setViewMode = (mode: ViewMode) => {
    useWorkspaceStore.setState((state) => ({
      sections: state.sections.map((s) => ({
        ...s,
        cards: s.cards.map((c) => (c.id === cardId ? { ...c, viewMode: mode } : c)),
      })),
    }))
  }

  if (!tab) return <div className="text-[10px] text-white/25">Tab not found</div>

  // Terminal tab
  if (tab.type === 'terminal') {
    return (
      <div className="text-[10px] text-white/30 font-mono">
        <span className="text-white/25">$ </span>
        <span>Terminal session</span>
      </div>
    )
  }

  // Conversation tab
  if (tab.type === 'conversation') {
    return (
      <div className="text-[10px] text-white/30 truncate">
        {tab.path}
      </div>
    )
  }

  const isDocument = tab.type === 'document'
  const isMarkdown = tab.path.endsWith('.md')
  const isCode = tab.type === 'file' && !isMarkdown

  const availableModes: ViewMode[] = isMarkdown
    ? ['mindmap', 'rendered', 'raw']
    : isDocument
    ? ['rendered', 'raw']
    : ['preview', 'code']

  const currentView = availableModes.includes(currentViewMode) ? currentViewMode : availableModes[0]

  if (loading) {
    return <div className="text-[10px] text-white/20 animate-pulse">Loading…</div>
  }

  return (
    <div className="flex flex-col h-full">
      <ViewModeToggle
        current={currentView}
        options={availableModes}
        onChange={setViewMode}
      />

      {currentView === 'mindmap' && isMarkdown && (
        <MindMapView
          markdown={content || tab.path}
          onNodeClick={(node) => {
            console.log('[MindMap] Node clicked:', node.label, node.linkedFiles)
          }}
        />
      )}

      {currentView === 'rendered' && (
        <div className="flex-1 overflow-auto text-[10px] leading-relaxed prose prose-invert prose-sm max-w-none">
          <ReactMarkdown>{content || '# No content'}</ReactMarkdown>
        </div>
      )}

      {currentView === 'raw' && (
        <div className="flex-1 overflow-auto">
          <pre className="text-[9px] text-white/40 font-mono whitespace-pre-wrap p-1">
            {content || '// No content'}
          </pre>
        </div>
      )}

      {currentView === 'preview' && (
        <div className="text-[10px] text-white/35 truncate">
          {tab.path}
          <div className="text-white/20 text-[8px] mt-0.5 border-l border-white/10 pl-1">
            {content.slice(0, 120).replace(/\n/g, ' ')}…
          </div>
        </div>
      )}

      {currentView === 'code' && (
        <div className="flex-1 min-h-0 overflow-hidden rounded border border-white/5">
          <CodePreviewPanel
            code={content || '// No content'}
            language={tab.path.split('.').pop() || 'tsx'}
          />
        </div>
      )}
    </div>
  )
}
