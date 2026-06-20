"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, AlertTriangle, CheckCircle, XCircle, Bug, RefreshCw, Database, Cpu, Wifi, HardDrive, Brain, Mic, Network, Zap, Server } from "lucide-react";

interface MonitorDiagnosticsPanelProps {
  glowColor?: string;
  fontColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
}

type HealthStatus = "healthy" | "warning" | "error" | "idle";

interface HealthCheck {
  component: string;
  status: HealthStatus;
  message: string;
  latency_ms: number;
}

interface TroubleshootData {
  issues: string[];
  warnings: string[];
  summary: string;
}

// ── Component icon mapping ────────────────────────────────────────────────────

function getComponentIcon(name: string) {
  const n = name.toLowerCase();
  if (n.includes("memory") || n.includes("db") || n === "monitor_db") return Database;
  if (n.includes("log")) return Bug;
  if (n.includes("websocket") || n.includes("ws")) return Wifi;
  if (n.includes("agent") || n.includes("kernel")) return Brain;
  if (n.includes("audio") || n.includes("mic") || n.includes("voice")) return Mic;
  if (n.includes("mcp")) return Network;
  if (n.includes("llama") || n.includes("model") || n.includes("lfm")) return Cpu;
  if (n.includes("gpu")) return Zap;
  if (n.includes("system") || n.includes("platform")) return Server;
  if (n.includes("store")) return HardDrive;
  return Activity;
}

// ── Component display name ────────────────────────────────────────────────────

function getComponentLabel(name: string): string {
  const map: Record<string, string> = {
    memory_db: "Memory DB",
    monitor_db: "Monitor DB",
    log_manager: "Log Manager",
    websocket: "WebSocket",
    agent_kernel: "Agent Kernel",
    audio_engine: "Audio Engine",
    lfm_model: "LFM Model",
    llama_server: "Llama Server",
    mcp_servers: "MCP Servers",
    gpu: "GPU",
    system: "System",
  };
  return map[name] || name.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

// ── Status styling ────────────────────────────────────────────────────────────

function getStatusStyle(status: HealthStatus) {
  switch (status) {
    case "healthy":
      return { color: "#22c55e", bg: "rgba(34,197,94,0.08)", border: "rgba(34,197,94,0.2)", label: "OK" };
    case "warning":
      return { color: "#fbbf24", bg: "rgba(251,191,36,0.08)", border: "rgba(251,191,36,0.2)", label: "WARN" };
    case "error":
      return { color: "#ef4444", bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.2)", label: "ERR" };
    case "idle":
      return { color: "rgba(255,255,255,0.4)", bg: "rgba(255,255,255,0.03)", border: "rgba(255,255,255,0.08)", label: "IDLE" };
    default:
      return { color: "rgba(255,255,255,0.4)", bg: "rgba(255,255,255,0.03)", border: "rgba(255,255,255,0.08)", label: status.toUpperCase() };
  }
}

// ── Health row ────────────────────────────────────────────────────────────────

function HealthRow({ check, index }: { check: HealthCheck; index: number }) {
  const Icon = getComponentIcon(check.component);
  const style = getStatusStyle(check.status);
  const label = getComponentLabel(check.component);

  return (
    <motion.div
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay: index * 0.03 }}
      className="flex items-center gap-2 py-1.5 px-3 rounded hover:bg-white/[0.03] transition-colors min-w-0"
    >
      {/* Status dot */}
      <motion.div
        animate={check.status === "healthy" ? { opacity: [0.5, 1, 0.5] } : {}}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        className="w-[6px] h-[6px] rounded-full flex-shrink-0"
        style={{ background: style.color, boxShadow: `0 0 6px ${style.color}60` }}
      />

      {/* Label */}
      <span className="text-[10px] text-white/60 font-medium flex-shrink-0 w-[80px] truncate">
        {label}
      </span>

      {/* Message */}
      <span
        className="text-[10px] truncate flex-1 min-w-0"
        style={{ color: check.status === "idle" ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.7)" }}
        title={check.message}
      >
        {check.message || "—"}
      </span>

      {/* Latency */}
      {check.latency_ms > 0 && (
        <span className="text-[8px] text-white/25 tabular-nums flex-shrink-0 hidden sm:inline">
          {check.latency_ms.toFixed(0)}ms
        </span>
      )}

      {/* Status badge */}
      <span
        className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded flex-shrink-0 min-w-[32px] text-center"
        style={{ color: style.color, background: style.bg, border: `1px solid ${style.border}` }}
      >
        {style.label}
      </span>
    </motion.div>
  );
}

// ── Section wrapper (matches AnalyticsSection aesthetic) ──────────────────────

function DiagSection({
  title,
  icon: Icon,
  glowColor,
  children,
}: {
  title: string;
  icon: any;
  glowColor: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-md border overflow-hidden min-w-0"
      style={{
        borderColor: `${glowColor}15`,
        background: `linear-gradient(180deg, rgba(5,5,12,0.5) 0%, rgba(8,9,16,0.3) 100%)`,
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-2 border-b"
        style={{ borderColor: `${glowColor}10` }}
      >
        <Icon size={11} style={{ color: glowColor }} />
        <span className="text-[10px] font-bold uppercase tracking-wider text-white/60 truncate">
          {title}
        </span>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

// ── Issue card ────────────────────────────────────────────────────────────────

function IssueCard({ severity, text, delay }: { severity: "error" | "warning"; text: string; delay: number }) {
  const isError = severity === "error";
  const color = isError ? "#ef4444" : "#fbbf24";
  const Icon = isError ? XCircle : AlertTriangle;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay }}
      className="flex items-start gap-2 p-2 rounded min-w-0"
      style={{
        background: `${color}08`,
        border: `1px solid ${color}20`,
      }}
    >
      <Icon size={11} style={{ color }} className="flex-shrink-0 mt-[1px]" />
      <span className="text-[10px] leading-snug min-w-0 break-words" style={{ color: `${color}dd` }}>
        {text}
      </span>
    </motion.div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function MonitorDiagnosticsPanel({
  glowColor = "#22c55e",
  fontColor,
  sendMessage,
}: MonitorDiagnosticsPanelProps) {
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [troubleshoot, setTroubleshoot] = useState<TroubleshootData>({ issues: [], warnings: [], summary: "" });
  const [debugLines, setDebugLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const requestData = useCallback(() => {
    if (sendMessage) {
      sendMessage("confirm_card", {
        section_id: "diagnostics",
        card_id: "diagnostics_refresh",
        action: "refresh",
        values: {},
      });
    }
  }, [sendMessage]);

  // Handle incoming field updates via iris:ws_message
  useEffect(() => {
    const handler = (event: any) => {
      const detail = event.detail;
      if (!detail || detail.type !== "update_field") return;
      const payload = detail.payload || {};
      const fieldId = payload.field_id;
      const value = payload.value;

      try {
        const parsed = typeof value === "string" ? JSON.parse(value) : value;

        if (fieldId === "system_health" && Array.isArray(parsed)) {
          setHealthChecks(parsed);
          setLoading(false);
        } else if (fieldId === "troubleshoot" && parsed) {
          if (Array.isArray(parsed)) {
            // Legacy format: array of strings
            setTroubleshoot({
              issues: parsed.filter((s: string) => s.startsWith("ERROR") || s.startsWith("ISSUE")),
              warnings: parsed.filter((s: string) => s.startsWith("WARN") || s.startsWith("NOTE")),
              summary: parsed[0] || "",
            });
          } else {
            setTroubleshoot(parsed);
          }
        } else if (fieldId === "debug_info") {
          if (Array.isArray(parsed)) {
            setDebugLines(parsed);
          } else if (typeof parsed === "string") {
            setDebugLines(parsed.split("\n"));
          }
        }
      } catch {
        if (fieldId === "system_health" && typeof value === "string") {
          // Legacy text format — skip
        }
        if (fieldId === "debug_info" && typeof value === "string") {
          setDebugLines(value.split("\n"));
        }
      }
    };
    window.addEventListener("iris:ws_message", handler);
    return () => window.removeEventListener("iris:ws_message", handler);
  }, []);

  // Request on mount
  useEffect(() => {
    requestData();
  }, [requestData]);

  // Count statuses
  const counts = useMemo(() => {
    const c = { healthy: 0, warning: 0, error: 0, idle: 0 };
    healthChecks.forEach(h => { c[h.status]++; });
    return c;
  }, [healthChecks]);

  return (
    <div className="w-full h-full overflow-y-auto overflow-x-hidden p-2 space-y-2 scrollbar-hide antialiased">
      {/* Minimal refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {counts.error > 0 && (
            <span className="text-[8px] font-bold px-1.5 py-0.5 rounded" style={{ color: "#f87171", background: "rgba(239,68,68,0.1)" }}>
              {counts.error} ERR
            </span>
          )}
          {counts.warning > 0 && (
            <span className="text-[8px] font-bold px-1.5 py-0.5 rounded" style={{ color: "#fbbf24", background: "rgba(251,191,36,0.1)" }}>
              {counts.warning} WARN
            </span>
          )}
          {counts.healthy > 0 && (
            <span className="text-[8px] font-bold px-1.5 py-0.5 rounded" style={{ color: "#22c55e", background: "rgba(34,197,94,0.1)" }}>
              {counts.healthy} OK
            </span>
          )}
        </div>
        <button
          onClick={requestData}
          className="p-1 rounded hover:bg-white/5 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={10} className="text-white/40 hover:text-white/70" />
        </button>
      </div>

      {/* System Health */}
      <DiagSection title={`System Health · ${healthChecks.length} checks`} icon={Activity} glowColor={glowColor}>
        {loading && healthChecks.length === 0 ? (
          <div className="py-3 text-center">
            <span className="text-[10px] text-white/30 italic">Running health checks...</span>
          </div>
        ) : healthChecks.length === 0 ? (
          <div className="py-3 text-center">
            <span className="text-[10px] text-white/30 italic">No health data available</span>
          </div>
        ) : (
          <div className="space-y-0.5">
            {healthChecks.map((check, i) => (
              <HealthRow key={check.component} check={check} index={i} />
            ))}
          </div>
        )}
      </DiagSection>

      {/* Troubleshoot */}
      <DiagSection title="Issues & Warnings" icon={AlertTriangle} glowColor={troubleshoot.issues.length > 0 ? "#ef4444" : "#fbbf24"}>
        {troubleshoot.issues.length === 0 && troubleshoot.warnings.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 py-2 px-2"
            style={{ background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: 4 }}
          >
            <CheckCircle size={11} style={{ color: "#22c55e" }} />
            <span className="text-[10px]" style={{ color: "rgba(34,197,94,0.9)" }}>
              {troubleshoot.summary || "All checks passed. Ready for inference."}
            </span>
          </motion.div>
        ) : (
          <div className="space-y-1.5">
            {troubleshoot.issues.map((issue, i) => (
              <IssueCard key={`issue-${i}`} severity="error" text={issue.replace(/^(ERROR|ISSUE):?\s*/, "")} delay={i * 0.05} />
            ))}
            {troubleshoot.warnings.map((warn, i) => (
              <IssueCard key={`warn-${i}`} severity="warning" text={warn.replace(/^(WARN|NOTE):?\s*/, "")} delay={(troubleshoot.issues.length + i) * 0.05} />
            ))}
          </div>
        )}
      </DiagSection>

      {/* Debug Info */}
      <DiagSection title="Debug Info" icon={Bug} glowColor="#a78bfa">
        {debugLines.length === 0 ? (
          <div className="py-2 text-center">
            <span className="text-[10px] text-white/30 italic">No debug info available</span>
          </div>
        ) : (
          <div
            className="font-mono text-[9px] leading-relaxed p-2 rounded space-y-0.5 overflow-x-auto scrollbar-hide min-w-0"
            style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(167,139,250,0.1)" }}
          >
            {debugLines.map((line, i) => {
              const colonIdx = line.indexOf(":");
              const key = colonIdx > 0 ? line.slice(0, colonIdx + 1) : "";
              const val = colonIdx > 0 ? line.slice(colonIdx + 1).trim() : line;
              return (
                <div key={i} className="flex gap-1.5 min-w-0">
                  {key && <span className="text-white/30 flex-shrink-0">{key}</span>}
                  <span style={{ color: "rgba(167,139,250,0.9)" }} className="break-all min-w-0">{val}</span>
                </div>
              );
            })}
          </div>
        )}
      </DiagSection>
    </div>
  );
}
