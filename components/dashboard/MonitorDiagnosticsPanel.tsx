"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Activity, AlertTriangle, CheckCircle,
  XCircle, Bug, RefreshCw, Info,
} from "lucide-react";
import { Xur } from "@/components/Xur";

interface MonitorDiagnosticsPanelProps {
  glowColor?: string;
  fontColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
}

// ── Health Row ───────────────────────────────────────────────────────────────

function HealthRow({
  label,
  value,
  status,
  glowColor,
  delay = 0,
}: {
  label: string;
  value: string;
  status: "healthy" | "warning" | "error" | "idle";
  glowColor: string;
  delay?: number;
}) {
  const statusColor =
    status === "healthy" ? "#22c55e" :
    status === "warning" ? "#fbbf24" :
    status === "error" ? "#ef4444" :
    "rgba(255,255,255,0.3)";

  const StatusIcon =
    status === "healthy" ? CheckCircle :
    status === "warning" ? AlertTriangle :
    status === "error" ? XCircle :
    Activity;

  return (
    <motion.div
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay }}
      className="flex items-center gap-2 py-1 px-1.5 rounded-md hover:bg-white/[0.02] transition-colors min-w-0"
    >
      {/* Pulsing status dot */}
      <div className="relative flex-shrink-0 w-[8px] h-[8px]">
        <motion.div
          className="absolute inset-0 rounded-full"
          style={{ background: statusColor }}
          animate={{ opacity: [1, 0.4, 1] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        />
        {status === "healthy" && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{ background: statusColor }}
            animate={{ scale: [1, 1.8, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeOut" }}
          />
        )}
      </div>

      {/* Label */}
      <span className="text-[9px] text-white/40 uppercase tracking-wide flex-shrink-0 w-[72px] truncate">
        {label}
      </span>

      {/* Value */}
      <span
        className="text-[10px] font-medium tabular-nums truncate flex-1 min-w-0"
        style={{ color: status === "idle" ? "rgba(255,255,255,0.5)" : glowColor }}
      >
        {value}
      </span>

      {/* Status icon */}
      <StatusIcon size={10} style={{ color: statusColor, flexShrink: 0 }} />
    </motion.div>
  );
}

// ── Issue Card ───────────────────────────────────────────────────────────────

function IssueCard({
  severity,
  text,
  glowColor,
  delay = 0,
}: {
  severity: "error" | "warning" | "info";
  text: string;
  glowColor: string;
  delay?: number;
}) {
  const color =
    severity === "error" ? "#ef4444" :
    severity === "warning" ? "#fbbf24" :
    glowColor;

  const Icon =
    severity === "error" ? XCircle :
    severity === "warning" ? AlertTriangle :
    Info;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay }}
      className="flex items-start gap-2 py-1.5 px-2 rounded-md"
      style={{
        background: `${color}08`,
        border: `1px solid ${color}15`,
      }}
    >
      <Icon size={10} style={{ color, marginTop: 1, flexShrink: 0 }} />
      <span className="text-[10px] leading-relaxed break-words" style={{ color: `${color}cc` }}>
        {text}
      </span>
    </motion.div>
  );
}

// ── Section Container ────────────────────────────────────────────────────────

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
      className="rounded-lg border overflow-hidden min-w-0"
      style={{
        borderColor: `${glowColor}12`,
        background: "linear-gradient(180deg, rgba(5,5,12,0.5) 0%, rgba(8,9,16,0.3) 100%)",
      }}
    >
      <div
        className="flex items-center gap-1.5 px-2.5 py-1.5 border-b"
        style={{ borderColor: `${glowColor}08` }}
      >
        <Icon size={11} style={{ color: glowColor }} />
        <span className="text-[9px] font-bold uppercase tracking-wider text-white/50 truncate">{title}</span>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

// ── Parse diagnostics text into structured data ──────────────────────────────

function parseHealthLines(text: string): { label: string; value: string; status: "healthy" | "warning" | "error" | "idle" }[] {
  if (!text) return [];
  const lines = text.split("\n").filter((l) => l.trim());
  return lines.map((line) => {
    const colonIdx = line.indexOf(":");
    const label = colonIdx > 0 ? line.slice(0, colonIdx).trim() : line.trim();
    const value = colonIdx > 0 ? line.slice(colonIdx + 1).trim() : "";

    let status: "healthy" | "warning" | "error" | "idle" = "healthy";
    const lower = value.toLowerCase();
    if (lower.includes("error") || lower.includes("fail") || lower.includes("offline") || lower.includes("not running")) {
      status = "error";
    } else if (lower.includes("warn") || lower.includes("degrad") || lower.includes("slow")) {
      status = "warning";
    } else if (!value || lower.includes("none") || lower.includes("n/a")) {
      status = "idle";
    }

    return { label, value: value || "—", status };
  });
}

function parseIssues(text: string): { severity: "error" | "warning" | "info"; text: string }[] {
  if (!text) return [];
  const lines = text.split("\n").filter((l) => l.trim());
  if (lines.length === 1 && (lines[0].toLowerCase().includes("no issue") || lines[0].toLowerCase().includes("none"))) {
    return [];
  }
  return lines.map((line) => {
    const lower = line.toLowerCase();
    let severity: "error" | "warning" | "info" = "info";
    if (lower.includes("error") || lower.includes("critical") || lower.includes("fail")) {
      severity = "error";
    } else if (lower.includes("warn") || lower.includes("caution")) {
      severity = "warning";
    }
    return { severity, text: line.replace(/^[\s\-\*•]+/, "").trim() };
  });
}

// ── Main Panel ───────────────────────────────────────────────────────────────

export function MonitorDiagnosticsPanel({ glowColor = "#00d4ff", fontColor = "white", sendMessage }: MonitorDiagnosticsPanelProps) {
  const [healthText, setHealthText] = useState("");
  const [troubleshootText, setTroubleshootText] = useState("");
  const [debugText, setDebugText] = useState("");
  const [loading, setLoading] = useState(true);

  const requestData = useCallback(() => {
    setLoading(true);
    if (sendMessage) {
      sendMessage("confirm_card", { section_id: "diagnostics", values: {} });
    }
  }, [sendMessage]);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent;
      const { type, payload } = ce.detail || {};

      if (type === "update_field") {
        const p = payload || {};
        if (p.field_id === "system_health") {
          setHealthText(p.value || "");
          setLoading(false);
        } else if (p.field_id === "troubleshoot") {
          setTroubleshootText(p.value || "");
        } else if (p.field_id === "debug_info") {
          setDebugText(p.value || "");
        }
      }
    };

    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  useEffect(() => {
    requestData();
    const interval = setInterval(requestData, 15000);
    return () => clearInterval(interval);
  }, [requestData]);

  const healthRows = parseHealthLines(healthText);
  const issues = parseIssues(troubleshootText);
  const debugLines = debugText ? debugText.split("\n").filter((l) => l.trim()) : [];

  if (loading && !healthText) {
    return (
      <div className="w-full h-full flex items-center justify-center p-8">
        <div className="flex flex-col items-center gap-3">
          <Xur size={28} color={glowColor} speed={1.2} />
          <span className="text-[11px] text-white/40">Running diagnostics...</span>
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

      {/* System Health */}
      <DiagSection title="System Health" icon={Activity} glowColor={glowColor}>
        {healthRows.length === 0 ? (
          <div className="py-3 text-center">
            <span className="text-[10px] text-white/30 italic">No health data available</span>
          </div>
        ) : (
          healthRows.map((row, i) => (
            <HealthRow
              key={i}
              label={row.label}
              value={row.value}
              status={row.status}
              glowColor={glowColor}
              delay={i * 0.03}
            />
          ))
        )}
      </DiagSection>

      {/* Troubleshoot */}
      <DiagSection title="Issues & Warnings" icon={AlertTriangle} glowColor={glowColor}>
        {issues.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 py-2 px-2"
          >
            <CheckCircle size={11} style={{ color: "#22c55e" }} />
            <span className="text-[10px] text-white/40">No issues detected — all systems nominal</span>
          </motion.div>
        ) : (
          <div className="space-y-1">
            {issues.map((issue, i) => (
              <IssueCard
                key={i}
                severity={issue.severity}
                text={issue.text}
                glowColor={glowColor}
                delay={i * 0.05}
              />
            ))}
          </div>
        )}
      </DiagSection>

      {/* Debug Info */}
      <DiagSection title="Debug Info" icon={Bug} glowColor={glowColor}>
        {debugLines.length === 0 ? (
          <div className="py-2 text-center">
            <span className="text-[10px] text-white/30 italic">No debug info available</span>
          </div>
        ) : (
          <div
            className="font-mono text-[9px] leading-relaxed p-2 rounded space-y-0.5 overflow-x-auto scrollbar-hide"
            style={{ background: "rgba(0,0,0,0.3)" }}
          >
            {debugLines.map((line, i) => {
              const colonIdx = line.indexOf(":");
              const key = colonIdx > 0 ? line.slice(0, colonIdx + 1) : "";
              const val = colonIdx > 0 ? line.slice(colonIdx + 1).trim() : line;
              return (
                <div key={i} className="flex gap-1.5 min-w-0">
                  {key && <span className="text-white/30 flex-shrink-0">{key}</span>}
                  <span style={{ color: `${glowColor}cc` }} className="break-all min-w-0">{val}</span>
                </div>
              );
            })}
          </div>
        )}
      </DiagSection>
    </div>
  );
}

export default MonitorDiagnosticsPanel;
