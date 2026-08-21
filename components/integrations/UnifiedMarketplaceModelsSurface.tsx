'use client'

/**
 * UnifiedMarketplaceModelsSurface — cli-workspace-unification T10 (REQ-9).
 *
 * ONE surface combining MCP Tools/Integrations with Local Models + Hugging
 * Face Hub discovery, switched by a top segmented pill (persisted in
 * localStorage as `iris_marketplace_subview`).
 *
 * HF tab contract (design.md Error Handling):
 *   - upstream search failure -> surfaced error state, never fabricated rows
 *   - token absent -> public search still works; gated repos marked unavailable
 *   - downloads stream into models/ with live %/speed/cancel (WS
 *     `model:download_progress` mirrored to `iris:model_download_progress`);
 *     cancel/fail removes the partial file backend-side and the row reports it
 */

import { useCallback, useEffect, useState } from 'react'
import { MarketplaceScreen } from '@/components/integrations/MarketplaceScreen'
import { ModelBrowserPanel } from '@/components/dashboard/ModelBrowserPanel'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { Download, Loader2, Search, X } from 'lucide-react'

type SubView = 'mcp' | 'models'

interface HfGgufFile {
  filename: string
  size?: number | null
}

interface HfResult {
  repo_id: string
  author: string
  likes: number
  downloads: number
  gated: boolean
  gguf_files: HfGgufFile[]
}

interface DownloadRow {
  jobId: string
  filename: string
  pct: number
  speedMb: number
  status: 'downloading' | 'done' | 'cancelled' | 'failed'
  error?: string
}

function formatBytes(n?: number | null): string {
  if (!n || n <= 0) return '—'
  const gb = n / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  return `${(n / (1024 * 1024)).toFixed(0)} MB`
}

function HfHubPanel({ glowColor }: { glowColor: string }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HfResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloads, setDownloads] = useState<Record<string, DownloadRow>>({})

  // Live progress via WS frames mirrored to window events by useIRISWebSocket.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = (e: Event) => {
      const d = (e as CustomEvent<Record<string, unknown>>).detail || {}
      const jobId = String(d.job_id || '')
      if (!jobId) return
      setDownloads((prev) => ({
        ...prev,
        [jobId]: {
          jobId,
          filename: String(d.filename || prev[jobId]?.filename || ''),
          pct: typeof d.pct === 'number' ? d.pct : prev[jobId]?.pct ?? 0,
          speedMb: typeof d.speed_mb === 'number' ? d.speed_mb : prev[jobId]?.speedMb ?? 0,
          status: d.cancelled ? 'cancelled' : d.error ? 'failed' : typeof d.pct === 'number' && d.pct >= 100 ? 'done' : 'downloading',
          error: typeof d.error === 'string' ? d.error : undefined,
        },
      }))
    }
    window.addEventListener('iris:model_download_progress', handler as EventListener)
    return () => window.removeEventListener('iris:model_download_progress', handler as EventListener)
  }, [])

  const doSearch = useCallback(async () => {
    setSearching(true)
    setError(null)
    try {
      const res = await fetch(`/api/models/hf/search?q=${encodeURIComponent(query)}&limit=20`)
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        // Surface the upstream failure — never fabricate results.
        setError(body?.error || `Search failed (${res.status})`)
        setResults(null)
      } else {
        setResults(Array.isArray(body?.results) ? body.results : [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed')
      setResults(null)
    } finally {
      setSearching(false)
    }
  }, [query])

  const startDownload = useCallback(async (repoId: string, file: HfGgufFile) => {
    try {
      const res = await fetch('/api/models/hf/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_id: repoId, filename: file.filename }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(body?.detail || `Download rejected (${res.status})`)
        return
      }
      setDownloads((prev) => ({
        ...prev,
        [body.job_id]: { jobId: body.job_id, filename: file.filename, pct: 0, speedMb: 0, status: 'downloading' },
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed to start')
    }
  }, [])

  const cancelDownload = useCallback(async (jobId: string) => {
    try {
      await fetch('/api/models/hf/download/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId }),
      })
    } catch {
      /* the worker's cancel flag is best-effort from here */
    }
  }, [])

  return (
    <div className="flex flex-col gap-3 p-3 min-h-0">
      {/* Local models — scan / VRAM fit / 1-click load (existing panel) */}
      <ModelBrowserPanel glowColor={glowColor} fontColor="white" />

      {/* REQ-9 AC5-AC8: HF Hub index search + streamed 1-click downloads */}
      <div
        className="rounded-xl p-3"
        style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid ${glowColor}15` }}
      >
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] font-bold tracking-wider uppercase" style={{ color: `${glowColor}90` }}>
            Hugging Face Hub
          </span>
          <div className="flex flex-1 items-center gap-1.5">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
              placeholder='e.g. "qwen2.5 coder gguf", "whisper"'
              className="flex-1 h-7 rounded px-2 text-[11px] bg-white/5 border border-white/5 outline-none font-mono text-white placeholder:text-white/25"
            />
            <button
              onClick={doSearch}
              disabled={searching}
              className="h-7 px-2.5 rounded text-[10px] font-medium flex items-center gap-1 disabled:opacity-40"
              style={{ background: `${glowColor}15`, color: glowColor, border: `1px solid ${glowColor}25` }}
            >
              {searching ? <Loader2 size={11} className="animate-spin" /> : <Search size={11} />}
              Search
            </button>
          </div>
        </div>

        {error && (
          <div className="text-[10px] px-2 py-1.5 rounded mb-2" style={{ background: 'rgba(239,68,68,0.08)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.2)' }}>
            {error}
          </div>
        )}

        {/* In-flight downloads */}
        {Object.values(downloads).length > 0 && (
          <div className="flex flex-col gap-1 mb-2">
            {Object.values(downloads).map((d) => (
              <div key={d.jobId} className="flex items-center gap-2 px-2 py-1 rounded" style={{ background: 'rgba(255,255,255,0.03)' }}>
                <Download size={10} style={{ color: glowColor }} />
                <span className="text-[10px] font-mono text-white/70 truncate flex-1">{d.filename}</span>
                {d.status === 'downloading' && (
                  <>
                    <div className="w-24 h-1 rounded-full overflow-hidden bg-white/10">
                      <div className="h-full" style={{ width: `${Math.min(100, d.pct)}%`, background: glowColor }} />
                    </div>
                    <span className="text-[9px] tabular-nums text-white/50 w-20 text-right">
                      {d.pct.toFixed(0)}% · {d.speedMb.toFixed(1)} MB/s
                    </span>
                    <button onClick={() => cancelDownload(d.jobId)} title="Cancel download" className="text-white/40 hover:text-red-400">
                      <X size={11} />
                    </button>
                  </>
                )}
                {d.status === 'done' && <span className="text-[9px]" style={{ color: '#34d399' }}>✓ done — rescanned</span>}
                {d.status === 'cancelled' && <span className="text-[9px] text-white/40">cancelled · partial removed</span>}
                {d.status === 'failed' && (
                  <span className="text-[9px] text-red-400 truncate max-w-[200px]" title={d.error}>
                    failed · partial removed{d.error ? ` — ${d.error}` : ''}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results */}
        {results && results.length === 0 && (
          <div className="text-[10px] text-white/30 italic px-1">No matching repositories</div>
        )}
        <div className="flex flex-col gap-1.5 max-h-[320px] overflow-y-auto pr-1">
          {(results || []).map((r) => (
            <div key={r.repo_id} className="rounded-lg px-2.5 py-2" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[11px] font-semibold text-white/85 truncate">{r.repo_id}</span>
                {r.gated && (
                  <span className="text-[8px] px-1 rounded bg-yellow-500/10 text-yellow-400/80 border border-yellow-500/20">gated</span>
                )}
                <span className="ml-auto text-[9px] text-white/35 flex-shrink-0">
                  ♥ {r.likes.toLocaleString()} · ↓ {r.downloads.toLocaleString()}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {r.gguf_files.length === 0 && (
                  <span className="text-[9px] text-white/25 italic">no .gguf files listed</span>
                )}
                {r.gguf_files.map((f) => (
                  <button
                    key={f.filename}
                    onClick={() => startDownload(r.repo_id, f)}
                    disabled={r.gated}
                    title={r.gated ? 'Gated repo — configure an HF token' : `Download ${f.filename}`}
                    className="text-[9px] font-mono px-1.5 py-0.5 rounded flex items-center gap-1 disabled:opacity-40"
                    style={{ background: `${glowColor}10`, color: `${glowColor}b0`, border: `1px solid ${glowColor}20` }}
                  >
                    <Download size={8} />
                    {quantLabel(f.filename)} · {formatBytes(f.size)}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" -> "Q4_K_M"; falls back to the
 *  full filename when no quant token is present. */
function quantLabel(filename: string): string {
  const m = filename.match(/(IQ?\d+_[A-Z]+_\d+|Q\d+_[A-Z]+(?:_\d+)?|Q\d+|[A-Z]\d+)\.gguf$/i)
  return m ? m[1].replace(/\.gguf$/i, '') : filename.replace(/\.gguf$/i, '')
}

export function UnifiedMarketplaceModelsSurface({
  glowColor,
  fontColor,
}: {
  glowColor: string
  fontColor: string
}) {
  const [subView, setSubView] = useState<SubView>('mcp')

  // Design: sub-view persists across sessions.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const saved = window.localStorage.getItem('iris_marketplace_subview')
    if (saved === 'mcp' || saved === 'models') setSubView(saved)
  }, [])
  const switchTo = (v: SubView) => {
    setSubView(v)
    if (typeof window !== 'undefined') window.localStorage.setItem('iris_marketplace_subview', v)
  }

  return (
    <div className="w-full h-full flex flex-col min-h-0">
      {/* REQ-9 AC2: top segmented pill switcher */}
      <div className="shrink-0 flex items-center justify-center gap-1 p-3 pb-2">
        {[
          { id: 'mcp' as const, label: '🔌 MCP Tools & Integrations' },
          { id: 'models' as const, label: '🧠 Local Models & HF Hub' },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => switchTo(t.id)}
            className="h-7 px-3 rounded-full text-[10px] font-bold tracking-wide transition-all"
            style={{
              background: subView === t.id ? `${glowColor}18` : 'rgba(255,255,255,0.03)',
              color: subView === t.id ? glowColor : 'rgba(255,255,255,0.45)',
              border: `1px solid ${subView === t.id ? `${glowColor}35` : 'rgba(255,255,255,0.06)'}`,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {subView === 'mcp' ? (
          <MarketplaceScreen glowColor={glowColor} fontColor={fontColor} />
        ) : (
          <HfHubPanel glowColor={glowColor} />
        )}
      </div>
    </div>
  )
}
