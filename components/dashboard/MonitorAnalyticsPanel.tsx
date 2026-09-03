"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Zap, DollarSign, Clock, Cpu, TrendingUp, Activity, RefreshCw,
} from "lucide-react";
import { Xur } from "@/components/Xur";

// ── Types ────────────────────────────────────────────────────────────────────

interface ModelBreakdown {
  model: string;
  total_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  audio_tokens: number;
  estimated_cost: number;
  avg_latency_ms: number;
  percentage: number;
  first_seen: number;
  last_seen: number;
}

interface SessionStats {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_audio_tokens: number;
  estimated_cost: number;
  avg_latency_ms: number;
  session_duration_minutes: number;
}

interface LatencyMetrics {
  count: number;
  min_ms: number;
  max_ms: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
}

interface RecentRecord {
  timestamp: number;
  session_id: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  mode: string;
  estimated_cost: number;
}

interface AnalyticsData {
  stats: SessionStats;
  models: ModelBreakdown[];
  latency: LatencyMetrics;
  recent: RecentRecord[];
}

interface MonitorAnalyticsPanelProps {
  glowColor?: string;
  fontColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ── Big Number Card (spiced up) ──────────────────────────────────────────────

function BigNumberCard({
  icon: Icon,
  label,
  value,
  sublabel,
  glowColor,
  delay = 0,
  accent,
}: {
  icon: any;
  label: string;
  value: string;
  sublabel?: string;
  glowColor: string;
  delay?: number;
  accent?: string;
}) {
  const cardColor = accent || glowColor;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
      whileHover={{ scale: 1.02 }}
      className="rounded-md border p-5 flex flex-col gap-2 relative overflow-hidden group min-w-0"
      style={{
        borderColor: `${cardColor}20`,
        background: `linear-gradient(135deg, rgba(5,5,12,0.7) 0%, rgba(12,12,20,0.5) 100%)`,
      }}
    >
      {/* Hover glow sweep */}
      <motion.div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
        style={{
          background: `radial-gradient(circle at 50% 0%, ${cardColor}10, transparent 70%)`,
        }}
      />

      {/* Top accent line */}
      <div
        className="absolute top-0 left-0 right-0 h-[1px]"
        style={{ background: `linear-gradient(90deg, transparent, ${cardColor}40, transparent)` }}
      />

      <div className="flex items-center justify-between gap-2 relative z-10 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <motion.div
            animate={{ opacity: [0.6, 1, 0.6] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut", delay }}
            className="flex-shrink-0"
          >
            <Icon size={11} style={{ color: cardColor }} />
          </motion.div>
          <span className="text-[9px] font-bold uppercase tracking-wider text-white/40 truncate">{label}</span>
        </div>
        {sublabel && (
          <span
            className="text-[8px] text-white/30 tabular-nums leading-none truncate min-w-0 flex-shrink-0"
            title={sublabel}
          >
            {sublabel}
          </span>
        )}
      </div>
      <span
        className="text-[20px] font-bold tabular-nums leading-none relative z-10 truncate"
        style={{ color: cardColor }}
        title={value}
      >
        {value}
      </span>
    </motion.div>
  );
}

// ── Shared Section Card (matches BigNumberCard aesthetic) ─────────────────────

function AnalyticsSection({
  icon: Icon,
  title,
  glowColor,
  children,
  delay = 0,
  className = "",
}: {
  icon: any;
  title: string;
  glowColor: string;
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
      whileHover={{ scale: 1.01 }}
      className={`rounded-md border p-5 relative overflow-hidden group min-w-0 ${className}`}
      style={{
        borderColor: `${glowColor}20`,
        background: `linear-gradient(135deg, rgba(5,5,12,0.7) 0%, rgba(12,12,20,0.5) 100%)`,
      }}
    >
      {/* Hover glow sweep */}
      <motion.div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
        style={{
          background: `radial-gradient(circle at 50% 0%, ${glowColor}10, transparent 70%)`,
        }}
      />

      {/* Top accent line */}
      <div
        className="absolute top-0 left-0 right-0 h-[1px]"
        style={{ background: `linear-gradient(90deg, transparent, ${glowColor}40, transparent)` }}
      />

      {/* Header */}
      <div className="flex items-center gap-2 mb-3 relative z-10">
        <motion.div
          animate={{ opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
        >
          <Icon size={12} style={{ color: glowColor }} />
        </motion.div>
        <span className="text-[10px] font-bold uppercase tracking-wider text-white/50 truncate">{title}</span>
      </div>

      <div className="relative z-10">{children}</div>
    </motion.div>
  );
}

// ── Model Breakdown Row (spiced up) ──────────────────────────────────────────

function ModelRow({ model, glowColor, maxTokens, index }: { model: ModelBreakdown; glowColor: string; maxTokens: number; index: number }) {
  const barWidth = maxTokens > 0 ? (model.total_tokens / maxTokens) * 100 : 0;

  return (
    <motion.div
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
      className="flex items-center gap-3 py-2.5 border-b border-white/[0.03] last:border-0 hover:bg-white/[0.02] transition-colors rounded-sm px-5 min-w-0"
    >
      {/* Model name */}
      <div className="flex-1 min-w-0 overflow-hidden">
        <span className="text-[11px] font-medium text-white/80 truncate block leading-tight">{model.model}</span>
        <span className="text-[9px] text-white/30 leading-none mt-0.5 block">{model.total_calls} calls</span>
      </div>

      {/* Token bar with animated gradient sweep */}
      <div className="w-[100px] flex-shrink-0">
        <div className="h-[6px] rounded-full bg-white/[0.04] overflow-hidden relative">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${barWidth}%` }}
            transition={{ duration: 0.6, ease: "easeOut", delay: index * 0.04 }}
            className="h-full rounded-full relative overflow-hidden"
            style={{
              background: `linear-gradient(90deg, ${glowColor}40, ${glowColor})`,
            }}
          >
            {/* Shimmer sweep */}
            <motion.div
              className="absolute inset-0"
              style={{
                background: `linear-gradient(90deg, transparent, ${glowColor}80, transparent)`,
              }}
              animate={{ x: ["-100%", "200%"] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut", repeatDelay: 1 }}
            />
          </motion.div>
        </div>
      </div>

      {/* Token count */}
      <div className="w-[56px] flex-shrink-0 text-right">
        <span className="text-[11px] font-medium tabular-nums text-white/70 leading-none">
          {formatNumber(model.total_tokens)}
        </span>
      </div>

      {/* Percentage */}
      <div className="w-[40px] flex-shrink-0 text-right">
        <span className="text-[10px] tabular-nums font-bold leading-none" style={{ color: glowColor }}>
          {model.percentage}%
        </span>
      </div>

      {/* Cost */}
      <div className="w-[56px] flex-shrink-0 text-right">
        <span className="text-[10px] tabular-nums text-white/40 leading-none">
          ${model.estimated_cost.toFixed(4)}
        </span>
      </div>
    </motion.div>
  );
}

// ── Latency Row ──────────────────────────────────────────────────────────────

function LatencyRow({ label, value, glowColor, isHighlight }: { label: string; value: number; glowColor: string; isHighlight?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 px-4 rounded hover:bg-white/[0.02] transition-colors">
      <span className="text-[10px] text-white/40 uppercase tracking-wide font-bold">{label}</span>
      <span
        className="text-[12px] font-medium tabular-nums leading-none"
        style={{ color: isHighlight ? glowColor : "rgba(255,255,255,0.6)" }}
      >
        {value.toFixed(1)} ms
      </span>
    </div>
  );
}

// ── Main Panel ───────────────────────────────────────────────────────────────

export function MonitorAnalyticsPanel({ glowColor = "#00d4aa", fontColor = "white", sendMessage }: MonitorAnalyticsPanelProps) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  const requestData = useCallback(() => {
    setLoading(true);
    if (sendMessage) {
      sendMessage("confirm_card", { section_id: "analytics", values: {} });
    }
  }, [sendMessage]);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent;
      const { type, payload } = ce.detail || {};

      if (type === "monitor_analytics_data") {
        setData(payload);
        setLoading(false);
      }
    };

    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  useEffect(() => {
    requestData();
    const interval = setInterval(requestData, 10000);
    return () => clearInterval(interval);
  }, [requestData]);

  const stats = data?.stats;
  const models = data?.models ?? [];
  const latency = data?.latency;
  const recent = data?.recent ?? [];
  const maxTokens = models.length > 0 ? Math.max(...models.map((m) => m.total_tokens)) : 0;

  if (loading && !data) {
    return (
      <div className="w-full h-full flex items-center justify-center p-8">
        <div className="flex flex-col items-center gap-3">
          <Xur size={28} color={glowColor} speed={1.2} />
          <span className="text-[11px] text-white/40">Loading analytics...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-y-auto overflow-x-hidden p-2 space-y-2 scrollbar-hide antialiased">
      {/* Minimal refresh */}
      <div className="flex justify-end">
        <button
          onClick={requestData}
          className="p-0.5 rounded hover:bg-white/5 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={10} className="text-white/40 hover:text-white/70" />
        </button>
      </div>

      {/* Big Number Cards — 2x2 grid with accent colors */}
      <div className="grid grid-cols-2 gap-1.5 [&>*]:min-w-0">
        <BigNumberCard
          icon={Zap}
          label="Total Tokens"
          value={formatNumber(stats?.total_tokens ?? 0)}
          sublabel={`${formatNumber(stats?.total_prompt_tokens ?? 0)}↑ / ${formatNumber(stats?.total_completion_tokens ?? 0)}↓`}
          glowColor={glowColor}
          delay={0}
        />
        <BigNumberCard
          icon={Activity}
          label="Total Calls"
          value={formatNumber(stats?.total_calls ?? 0)}
          sublabel={stats?.total_audio_tokens ? `${formatNumber(stats.total_audio_tokens)} audio` : "calls"}
          glowColor={glowColor}
          delay={0.05}
          accent="#a855f7"
        />
        <BigNumberCard
          icon={DollarSign}
          label="Est. Cost"
          value={`$${(stats?.estimated_cost ?? 0).toFixed(4)}`}
          sublabel="USD"
          glowColor={glowColor}
          delay={0.1}
          accent="#22c55e"
        />
        <BigNumberCard
          icon={Clock}
          label="Avg Latency"
          value={`${(stats?.avg_latency_ms ?? 0).toFixed(0)}ms`}
          sublabel={`${(stats?.session_duration_minutes ?? 0).toFixed(1)} min`}
          glowColor={glowColor}
          delay={0.15}
          accent="#fbbf24"
        />
      </div>

      {/* Model Breakdown */}
      <AnalyticsSection icon={Cpu} title="Model Breakdown" glowColor={glowColor} delay={0.2}>
        {/* Column headers */}
        <div className="flex items-center gap-3 pb-2 border-b border-white/[0.05] mb-1 px-4">
          <div className="flex-1 min-w-0 text-[9px] font-bold uppercase tracking-wider text-white/30">Model</div>
          <div className="w-[100px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-center">Distribution</div>
          <div className="w-[56px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-right">Tokens</div>
          <div className="w-[40px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-right">%</div>
          <div className="w-[56px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-right">Cost</div>
        </div>

        {models.length === 0 ? (
          <div className="py-4 text-center">
            <span className="text-[10px] text-white/30">No model usage recorded yet</span>
          </div>
        ) : (
          models.map((m, i) => <ModelRow key={m.model} model={m} glowColor={glowColor} maxTokens={maxTokens} index={i} />)
        )}
      </AnalyticsSection>

      {/* Latency Metrics */}
      {latency && latency.count > 0 && (
        <AnalyticsSection icon={TrendingUp} title="Latency Distribution" glowColor={glowColor} delay={0.25}>
          <div className="grid grid-cols-3 gap-x-3 gap-y-0">
            <LatencyRow label="Min" value={latency.min_ms} glowColor={glowColor} />
            <LatencyRow label="P50" value={latency.p50_ms} glowColor={glowColor} isHighlight />
            <LatencyRow label="Avg" value={latency.avg_ms} glowColor={glowColor} />
            <LatencyRow label="P95" value={latency.p95_ms} glowColor={glowColor} isHighlight />
            <LatencyRow label="Max" value={latency.max_ms} glowColor={glowColor} />
            <LatencyRow label="Count" value={latency.count} glowColor={glowColor} />
          </div>
        </AnalyticsSection>
      )}

      {/* Recent Activity */}
      {recent.length > 0 && (
        <AnalyticsSection icon={Activity} title="Recent Activity" glowColor={glowColor} delay={0.3}>
          <div className="space-y-1 max-h-[160px] overflow-y-auto scrollbar-hide">
            {recent.map((r, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.3) }}
                className="flex items-center gap-3 py-2 text-[10px] border-b border-white/[0.02] last:border-0 hover:bg-white/[0.03] transition-colors rounded-sm min-w-0"
                style={{ paddingLeft: 4, paddingRight: 4 }}
              >
                <span className="text-white/30 tabular-nums w-[64px] flex-shrink-0 leading-none">{formatTime(r.timestamp)}</span>
                <span className="text-white/60 truncate flex-1 min-w-0 leading-none">{r.model}</span>
                <span className="tabular-nums text-white/40 w-[56px] flex-shrink-0 text-right leading-none">{formatNumber(r.total_tokens)}</span>
                <span className="tabular-nums w-[48px] flex-shrink-0 text-right leading-none" style={{ color: glowColor }}>
                  {r.latency_ms.toFixed(0)}ms
                </span>
              </motion.div>
            ))}
          </div>
        </AnalyticsSection>
      )}
    </div>
  );
}

export default MonitorAnalyticsPanel;
