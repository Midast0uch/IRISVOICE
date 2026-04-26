'use client'

/**
 * DashboardRenderer — renders DashboardData from crawler results.
 * Supports: MetricsSection, TableSection, CardsSection, ChartSection.
 * Receives a DashboardData object and renders each section in sequence.
 */

import { useState, useCallback } from 'react'
import { Download, Star, ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type {
  DashboardData,
  DashboardSection,
  MetricsSection,
  TableSection,
  CardsSection,
  ChartSection,
  MetricItem,
  CardItem,
} from '@/types/iris'

interface DashboardRendererProps {
  data: DashboardData
  glowColor?: string
  onSave?: (pinId: string) => void  // called after ★ Save anchors a PiN
}

// ── Metric card ────────────────────────────────────────────────────────────────
function MetricCard({ item, glowColor }: { item: MetricItem; glowColor: string }) {
  const TrendIcon =
    item.trend === 'up' ? TrendingUp :
    item.trend === 'down' ? TrendingDown :
    Minus

  const trendColor =
    item.trend === 'up' ? '#22c55e' :
    item.trend === 'down' ? '#ef4444' :
    'rgba(255,255,255,0.4)'

  return (
    <div
      className="flex flex-col gap-1 p-3 rounded-lg"
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: `1px solid ${glowColor}20`,
      }}
    >
      <span className="text-[10px] font-medium uppercase tracking-widest text-white/40">
        {item.label}
      </span>
      <span className="text-2xl font-semibold text-white leading-none">{item.value}</span>
      {item.delta && (
        <span className="flex items-center gap-1 text-[11px]" style={{ color: trendColor }}>
          <TrendIcon size={11} />
          {item.delta}
        </span>
      )}
    </div>
  )
}

// ── Metrics section ────────────────────────────────────────────────────────────
function MetricsSectionView({ section, glowColor }: { section: MetricsSection; glowColor: string }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {section.items.map((item, i) => (
        <MetricCard key={i} item={item} glowColor={glowColor} />
      ))}
    </div>
  )
}

// ── Table section ──────────────────────────────────────────────────────────────
function TableSectionView({ section, glowColor }: { section: TableSection; glowColor: string }) {
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortAsc, setSortAsc] = useState(true)

  const handleSort = useCallback((col: number) => {
    if (sortCol === col) {
      setSortAsc(a => !a)
    } else {
      setSortCol(col)
      setSortAsc(true)
    }
  }, [sortCol])

  const rows = sortCol === null ? section.rows : [...section.rows].sort((a, b) => {
    const av = a[sortCol] ?? ''
    const bv = b[sortCol] ?? ''
    const cmp = av.localeCompare(bv, undefined, { numeric: true })
    return sortAsc ? cmp : -cmp
  })

  return (
    <div className="overflow-x-auto">
      {section.title && (
        <h4 className="text-[11px] font-semibold uppercase tracking-widest text-white/50 mb-2">
          {section.title}
        </h4>
      )}
      <table className="w-full text-[12px]">
        <thead>
          <tr style={{ borderBottom: `1px solid ${glowColor}20` }}>
            {section.headers.map((h, i) => (
              <th
                key={i}
                onClick={() => handleSort(i)}
                className="text-left px-2 py-1.5 font-medium text-white/50 cursor-pointer select-none hover:text-white/80 transition-colors"
              >
                {h} {sortCol === i ? (sortAsc ? '↑' : '↓') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className="hover:bg-white/[0.03] transition-colors"
              style={{ borderBottom: `1px solid rgba(255,255,255,0.04)` }}
            >
              {row.map((cell, ci) => (
                <td key={ci} className="px-2 py-1.5 text-white/70">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Cards section ──────────────────────────────────────────────────────────────
function CardsSectionView({ section, glowColor }: { section: CardsSection; glowColor: string }) {
  return (
    <div>
      {section.title && (
        <h4 className="text-[11px] font-semibold uppercase tracking-widest text-white/50 mb-2">
          {section.title}
        </h4>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {section.items.map((item, i) => (
          <CardItemView key={i} item={item} glowColor={glowColor} />
        ))}
      </div>
    </div>
  )
}

function CardItemView({ item, glowColor }: { item: CardItem; glowColor: string }) {
  return (
    <div
      className="p-3 rounded-lg flex flex-col gap-1.5"
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: `1px solid ${glowColor}18`,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-[13px] font-medium text-white leading-tight">{item.title}</span>
          {item.subtitle && (
            <span className="text-[11px] text-white/40">{item.subtitle}</span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {item.tag && (
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-medium uppercase tracking-wider"
              style={{ background: `${glowColor}20`, color: glowColor }}
            >
              {item.tag}
            </span>
          )}
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1 rounded hover:bg-white/10 transition-colors"
            >
              <ExternalLink size={11} className="text-white/40" />
            </a>
          )}
        </div>
      </div>
      <p className="text-[12px] text-white/60 leading-relaxed">{item.body}</p>
    </div>
  )
}

// ── Chart section (bar only — recharts deferred) ───────────────────────────────
function ChartSectionView({ section, glowColor }: { section: ChartSection; glowColor: string }) {
  // Render a simple CSS bar chart. Recharts integration is Phase E (recharts lazy-loaded).
  const allValues = section.datasets.flatMap(d => d.values)
  const maxVal = Math.max(...allValues, 1)

  return (
    <div>
      {section.title && (
        <h4 className="text-[11px] font-semibold uppercase tracking-widest text-white/50 mb-3">
          {section.title}
        </h4>
      )}
      <div className="flex flex-col gap-2">
        {section.labels.map((label, li) => (
          <div key={li} className="flex items-center gap-2">
            <span className="text-[11px] text-white/50 w-24 shrink-0 truncate" title={label}>
              {label}
            </span>
            <div className="flex-1 flex gap-1">
              {section.datasets.map((ds, di) => {
                const val = ds.values[li] ?? 0
                const pct = (val / maxVal) * 100
                return (
                  <div
                    key={di}
                    className="relative h-5 rounded-sm overflow-hidden flex-1"
                    style={{ background: 'rgba(255,255,255,0.05)' }}
                    title={`${ds.label}: ${val}`}
                  >
                    <div
                      className="h-full rounded-sm transition-all duration-500"
                      style={{
                        width: `${pct}%`,
                        background: `${glowColor}${60 + di * 20}`,
                      }}
                    />
                  </div>
                )
              })}
            </div>
            <span className="text-[11px] text-white/40 w-10 text-right shrink-0">
              {section.datasets[0]?.values[li] ?? 0}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Section dispatcher ─────────────────────────────────────────────────────────
function SectionView({ section, glowColor }: { section: DashboardSection; glowColor: string }) {
  switch (section.type) {
    case 'metrics': return <MetricsSectionView section={section} glowColor={glowColor} />
    case 'table':   return <TableSectionView   section={section} glowColor={glowColor} />
    case 'cards':   return <CardsSectionView   section={section} glowColor={glowColor} />
    case 'chart':   return <ChartSectionView   section={section} glowColor={glowColor} />
  }
}

// ── Export helpers ─────────────────────────────────────────────────────────────
function exportJson(data: DashboardData) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${data.title.replace(/\s+/g, '_')}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function exportCsv(data: DashboardData) {
  const tables = data.sections.filter((s): s is TableSection => s.type === 'table')
  if (tables.length === 0) return
  const rows = [tables[0].headers, ...tables[0].rows]
  const csv = rows.map(r => r.map(c => `"${c.replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${data.title.replace(/\s+/g, '_')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ── Root component ─────────────────────────────────────────────────────────────
export function DashboardRenderer({ data, glowColor = '#00d4ff', onSave }: DashboardRendererProps) {
  const [saved, setSaved] = useState(false)

  const handleSave = useCallback(async () => {
    if (!data.pin_id || saved) return
    try {
      const res = await fetch('/api/crawler/pin/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin_id: data.pin_id }),
      })
      if (res.ok) {
        setSaved(true)
        onSave?.(data.pin_id)
      }
    } catch {
      // Network error — silently ignore; user can retry
    }
  }, [data.pin_id, saved, onSave])

  const hasTable = data.sections.some(s => s.type === 'table')

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div
        className="px-4 py-3 flex items-start justify-between gap-3 border-b shrink-0"
        style={{ borderColor: `${glowColor}15` }}
      >
        <div className="flex flex-col gap-0.5 min-w-0">
          <h3 className="text-[14px] font-semibold text-white leading-tight truncate">{data.title}</h3>
          <p className="text-[11px] text-white/50 leading-snug">{data.summary}</p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {data.pin_id && (
            <button
              onClick={handleSave}
              disabled={saved}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium transition-all duration-150"
              style={{
                background: saved ? `${glowColor}25` : 'rgba(255,255,255,0.05)',
                border: `1px solid ${saved ? glowColor + '60' : 'rgba(255,255,255,0.1)'}`,
                color: saved ? glowColor : 'rgba(255,255,255,0.6)',
              }}
            >
              <Star size={11} fill={saved ? glowColor : 'none'} />
              {saved ? 'Saved' : 'Save'}
            </button>
          )}
          <button
            onClick={() => exportJson(data)}
            className="p-1.5 rounded hover:bg-white/10 transition-colors"
            title="Export JSON"
          >
            <Download size={13} className="text-white/50" />
          </button>
          {hasTable && (
            <button
              onClick={() => exportCsv(data)}
              className="p-1.5 rounded hover:bg-white/10 transition-colors text-[10px] text-white/50 hover:text-white font-mono"
              title="Export CSV"
            >
              CSV
            </button>
          )}
        </div>
      </div>

      {/* Sections */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-5">
        {data.sections.map((section, i) => (
          <SectionView key={i} section={section} glowColor={glowColor} />
        ))}
      </div>

      {/* Footer */}
      <div
        className="px-4 py-2 flex items-center gap-3 border-t text-[10px] text-white/30 shrink-0"
        style={{ borderColor: `${glowColor}10` }}
      >
        <span>Crawled {data.crawled_pages} pages</span>
        <span>·</span>
        <span>{data.duration_ms}ms</span>
        <span>·</span>
        <span>{new Date(data.timestamp).toLocaleString()}</span>
        <span className="ml-auto font-mono opacity-60 truncate max-w-[40%]" title={data.query}>
          "{data.query}"
        </span>
      </div>
    </div>
  )
}
