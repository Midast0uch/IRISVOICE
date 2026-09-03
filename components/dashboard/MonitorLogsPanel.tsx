"use client";

import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, Info, Bug, RefreshCw, Search, X, Filter, ArrowDown, Terminal } from "lucide-react";

interface MonitorLogsPanelProps {
  glowColor?: string;
  fontColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
}

type LogLevel = "ALL" | "INFO" | "WARNING" | "ERROR" | "DEBUG";

interface LogEntry {
  timestamp: string;
  level: string;
  source: string;
  message: string;
}

// ── Log entry colors ─────────────────────────────────────────────────────────

function getLevelStyle(level: string) {
  const lvl = level.toUpperCase();
  if (lvl === "ERROR" || lvl === "CRITICAL" || lvl === "FATAL") {
    return { color: "#ef4444", bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.15)" };
  }
  if (lvl === "WARN" || lvl === "WARNING") {
    return { color: "#fbbf24", bg: "rgba(251,191,36,0.08)", border: "rgba(251,191,36,0.15)" };
  }
  if (lvl === "DEBUG" || lvl === "TRACE") {
    return { color: "#a78bfa", bg: "rgba(167,139,250,0.08)", border: "rgba(167,139,250,0.15)" };
  }
  return { color: glowColorVal, bg: "rgba(34,197,94,0.06)", border: "rgba(34,197,94,0.12)" };
}

const glowColorVal = "#22c55e";

// ── Format timestamp ──────────────────────────────────────────────────────────

function formatTs(ts: string): string {
  if (!ts) return "--:--:--";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts.slice(11, 19) || ts.slice(-8) || "--:--:--";
    return d.toTimeString().slice(0, 8);
  } catch {
    return ts.slice(-8) || "--:--:--";
  }
}

// ── Single log line ───────────────────────────────────────────────────────────

function LogLine({ entry, glowColor }: { entry: LogEntry; glowColor: string }) {
  const style = useMemo(() => {
    const lvl = entry.level.toUpperCase();
    if (lvl.includes("ERROR") || lvl.includes("CRITICAL") || lvl.includes("FATAL")) {
      return { color: "#f87171", bar: "#ef4444" };
    }
    if (lvl.includes("WARN")) {
      return { color: "#fbbf24", bar: "#fbbf24" };
    }
    if (lvl.includes("DEBUG") || lvl.includes("TRACE")) {
      return { color: "#a78bfa", bar: "#a78bfa" };
    }
    return { color: "rgba(255,255,255,0.7)", bar: glowColor };
  }, [entry.level, glowColor]);

  return (
    <div
      className="group flex items-start gap-2 py-1.5 px-3 hover:bg-white/[0.03] transition-colors border-b border-white/[0.02] min-w-0"
    >
      {/* Color bar */}
      <div
        className="w-[2px] self-stretch rounded-full flex-shrink-0 opacity-60 group-hover:opacity-100 transition-opacity"
        style={{ background: style.bar }}
      />

      {/* Timestamp */}
      <span className="text-[10px] text-white/30 tabular-nums flex-shrink-0 leading-tight pt-[1px]">
        {formatTs(entry.timestamp)}
      </span>

      {/* Level badge */}
      <span
        className="text-[9px] font-bold uppercase tracking-wider flex-shrink-0 leading-tight pt-[1px] w-[44px]"
        style={{ color: style.color }}
      >
        {entry.level}
      </span>

      {/* Source */}
      {entry.source && (
        <span className="text-[9px] text-white/25 uppercase tracking-wider flex-shrink-0 leading-tight pt-[1px] w-[50px] truncate">
          {entry.source}
        </span>
      )}

      {/* Message */}
      <span className="text-[10px] text-white/60 leading-snug break-words min-w-0 flex-1 font-mono">
        {entry.message}
      </span>
    </div>
  );
}

// ── Log section (scrollable) ──────────────────────────────────────────────────

function LogSection({
  title,
  icon: Icon,
  entries,
  glowColor,
  loading,
  onRefresh,
  emptyMsg,
  defaultLevelFilter = "ALL" as LogLevel,
  accentColor,
}: {
  title: string;
  icon: any;
  entries: LogEntry[];
  glowColor: string;
  loading: boolean;
  onRefresh: () => void;
  emptyMsg: string;
  defaultLevelFilter?: LogLevel;
  accentColor?: string;
}) {
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState<LogLevel>(defaultLevelFilter);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Filter entries
  const filtered = useMemo(() => {
    let result = entries;
    if (levelFilter !== "ALL") {
      result = result.filter((e) => {
        const lvl = e.level.toUpperCase();
        if (levelFilter === "INFO") return lvl.includes("INFO") || (!lvl.includes("ERROR") && !lvl.includes("WARN") && !lvl.includes("DEBUG"));
        return lvl.includes(levelFilter);
      });
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (e) =>
          e.message.toLowerCase().includes(q) ||
          e.source.toLowerCase().includes(q) ||
          e.level.toLowerCase().includes(q)
      );
    }
    return result;
  }, [entries, levelFilter, search]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered, autoScroll]);

  // Count by level
  const counts = useMemo(() => {
    const c = { ERROR: 0, WARNING: 0, INFO: 0, DEBUG: 0 };
    entries.forEach((e) => {
      const lvl = e.level.toUpperCase();
      if (lvl.includes("ERROR")) c.ERROR++;
      else if (lvl.includes("WARN")) c.WARNING++;
      else if (lvl.includes("DEBUG")) c.DEBUG++;
      else c.INFO++;
    });
    return c;
  }, [entries]);

  const sectionColor = accentColor || glowColor;

  return (
    <div
      className="rounded-md border overflow-hidden min-w-0 flex flex-col"
      style={{
        borderColor: `${sectionColor}15`,
        background: `linear-gradient(180deg, rgba(5,5,12,0.5) 0%, rgba(8,9,16,0.3) 100%)`,
      }}
    >
      {/* Header row */}
      <div
        className="flex items-center justify-between px-3 py-2 border-b flex-shrink-0"
        style={{ borderColor: `${sectionColor}10` }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={11} style={{ color: sectionColor }} />
          <span className="text-[10px] font-bold uppercase tracking-wider text-white/60 truncate">
            {title}
          </span>
          <span
            className="text-[9px] tabular-nums px-1.5 py-0.5 rounded-full flex-shrink-0"
            style={{ background: `${sectionColor}15`, color: sectionColor }}
          >
            {filtered.length}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {counts.ERROR > 0 && (
            <span className="text-[8px] font-bold px-1 rounded" style={{ color: "#f87171", background: "rgba(239,68,68,0.1)" }}>
              {counts.ERROR}E
            </span>
          )}
          {counts.WARNING > 0 && (
            <span className="text-[8px] font-bold px-1 rounded" style={{ color: "#fbbf24", background: "rgba(251,191,36,0.1)" }}>
              {counts.WARNING}W
            </span>
          )}
          <button
            onClick={onRefresh}
            className="p-1 rounded hover:bg-white/5 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={10} className="text-white/40 hover:text-white/70" />
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div
        className="flex items-center gap-1.5 px-2 py-1.5 border-b flex-shrink-0"
        style={{ borderColor: `${sectionColor}08` }}
      >
        {/* Level chips */}
        {(["ALL", "ERROR", "WARNING", "INFO", "DEBUG"] as LogLevel[]).map((lvl) => {
          const isActive = levelFilter === lvl;
          const chipColor =
            lvl === "ERROR" ? "#ef4444" :
            lvl === "WARNING" ? "#fbbf24" :
            lvl === "DEBUG" ? "#a78bfa" :
            sectionColor;
          return (
            <button
              key={lvl}
              onClick={() => setLevelFilter(lvl)}
              className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded transition-colors"
              style={{
                background: isActive ? `${chipColor}20` : "rgba(255,255,255,0.03)",
                color: isActive ? chipColor : "rgba(255,255,255,0.4)",
                border: `1px solid ${isActive ? chipColor + "40" : "rgba(255,255,255,0.05)"}`,
              }}
            >
              {lvl}
            </button>
          );
        })}

        {/* Search */}
        <div className="flex-1 min-w-0 relative ml-1">
          <Search size={9} className="absolute left-1.5 top-1/2 -translate-y-1/2 text-white/25" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter..."
            className="w-full bg-white/[0.03] border border-white/[0.05] rounded pl-5 pr-5 py-0.5 text-[9px] text-white/70 placeholder:text-white/20 focus:outline-none focus:border-white/10"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-white/5"
            >
              <X size={9} className="text-white/30" />
            </button>
          )}
        </div>
      </div>

      {/* Scrollable log area */}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden scrollbar-hide"
        style={{ maxHeight: "240px" }}
      >
        {loading && entries.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <span className="text-[10px] text-white/30">Loading logs...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <span className="text-[10px] text-white/30 italic">{emptyMsg}</span>
          </div>
        ) : (
          filtered.map((entry, i) => (
            <LogLine key={`${entry.timestamp}-${i}`} entry={entry} glowColor={glowColor} />
          ))
        )}
      </div>

      {/* Footer with auto-scroll toggle */}
      <div
        className="flex items-center justify-between px-2 py-1 border-t flex-shrink-0"
        style={{ borderColor: `${sectionColor}08` }}
      >
        <button
          onClick={() => setAutoScroll(!autoScroll)}
          className="flex items-center gap-1 text-[8px] uppercase tracking-wider font-bold transition-colors"
          style={{ color: autoScroll ? sectionColor : "rgba(255,255,255,0.3)" }}
        >
          <ArrowDown size={8} className={autoScroll ? "" : "opacity-40"} />
          Auto-scroll {autoScroll ? "ON" : "OFF"}
        </button>
        <span className="text-[8px] text-white/25 tabular-nums">
          {entries.length} total
        </span>
      </div>
    </div>
  );
}

// ── Main Logs Panel ───────────────────────────────────────────────────────────

export function MonitorLogsPanel({
  glowColor = "#22c55e",
  fontColor,
  sendMessage,
}: MonitorLogsPanelProps) {
  const [systemLogs, setSystemLogs] = useState<LogEntry[]>([]);
  const [errorLogs, setErrorLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const requestData = useCallback(() => {
    if (sendMessage) {
      sendMessage("confirm_card", {
        section_id: "logs",
        card_id: "logs_refresh",
        action: "refresh",
        values: {},
      });
    }
  }, [sendMessage]);

  // Handle incoming field updates
  useEffect(() => {
    const handler = (event: any) => {
      const detail = event.detail;
      if (!detail) return;
      if (detail.type !== "update_field") return;
      const payload = detail.payload || {};
      const fieldId = payload.field_id;
      const value = payload.value;

      if (fieldId === "system_logs" && value) {
        try {
          const parsed = typeof value === "string" ? JSON.parse(value) : value;
          if (Array.isArray(parsed)) {
            setSystemLogs(parsed);
            setLoading(false);
          }
        } catch {
          // Fallback: treat as raw text, wrap in single entry
          const lines = (value as string).split("\n").filter((l: string) => l.trim());
          setSystemLogs(
            lines.map((l: string) => ({
              timestamp: "",
              level: l.toUpperCase().includes("ERROR") ? "ERROR" : "INFO",
              source: "system",
              message: l,
            }))
          );
          setLoading(false);
        }
      }
      if (fieldId === "error_logs" && value) {
        try {
          const parsed = typeof value === "string" ? JSON.parse(value) : value;
          if (Array.isArray(parsed)) {
            setErrorLogs(parsed);
          }
        } catch {
          // ignore parse errors for error logs
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

  return (
    <div className="w-full h-full flex flex-col gap-2 p-2 overflow-hidden antialiased">
      {/* System Output */}
      <LogSection
        title="System Output"
        icon={Terminal}
        entries={systemLogs}
        glowColor={glowColor}
        loading={loading}
        onRefresh={requestData}
        emptyMsg="No system output recorded"
        defaultLevelFilter="ALL"
      />

      {/* Error Stream */}
      <LogSection
        title="Error Stream"
        icon={AlertTriangle}
        entries={errorLogs}
        glowColor="#ef4444"
        loading={loading}
        onRefresh={requestData}
        emptyMsg="No errors or warnings — all systems nominal"
        defaultLevelFilter="ALL"
        accentColor="#ef4444"
      />
    </div>
  );
}
