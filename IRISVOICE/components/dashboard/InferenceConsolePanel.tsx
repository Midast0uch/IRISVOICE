"use client"

import React, { useState, useRef, useEffect, useCallback } from "react"
import { Trash2, Pause, Play, Download, Activity, Filter, ChevronDown } from "lucide-react"

// ── Types ─────────────────────────────────────────────────────────────────

type InferenceEntry =
  | {
      kind: 'inference'
      id: string
      ts: number
      model: string
      promptTok: number
      compTok: number
      tps: number
      latencyMs: number
    }
  | {
      kind: 'load'
      id: string
      ts: number
      action: 'loaded' | 'unloaded'
      model: string
      profile: string
    }

type FilterMode = 'all' | 'inference' | 'load'

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function shortModel(model: string): string {
  const parts = model.split(/[\\/]/)
  const name = parts[parts.length - 1] || model
  return name.length > 32 ? name.slice(0, 29) + '…' : name
}

// ── Component ──────────────────────────────────────────────────────────────

interface InferenceConsolePanelProps {
  glowColor?: string
  fontColor?: string
}

export function InferenceConsolePanel({ glowColor = '#00d4aa', fontColor = 'white' }: InferenceConsolePanelProps) {
  const [entries, setEntries] = useState<InferenceEntry[]>([])
  const [filter, setFilter] = useState<FilterMode>('all')
  const [isPaused, setIsPaused] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [showFilterMenu, setShowFilterMenu] = useState(false)
  const [activeModel, setActiveModel] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const isPausedRef = useRef(isPaused)
  isPausedRef.current = isPaused

  // Session stats
  const inferenceEntries = entries.filter(e => e.kind === 'inference') as Extract<InferenceEntry, { kind: 'inference' }>[]
  const avgTps = inferenceEntries.length > 0
    ? (inferenceEntries.reduce((s, e) => s + e.tps, 0) / inferenceEntries.length).toFixed(1)
    : '—'
  const totalTokens = inferenceEntries.reduce((s, e) => s + e.compTok + e.promptTok, 0)

  // WebSocket event listener
  useEffect(() => {
    const handler = (e: Event) => {
      if (isPausedRef.current) return
      const ce = e as CustomEvent
      const { type, payload } = ce.detail || {}

      if (type === 'inference_event') {
        const entry: InferenceEntry = {
          kind: 'inference',
          id: `inf-${Date.now()}-${Math.random()}`,
          ts: payload.timestamp ?? Date.now() / 1000,
          model: payload.model ?? '',
          promptTok: payload.prompt_tokens ?? 0,
          compTok: payload.completion_tokens ?? 0,
          tps: payload.tps ?? 0,
          latencyMs: payload.time_ms ?? 0,
        }
        setEntries(prev => [...prev.slice(-499), entry])
      } else if (type === 'model_load_event') {
        const entry: InferenceEntry = {
          kind: 'load',
          id: `load-${Date.now()}-${Math.random()}`,
          ts: payload.timestamp ?? Date.now() / 1000,
          action: payload.action === 'loaded' ? 'loaded' : 'unloaded',
          model: payload.model ?? '',
          profile: payload.profile ?? '',
        }
        setEntries(prev => [...prev.slice(-499), entry])
        if (payload.action === 'loaded') setActiveModel(payload.model ?? null)
        if (payload.action === 'unloaded') setActiveModel(null)
      }
    }

    window.addEventListener('iris:ws_message', handler as EventListener)
    return () => window.removeEventListener('iris:ws_message', handler as EventListener)
  }, [])

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [entries, autoScroll])

  const handleExport = useCallback(() => {
    const json = JSON.stringify(entries, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `inference_console_${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [entries])

  const visible = entries.filter(e => filter === 'all' || e.kind === filter)

  return (
    <div className="flex flex-col h-full" style={{ color: fontColor }}>
      {/* Summary Bar */}
      <div
        className="flex items-center gap-4 px-4 py-3 border-b flex-shrink-0 flex-wrap"
        style={{ borderColor: `${glowColor}20`, background: 'rgba(0,0,0,0.3)' }}
      >
        <Activity size={14} style={{ color: glowColor }} />
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[10px] text-white/40 uppercase tracking-widest shrink-0">Model</span>
          <span className="text-[11px] font-mono truncate max-w-[180px]" style={{ color: activeModel ? glowColor : 'rgba(255,255,255,0.3)' }}>
            {activeModel ? shortModel(activeModel) : 'none loaded'}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-white/40 uppercase tracking-widest">Avg TPS</span>
          <span className="text-[11px] font-mono" style={{ color: glowColor }}>{avgTps}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-white/40 uppercase tracking-widest">Tokens</span>
          <span className="text-[11px] font-mono text-white/70">{totalTokens.toLocaleString()}</span>
        </div>
      </div>

      {/* Controls */}
      <div
        className="flex items-center gap-2 px-4 py-2 border-b flex-shrink-0"
        style={{ borderColor: `${glowColor}10` }}
      >
        {/* Filter */}
        <div className="relative">
          <button
            onClick={() => setShowFilterMenu(v => !v)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] uppercase tracking-widest border transition-all"
            style={{
              color: 'rgba(255,255,255,0.5)',
              borderColor: `${glowColor}20`,
              background: 'rgba(255,255,255,0.04)',
            }}
          >
            <Filter size={10} />
            {filter}
            <ChevronDown size={10} />
          </button>
          {showFilterMenu && (
            <div
              className="absolute top-full left-0 mt-1 rounded border shadow-xl z-50 overflow-hidden"
              style={{ background: 'rgba(10,10,20,0.98)', borderColor: `${glowColor}25`, minWidth: 110 }}
            >
              {(['all', 'inference', 'load'] as FilterMode[]).map(f => (
                <button
                  key={f}
                  onClick={() => { setFilter(f); setShowFilterMenu(false) }}
                  className="w-full text-left px-3 py-1.5 text-[10px] uppercase tracking-widest transition-colors hover:bg-white/5"
                  style={{ color: filter === f ? glowColor : 'rgba(255,255,255,0.5)' }}
                >
                  {f}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Pause/Resume */}
        <button
          onClick={() => setIsPaused(v => !v)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] uppercase tracking-widest border transition-all"
          style={{
            color: isPaused ? glowColor : 'rgba(255,255,255,0.5)',
            borderColor: isPaused ? `${glowColor}40` : `${glowColor}20`,
            background: isPaused ? `${glowColor}15` : 'rgba(255,255,255,0.04)',
          }}
        >
          {isPaused ? <Play size={10} /> : <Pause size={10} />}
          {isPaused ? 'Resume' : 'Pause'}
        </button>

        {/* Auto-scroll */}
        <button
          onClick={() => setAutoScroll(v => !v)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] uppercase tracking-widest border transition-all"
          style={{
            color: autoScroll ? glowColor : 'rgba(255,255,255,0.5)',
            borderColor: autoScroll ? `${glowColor}40` : `${glowColor}20`,
            background: autoScroll ? `${glowColor}15` : 'rgba(255,255,255,0.04)',
          }}
        >
          Auto-scroll
        </button>

        <div className="flex-1" />

        {/* Export */}
        <button
          onClick={handleExport}
          disabled={entries.length === 0}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] uppercase tracking-widest border transition-all"
          style={{
            color: 'rgba(255,255,255,0.4)',
            borderColor: `${glowColor}20`,
            background: 'rgba(255,255,255,0.04)',
            opacity: entries.length === 0 ? 0.4 : 1,
          }}
        >
          <Download size={10} />
          Export
        </button>

        {/* Clear */}
        <button
          onClick={() => setEntries([])}
          disabled={entries.length === 0}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] uppercase tracking-widest border transition-all"
          style={{
            color: 'rgba(255,255,255,0.4)',
            borderColor: `${glowColor}20`,
            background: 'rgba(255,255,255,0.04)',
            opacity: entries.length === 0 ? 0.4 : 1,
          }}
        >
          <Trash2 size={10} />
          Clear
        </button>
      </div>

      {/* Log Area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-2 font-mono text-[11px] space-y-1"
        style={{ background: 'rgba(0,0,0,0.2)' }}
      >
        {visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 opacity-40">
            <Activity size={28} />
            <p className="text-[11px] uppercase tracking-widest">Waiting for inference events…</p>
          </div>
        ) : (
          visible.map(entry => (
            <div key={entry.id} className="flex items-start gap-2 py-0.5">
              <span className="text-white/30 shrink-0">{fmtTime(entry.ts)}</span>
              {entry.kind === 'inference' ? (
                <span className="text-white/75">
                  <span style={{ color: glowColor }}>{shortModel(entry.model)}</span>
                  {' · '}
                  <span className="text-white/50">↑{entry.promptTok} ↓{entry.compTok} tok</span>
                  {' · '}
                  <span style={{ color: glowColor }}>{entry.tps} t/s</span>
                  {' · '}
                  <span className="text-white/50">{entry.latencyMs}ms</span>
                </span>
              ) : (
                <span className="text-white/35">
                  {entry.action === 'loaded' ? '▶ Loaded' : '■ Unloaded'}
                  {': '}
                  <span className="text-white/55">{shortModel(entry.model)}</span>
                  {entry.action === 'loaded' && entry.profile && (
                    <span className="text-white/30"> · {entry.profile}</span>
                  )}
                </span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default InferenceConsolePanel
