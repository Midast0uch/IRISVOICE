"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  BarChart3, Zap, DollarSign, Clock, Cpu, TrendingUp, Activity, RefreshCw,
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

// ── Big Number Card ──────────────────────────────────────────────────────────

function BigNumberCard({
  icon: Icon,
  label,
  value,
  sublabel,
  glowColor,
  delay = 0,
}: {
  icon: any;
  label: string;
  value: string;
  sublabel?: string;
  glowColor: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
      className="rounded-lg border p-3 flex flex-col gap-1"
      style={{
        borderColor: `${glowColor}20`,
        background: `linear-gradient(135deg, rgba(5,5,12,0.6) 0%, rgba(12,12,20,0.4) 100%)`,
      }}
    >
      <div className="flex items-center gap-1.5">
        <Icon size={12} style={{ color: glowColor }} />
        <span className="text-[9px] font-bold uppercase tracking-wider text-white/40">{label}</span>
      </div>
      <span className="text-[20px] font-bold tabular-nums" style={{ color: glowColor }}>
        {value}
      </span>
      {sublabel && <span className="text-[9px] text-white/30 tabular-nums">{sublabel}</span>}
    </motion.div>
  );
}

// ── Model Breakdown Row ──────────────────────────────────────────────────────

function ModelRow({ model, glowColor, maxTokens }: { model: ModelBreakdown; glowColor: string; maxTokens: number }) {
  const barWidth = maxTokens > 0 ? (model.total_tokens / maxTokens) * 100 : 0;

  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-white/[0.03] last:border-0">
      {/* Model name */}
      <div className="flex-1 min-w-0">
        <span className="text-[11px] font-medium text-white/80 truncate block">{model.model}</span>
        <span className="text-[9px] text-white/30">{model.total_calls} calls</span>
      </div>

      {/* Token bar */}
      <div className="w-[80px] flex-shrink-0">
        <div className="h-[6px] rounded-full bg-white/[0.04] overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${barWidth}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="h-full rounded-full"
            style={{
              background: `linear-gradient(90deg, ${glowColor}40, ${glowColor})`,
            }}
          />
        </div>
      </div>

      {/* Token count */}
      <div className="w-[60px] flex-shrink-0 text-right">
        <span className="text-[11px] font-medium tabular-nums text-white/70">
          {formatNumber(model.total_tokens)}
        </span>
      </div>

      {/* Percentage */}
      <div className="w-[40px] flex-shrink-0 text-right">
        <span className="text-[10px] tabular-nums" style={{ color: glowColor }}>
          {model.percentage}%
        </span>
      </div>

      {/* Cost */}
      <div className="w-[50px] flex-shrink-0 text-right">
        <span className="text-[10px] tabular-nums text-white/40">
          ${model.estimated_cost.toFixed(4)}
        </span>
      </div>
    </div>
  );
}

// ── Latency Row ──────────────────────────────────────────────────────────────

function LatencyRow({ label, value, glowColor }: { label: string; value: number; glowColor: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[10px] text-white/40 uppercase tracking-wide">{label}</span>
      <span className="text-[11px] font-medium tabular-nums" style={{ color: glowColor }}>
        {value.toFixed(1)} ms
      </span>
    </div>
  );
}

// ── Main Panel ───────────────────────────────────────────────────────────────

export function MonitorAnalyticsPanel({ glowColor = "#00d4aa", fontColor = "white", sendMessage }: MonitorAnalyticsPanelProps) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  // Request analytics data from backend
  const requestData = useCallback(() => {
    setLoading(true);
    if (sendMessage) {
      sendMessage("confirm_card", { section_id: "analytics", values: {} });
    }
  }, [sendMessage]);

  // Listen for monitor_analytics_data WS messages
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

  // Auto-request on mount
  useEffect(() => {
    requestData();
    // Refresh every 10 seconds
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
          <Xur size={48} color={glowColor} speed={1.2} />
          <span className="text-[11px] text-white/40">Loading analytics...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-y-auto p-3 space-y-3 scrollbar-hide">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <BarChart3 size={14} style={{ color: glowColor }} />
          <span className="text-[12px] font-bold uppercase tracking-wider text-white/60">Analytics</span>
        </div>
        <button
          onClick={requestData}
          className="p-1 rounded hover:bg-white/5 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className="text-white/40 hover:text-white/70" />
        </button>
      </div>

      {/* Big Number Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <BigNumberCard
          icon={Zap}
          label="Total Tokens"
          value={formatNumber(stats?.total_tokens ?? 0)}
          sublabel={`${formatNumber(stats?.total_prompt_tokens ?? 0)} in / ${formatNumber(stats?.total_completion_tokens ?? 0)} out`}
          glowColor={glowColor}
          delay={0}
        />
        <BigNumberCard
          icon={Activity}
          label="Total Calls"
          value={formatNumber(stats?.total_calls ?? 0)}
          sublabel={stats?.total_audio_tokens ? `${formatNumber(stats.total_audio_tokens)} audio tokens` : undefined}
          glowColor={glowColor}
          delay={0.05}
        />
        <BigNumberCard
          icon={DollarSign}
          label="Est. Cost"
          value={`$${(stats?.estimated_cost ?? 0).toFixed(4)}`}
          sublabel="USD"
          glowColor={glowColor}
          delay={0.1}
        />
        <BigNumberCard
          icon={Clock}
          label="Avg Latency"
          value={`${(stats?.avg_latency_ms ?? 0).toFixed(0)} ms`}
          sublabel={`${(stats?.session_duration_minutes ?? 0).toFixed(1)} min session`}
          glowColor={glowColor}
          delay={0.15}
        />
      </div>

      {/* Model Breakdown */}
      <div
        className="rounded-lg border p-3"
        style={{ borderColor: `${glowColor}15`, background: "rgba(255,255,255,0.01)" }}
      >
        <div className="flex items-center gap-1.5 mb-2">
          <Cpu size={11} style={{ color: glowColor }} />
          <span className="text-[10px] font-bold uppercase tracking-wider text-white/50">Model Breakdown</span>
        </div>

        {/* Column headers */}
        <div className="flex items-center gap-2 pb-1.5 border-b border-white/[0.05] mb-1">
          <div className="flex-1 text-[9px] font-bold uppercase tracking-wider text-white/30">Model</div>
          <div className="w-[80px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-center">Distribution</div>
          <div className="w-[60px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-right">Tokens</div>
          <div className="w-[40px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-right">%</div>
          <div className="w-[50px] flex-shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/30 text-right">Cost</div>
        </div>

        {models.length === 0 ? (
          <div className="py-4 text-center">
            <span className="text-[10px] text-white/30">No model usage recorded yet</span>
          </div>
        ) : (
          models.map((m) => <ModelRow key={m.model} model={m} glowColor={glowColor} maxTokens={maxTokens} />)
        )}
      </div>

      {/* Latency Metrics */}
      {latency && latency.count > 0 && (
        <div
          className="rounded-lg border p-3"
          style={{ borderColor: `${glowColor}15`, background: "rgba(255,255,255,0.01)" }}
        >
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp size={11} style={{ color: glowColor }} />
            <span className="text-[10px] font-bold uppercase tracking-wider text-white/50">Latency Distribution</span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0">
            <LatencyRow label="Min" value={latency.min_ms} glowColor={glowColor} />
            <LatencyRow label="P50" value={latency.p50_ms} glowColor={glowColor} />
            <LatencyRow label="Avg" value={latency.avg_ms} glowColor={glowColor} />
            <LatencyRow label="P95" value={latency.p95_ms} glowColor={glowColor} />
            <LatencyRow label="Max" value={latency.max_ms} glowColor={glowColor} />
            <LatencyRow label="Count" value={latency.count} glowColor={glowColor} />
          </div>
        </div>
      )}

      {/* Recent Activity */}
      {recent.length > 0 && (
        <div
          className="rounded-lg border p-3"
          style={{ borderColor: `${glowColor}15`, background: "rgba(255,255,255,0.01)" }}
        >
          <div className="flex items-center gap-1.5 mb-2">
            <Activity size={11} style={{ color: glowColor }} />
            <span className="text-[10px] font-bold uppercase tracking-wider text-white/50">Recent Activity</span>
          </div>
          <div className="space-y-0.5 max-h-[180px] overflow-y-auto scrollbar-hide">
            {recent.map((r, i) => (
              <div key={i} className="flex items-center gap-2 py-1 text-[10px] border-b border-white/[0.02] last:border-0">
                <span className="text-white/30 tabular-nums w-[60px] flex-shrink-0">{formatTime(r.timestamp)}</span>
                <span className="text-white/60 truncate flex-1">{r.model}</span>
                <span className="tabular-nums text-white/40 w-[50px] flex-shrink-0 text-right">{formatNumber(r.total_tokens)}</span>
                <span className="tabular-nums w-[40px] flex-shrink-0 text-right" style={{ color: glowColor }}>
                  {r.latency_ms.toFixed(0)}ms
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default MonitorAnalyticsPanel;
