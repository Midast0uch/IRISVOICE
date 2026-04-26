'use client';

import { useEffect, useState } from 'react';
import { Scissors, Zap, RefreshCw, AlertCircle, FileEdit } from 'lucide-react';

interface DCPEvent {
  input_count: number;
  output_count: number;
  dedups: number;
  errors_purged: number;
  writes_superseded: number;
  tokens_saved: number;
}

interface DCPStats {
  totalPrunes: number;
  totalTokensSaved: number;
  totalDedups: number;
  totalErrorsPurged: number;
  totalWritesSuperseded: number;
  lastEvent: DCPEvent | null;
}

const EMPTY: DCPStats = {
  totalPrunes: 0,
  totalTokensSaved: 0,
  totalDedups: 0,
  totalErrorsPurged: 0,
  totalWritesSuperseded: 0,
  lastEvent: null,
};

interface DCPStatsPanelProps {
  glowColor?: string;
}

export function DCPStatsPanel({ glowColor = '#00d4aa' }: DCPStatsPanelProps) {
  const [stats, setStats] = useState<DCPStats>(EMPTY);

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<DCPEvent>).detail;
      if (!d) return;
      setStats(prev => ({
        totalPrunes: prev.totalPrunes + 1,
        totalTokensSaved: prev.totalTokensSaved + (d.tokens_saved ?? 0),
        totalDedups: prev.totalDedups + (d.dedups ?? 0),
        totalErrorsPurged: prev.totalErrorsPurged + (d.errors_purged ?? 0),
        totalWritesSuperseded: prev.totalWritesSuperseded + (d.writes_superseded ?? 0),
        lastEvent: d,
      }));
    };
    window.addEventListener('iris:dcp_pruned', handler);
    return () => window.removeEventListener('iris:dcp_pruned', handler);
  }, []);

  const metric = (label: string, value: number | string, icon: React.ReactNode, highlight = false) => (
    <div
      className="flex flex-col gap-1 px-4 py-3 rounded-lg border bg-white/[0.03] hover:bg-white/[0.05] transition-colors"
      style={{ borderColor: highlight ? `${glowColor}40` : 'rgba(255,255,255,0.06)' }}
    >
      <div className="flex items-center gap-1.5" style={{ color: highlight ? glowColor : 'rgba(255,255,255,0.35)' }}>
        {icon}
        <span className="text-[9px] font-black tracking-[0.18em] uppercase">{label}</span>
      </div>
      <span
        className="text-[22px] font-black tabular-nums leading-none"
        style={{ color: highlight ? glowColor : 'rgba(255,255,255,0.85)' }}
      >
        {typeof value === 'number' ? value.toLocaleString() : value}
      </span>
    </div>
  );

  const hasActivity = stats.totalPrunes > 0;

  return (
    <div className="px-8 py-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Scissors size={13} style={{ color: glowColor }} />
          <span className="text-[10px] font-black tracking-[0.22em] uppercase" style={{ color: 'rgba(255,255,255,0.6)' }}>
            DCP — Dynamic Context Pruner
          </span>
        </div>
        <div
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[9px] font-black tracking-[0.15em] uppercase"
          style={{
            borderColor: hasActivity ? `${glowColor}50` : 'rgba(255,255,255,0.08)',
            color: hasActivity ? glowColor : 'rgba(255,255,255,0.3)',
            background: hasActivity ? `${glowColor}12` : 'transparent',
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: hasActivity ? glowColor : 'rgba(255,255,255,0.2)' }}
          />
          {hasActivity ? 'ACTIVE' : 'IDLE — NO TURNS YET'}
        </div>
      </div>

      {/* Metric grid */}
      <div className="grid grid-cols-2 gap-2">
        {metric('Prune Passes', stats.totalPrunes, <RefreshCw size={10} />, stats.totalPrunes > 0)}
        {metric('Tokens Saved', stats.totalTokensSaved, <Zap size={10} />, stats.totalTokensSaved > 0)}
        {metric('Deduplicated', stats.totalDedups, <Scissors size={10} />)}
        {metric('Errors Purged', stats.totalErrorsPurged, <AlertCircle size={10} />)}
      </div>

      <div className="grid grid-cols-1 gap-2">
        {metric('Stale Writes Superseded', stats.totalWritesSuperseded, <FileEdit size={10} />)}
      </div>

      {/* Last event detail */}
      {stats.lastEvent && (
        <div
          className="rounded-lg border px-4 py-3 space-y-1.5"
          style={{ borderColor: 'rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
        >
          <span className="text-[9px] font-black tracking-[0.18em] uppercase" style={{ color: 'rgba(255,255,255,0.3)' }}>
            Last Pass
          </span>
          <div className="flex gap-4 flex-wrap">
            {[
              ['In', stats.lastEvent.input_count],
              ['Out', stats.lastEvent.output_count],
              ['Saved', stats.lastEvent.tokens_saved],
              ['Dedups', stats.lastEvent.dedups],
              ['Errs', stats.lastEvent.errors_purged],
              ['Writes↑', stats.lastEvent.writes_superseded],
            ].map(([k, v]) => (
              <div key={k as string} className="flex items-baseline gap-1">
                <span className="text-[9px] uppercase tracking-wide" style={{ color: 'rgba(255,255,255,0.3)' }}>{k}</span>
                <span className="text-[13px] font-bold tabular-nums" style={{ color: Number(v) > 0 ? glowColor : 'rgba(255,255,255,0.5)' }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
