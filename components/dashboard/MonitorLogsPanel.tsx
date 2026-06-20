"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Info, Bug, RefreshCw } from "lucide-react";
import { Xur } from "@/components/Xur";

interface MonitorLogsPanelProps {
  glowColor?: string;
  fontColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
}

// ── Log line parser ──────────────────────────────────────────────────────────

interface ParsedLogLine {
  timestamp: string;
  level: "ERROR" | "WARN" | "INFO" | "DEBUG" | "UNKNOWN";
  text: string;
  raw: string;
}

function parseLogLine(line: string): ParsedLogLine {
  // Try to extract timestamp and level from common log formats
  // Format 1: "2024-01-15 10:30:45 - ERROR - message"
  // Format 2: "[10:30:45] ERROR message"
  // Format 3: "10:30:45 ERROR message"
  const tsMatch = line.match(/^(\[?[\d:/\s-:]+\]?)/);
  const levelMatch = line.match(/\b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|CRITICAL|FATAL)\b/i);

  const timestamp = tsMatch ? tsMatch[1].replace(/[\[\]]/g, "") : "";
  const rawLevel = levelMatch ? levelMatch[1].toUpperCase() : "UNKNOWN";
  const level = rawLevel === "WARNING" ? "WARN" : rawLevel === "TRACE" || rawLevel === "CRITICAL" || rawLevel === "FATAL" ? "ERROR" : (rawLevel as any);

  // Remove timestamp and level from the text
  let text = line;
  if (tsMatch) text = text.replace(tsMatch[0], "").replace(/^[\s\-\]]+/, "");
  if (levelMatch) text = text.replace(levelMatch[0], "").replace(/^[\s\-\]]+/, "");

  return { timestamp, level, text: text || line, raw: line };
}

function getLevelColor(level: string, glowColor: string): string {
  switch (level) {
    case "ERROR":
    case "CRITICAL":
    case "FATAL":
      return "#ef4444";
    case "WARN":
    case "WARNING":
      return "#fbbf24";
    case "INFO":
      return glowColor;
    case "DEBUG":
    case "TRACE":
      return "rgba(255,255,255,0.35)";
    default:
      return "rgba(255,255,255,0.5)";
  }
}

function getLevelIcon(level: string) {
  switch (level) {
    case "ERROR":
    case "CRITICAL":
    case "FATAL":
      return AlertTriangle;
    case "WARN":
    case "WARNING":
      return AlertTriangle;
    case "INFO":
      return Info;
    case "DEBUG":
    case "TRACE":
      return Bug;
    default:
      return Info;
  }
}

// ── Log Section ──────────────────────────────────────────────────────────────

function LogSection({
  title,
  icon: Icon,
  logs,
  glowColor,
  loading,
  onRefresh,
}: {
  title: string;
  icon: any;
  logs: string;
  glowColor: string;
  loading: boolean;
  onRefresh: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lines = logs ? logs.split("\n").filter((l) => l.trim()) : [];
  const parsed = lines.map(parseLogLine);

  // Auto-scroll to bottom (latest logs)
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div
      className="rounded-lg border overflow-hidden flex flex-col"
      style={{
        borderColor: `${glowColor}12`,
        background: "linear-gradient(180deg, rgba(3,4,10,0.8) 0%, rgba(6,7,14,0.6) 100%)",
      }}
    >
      {/* Section header */}
      <div
        className="flex items-center justify-between px-3 py-2 border-b flex-shrink-0"
        style={{ borderColor: `${glowColor}08` }}
      >
        <div className="flex items-center gap-1.5">
          <Icon size={11} style={{ color: glowColor }} />
          <span className="text-[10px] font-bold uppercase tracking-wider text-white/50">{title}</span>
          <span
            className="text-[9px] tabular-nums px-1.5 py-0.5 rounded-full"
            style={{ background: `${glowColor}10`, color: `${glowColor}90` }}
          >
            {parsed.length}
          </span>
        </div>
        <button
          onClick={onRefresh}
          className="p-0.5 rounded hover:bg-white/5 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={10} className="text-white/30 hover:text-white/60" />
        </button>
      </div>

      {/* Log content — terminal style */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto scrollbar-hide max-h-[200px] min-h-[60px] relative"
        style={{
          background: "rgba(0,0,0,0.3)",
        }}
      >
        {/* Scanline overlay */}
        <div
          className="absolute inset-0 pointer-events-none z-10"
          style={{
            background: `repeating-linear-gradient(
              0deg,
              transparent,
              transparent 2px,
              ${glowColor}02 2px,
              ${glowColor}02 3px
            )`,
          }}
        />

        {loading && parsed.length === 0 ? (
          <div className="flex items-center justify-center py-6">
            <Xur size={20} color={glowColor} speed={1.5} />
          </div>
        ) : parsed.length === 0 ? (
          <div className="flex items-center justify-center py-6">
            <span className="text-[10px] text-white/20 italic">No logs available</span>
          </div>
        ) : (
          <div className="font-mono text-[10px] leading-relaxed p-2 space-y-0.5 relative z-20">
            {parsed.map((line, i) => {
              const LevelIcon = getLevelIcon(line.level);
              const color = getLevelColor(line.level, glowColor);
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15, delay: Math.min(i * 0.01, 0.3) }}
                  className="flex items-start gap-1.5 py-0.5"
                >
                  {/* Line number */}
                  <span className="text-white/15 tabular-nums select-none w-[24px] flex-shrink-0 text-right">
                    {i + 1}
                  </span>

                  {/* Level icon */}
                  <LevelIcon
                    size={9}
                    style={{ color, marginTop: 2, flexShrink: 0 }}
                  />

                  {/* Timestamp */}
                  {line.timestamp && (
                    <span className="text-white/25 tabular-nums flex-shrink-0">{line.timestamp}</span>
                  )}

                  {/* Log text */}
                  <span
                    className="break-all whitespace-pre-wrap"
                    style={{ color }}
                  >
                    {line.text}
                  </span>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Panel ───────────────────────────────────────────────────────────────

export function MonitorLogsPanel({ glowColor = "#00d4ff", fontColor = "white", sendMessage }: MonitorLogsPanelProps) {
  const [systemLogs, setSystemLogs] = useState("");
  const [errorLogs, setErrorLogs] = useState("");
  const [loading, setLoading] = useState(true);

  const requestData = useCallback(() => {
    setLoading(true);
    if (sendMessage) {
      sendMessage("confirm_card", { section_id: "logs", values: {} });
    }
  }, [sendMessage]);

  // Listen for update_field messages for logs
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent;
      const { type, payload } = ce.detail || {};

      if (type === "update_field") {
        const p = payload || {};
        if (p.section_id === "logs" || p.field_id === "system_logs") {
          if (p.field_id === "system_logs") {
            setSystemLogs(p.value || "");
            setLoading(false);
          } else if (p.field_id === "error_logs") {
            setErrorLogs(p.value || "");
          }
        }
      }
    };

    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  // Auto-request on mount + refresh every 15s
  useEffect(() => {
    requestData();
    const interval = setInterval(requestData, 15000);
    return () => clearInterval(interval);
  }, [requestData]);

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

      {/* System Logs */}
      <LogSection
        title="System Output"
        icon={Info}
        logs={systemLogs}
        glowColor={glowColor}
        loading={loading}
        onRefresh={requestData}
      />

      {/* Error Logs */}
      <LogSection
        title="Error Stream"
        icon={AlertTriangle}
        logs={errorLogs || systemLogs}
        glowColor={glowColor}
        loading={loading}
        onRefresh={requestData}
      />
    </div>
  );
}

export default MonitorLogsPanel;
