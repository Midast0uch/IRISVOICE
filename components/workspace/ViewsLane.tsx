'use client'

/**
 * The Workspace Hub's Views lane (docs/design/chatview-2026-10-06, concept 2 rev 4):
 * artifacts and ± diffs dragged out of the chat (or sent by "To dashboard") stay open
 * here, beside the hub's tools. A view is not a tab and not a project file.
 * Each card: title + kind, the body (markdown rendered; html / json raw; diff hunks), a close x.
 */

import React from 'react'
import ReactMarkdown from 'react-markdown'
import { useWorkspaceStore, type WorkspaceView } from '@/stores/workspaceStore'
import { DiffLines } from '@/components/chat/diff/DiffLines'

function ViewBody({ view }: { view: WorkspaceView }) {
  if (view.kind === 'diff') {
    return (
      <div data-workspace-diff>
        {(view.diffs ?? []).map((d) => (
          <div key={d.diff_id} className="mb-2">
            <div className="text-[10px] font-mono truncate" style={{ color: 'rgba(255,255,255,0.7)' }} title={d.path}>
              ± {d.path}{' '}
              <span style={{ color: '#5fcf98' }}>+{d.added}</span>{' '}
              <span style={{ color: '#ff7a6e' }}>−{d.removed}</span>
            </div>
            {d.hunks.map((h, i) => (
              <DiffLines key={i} lines={h.lines} fontSize={10} />
            ))}
          </div>
        ))}
      </div>
    )
  }
  if (view.format === 'html' || view.format === 'json') {
    return <pre className="m-0 text-[10px] font-mono whitespace-pre-wrap text-white/60">{view.content || '// No content'}</pre>
  }
  return (
    <div className="text-[11px] leading-relaxed prose prose-invert prose-sm max-w-none">
      <ReactMarkdown>{view.content || '# No content'}</ReactMarkdown>
    </div>
  )
}

export function ViewsLane({ over }: { over?: boolean }) {
  const views = useWorkspaceStore((s) => s.views) ?? []
  const removeView = useWorkspaceStore((s) => s.removeView)
  return (
    <aside
      className="shrink-0 flex flex-col min-h-0 overflow-hidden"
      data-views-lane
      aria-label="Views"
      style={{
        width: 300,
        margin: '0 8px 8px 0',
        border: `1px dashed ${over ? '#5fcf98' : 'rgba(255,255,255,0.14)'}`,
        borderRadius: 10,
        background: over ? 'rgba(95,207,152,0.06)' : 'transparent',
        transition: 'border-color .2s, background .2s',
      }}
    >
      <h4
        className="m-0 flex items-center gap-1.5 px-2.5 py-2 font-mono uppercase"
        style={{ fontSize: 10, letterSpacing: '.12em', color: '#8a92a8', borderBottom: '1px solid rgba(160,190,255,0.09)' }}
      >
        Views<small style={{ marginLeft: 'auto', letterSpacing: 0, textTransform: 'none', fontWeight: 400 }}>from the chat</small>
      </h4>
      <div className="flex-1 min-h-0 overflow-auto p-2 flex flex-col gap-2">
        {views.length === 0 && (
          <div className="text-center text-[12px]" style={{ color: '#8a92a8', padding: '14px 6px' }}>
            Drag an artifact or a ± diff here. It stays open beside your tools.
          </div>
        )}
        {views.map((v) => (
          <div
            key={v.id}
            data-view-card
            className="flex flex-col gap-1 min-w-0"
            style={{ border: '1px solid rgba(160,190,255,0.09)', borderRadius: 7, background: '#0e1122', padding: '7px 9px' }}
          >
            <div className="flex items-center gap-1.5 min-w-0" style={{ font: '600 12px/1.3 sans-serif', color: '#e6e9f2' }}>
              <span aria-hidden style={{ color: v.kind === 'diff' ? '#5fcf98' : 'var(--b1, #60a5fa)' }}>{v.kind === 'diff' ? '±' : '▤'}</span>
              <span className="truncate" data-view-title>{v.title}</span>
              <small className="font-mono shrink-0" style={{ fontWeight: 400, color: '#8a92a8' }} data-view-kind>
                {v.kind === 'diff' ? 'diff' : v.format || 'artifact'}
              </small>
              <button
                type="button"
                aria-label={`Close view ${v.title}`}
                onClick={() => removeView(v.id)}
                style={{ marginLeft: 'auto', background: 'none', border: 0, color: '#8a92a8', cursor: 'pointer' }}
              >
                ×
              </button>
            </div>
            <div className="overflow-auto" style={{ maxHeight: 260 }}>
              <ViewBody view={v} />
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
