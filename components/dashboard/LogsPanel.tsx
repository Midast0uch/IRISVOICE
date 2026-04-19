"use client"

import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertCircle,
  AlertTriangle,
  Info,
  Bug,
  Trash2,
  Pause,
  Play,
  Download,
  Terminal,
} from "lucide-react";

export type LogLevel = "error" | "warn" | "info" | "debug";

export interface LogEntry {
  id: string;
  timestamp: Date;
  level: LogLevel;
  source: string;
  message: string;
}

interface LogsPanelProps {
  glowColor?: string;
  fontColor?: string;
  logs?: LogEntry[];
  maxLines?: number;
  isConnected?: boolean;
  onClear?: () => void;
  onExport?: () => void;
}

type LogFilter = "all" | LogLevel;

const LOG_LEVELS: { id: LogFilter; label: string; color: string }[] = [
  { id: "all", label: "All", color: "#ffffff" },
  { id: "error", label: "Errors", color: "#ef4444" },
  { id: "warn", label: "Warnings", color: "#fbbf24" },
  { id: "info", label: "Info", color: "#3b82f6" },
  { id: "debug", label: "Debug", color: "#22c55e" },
];

const getLogIcon = (level: LogLevel) => {
  switch (level) {
    case "error":
      return <AlertCircle size={12} />;
    case "warn":
      return <AlertTriangle size={12} />;
    case "info":
      return <Info size={12} />;
    case "debug":
      return <Bug size={12} />;
    default:
      return <Terminal size={12} />;
  }
};

const getLogColor = (level: LogLevel): string => {
  switch (level) {
    case "error":
      return "#ef4444";
    case "warn":
      return "#fbbf24";
    case "info":
      return "#3b82f6";
    case "debug":
      return "#22c55e";
    default:
      return "#ffffff";
  }
};

const formatLogTime = (date: Date): string => {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
};

export function LogsPanel({
  glowColor = "#00d4ff",
  fontColor = "#ffffff",
  logs = [],
  maxLines = 1000,
  isConnected = true,
  onClear,
  onExport,
}: LogsPanelProps) {
  const [filter, setFilter] = useState<LogFilter>("all");
  const [isPaused, setIsPaused] = useState(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wasAtBottom = useRef(true);

  const filteredLogs =
    filter === "all" ? logs : logs.filter((log) => log.level === filter);

  // Auto-scroll to bottom unless user has scrolled up
  useEffect(() => {
    if (isPaused) return;

    const container = scrollRef.current;
    if (!container) return;

    if (wasAtBottom.current) {
      container.scrollTop = container.scrollHeight;
    }
  }, [filteredLogs, isPaused]);

  // Track scroll position
  const handleScroll = () => {
    const container = scrollRef.current;
    if (!container) return;

    const isAtBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight <
      50;
    wasAtBottom.current = isAtBottom;
    setShowScrollButton(!isAtBottom && filteredLogs.length > 0);
  };

  const scrollToBottom = () => {
    const container = scrollRef.current;
    if (container) {
      container.scrollTop = container.scrollHeight;
      wasAtBottom.current = true;
      setShowScrollButton(false);
    }
  };

  const handleClear = () => {
    if (onClear) {
      onClear();
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Filter Tabs - 28px height */}
      <div
        className="h-7 flex items-center px-2 gap-0.5 border-b flex-shrink-0"
        style={{ borderColor: `${glowColor}15` }}
      >
        {LOG_LEVELS.map((level) => (
          <button
            key={level.id}
            onClick={() => setFilter(level.id)}
            className="px-2.5 py-1 rounded text-[10px] font-medium transition-all duration-150"
            style={{
              color: filter === level.id ? level.color : `${fontColor}50`,
              backgroundColor:
                filter === level.id ? `${level.color}15` : "transparent",
            }}
            onMouseEnter={(e) => {
              if (filter !== level.id) {
                e.currentTarget.style.color = `${fontColor}70`;
              }
            }}
            onMouseLeave={(e) => {
              if (filter !== level.id) {
                e.currentTarget.style.color = `${fontColor}50`;
              }
            }}
          >
            {level.label}
          </button>
        ))}
      </div>

      {/* Toolbar - 32px height */}
      <div
        className="h-8 flex items-center justify-between px-3 border-b"
        style={{ borderColor: `${glowColor}10` }}
      >
        <div className="flex items-center gap-2">
          {/* Connection status */}
          <div className="flex items-center gap-1.5">
            <motion.div
              className="w-1.5 h-1.5 rounded-full"
              style={{
                backgroundColor: isConnected ? "#22c55e" : "#ef4444",
              }}
              animate={{
                opacity: isConnected ? [1, 0.5, 1] : 1,
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
              }}
            />
            <span className="text-[9px]" style={{ color: `${fontColor}40` }}>
              {isConnected ? "Live" : "Disconnected"}
            </span>
          </div>

          {/* Line count */}
          <span className="text-[9px]" style={{ color: `${fontColor}30` }}>
            | {filteredLogs.length} lines
            {logs.length > maxLines && ` (${logs.length} total)`}
          </span>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-1">
          {/* Pause/Resume */}
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="p-1.5 rounded transition-all duration-150"
            style={{
              color: isPaused ? "#fbbf24" : `${fontColor}50`,
              backgroundColor: isPaused ? "rgba(251, 191, 36, 0.1)" : "transparent",
            }}
            title={isPaused ? "Resume" : "Pause"}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = isPaused
                ? "#fbbf24"
                : `${fontColor}70`;
              e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = isPaused
                ? "#fbbf24"
                : `${fontColor}50`;
              e.currentTarget.style.backgroundColor = isPaused
                ? "rgba(251, 191, 36, 0.1)"
                : "transparent";
            }}
          >
            {isPaused ? <Play size={12} /> : <Pause size={12} />}
          </button>

          {/* Clear */}
          <button
            onClick={handleClear}
            className="p-1.5 rounded transition-all duration-150"
            style={{ color: `${fontColor}50` }}
            title="Clear logs"
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "#ef4444";
              e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = `${fontColor}50`;
              e.currentTarget.style.backgroundColor = "transparent";
            }}
          >
            <Trash2 size={12} />
          </button>

          {/* Export */}
          {onExport && (
            <button
              onClick={onExport}
              className="p-1.5 rounded transition-all duration-150"
              style={{ color: `${fontColor}50` }}
              title="Export logs"
              onMouseEnter={(e) => {
                e.currentTarget.style.color = glowColor;
                e.currentTarget.style.backgroundColor =
                  "rgba(255,255,255,0.05)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = `${fontColor}50`;
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <Download size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Log Content */}
      <div className="flex-1 relative overflow-hidden">
        {filteredLogs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-4">
            <Terminal
              size={28}
              style={{ color: `${glowColor}25` }}
              className="mb-2"
            />
            <p className="text-[11px]" style={{ color: `${fontColor}35` }}>
              {filter === "all"
                ? "No logs available"
                : `No ${filter} logs`}
            </p>
          </div>
        ) : (
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="h-full overflow-y-auto p-2 space-y-0.5 font-mono"
            style={{
              backgroundColor: "rgba(0,0,0,0.2)",
              fontSize: "9px",
              lineHeight: "1.5",
            }}
          >
            {filteredLogs.map((log) => (
              <div
                key={log.id}
                className="flex items-start gap-2 py-0.5 px-1 rounded hover:bg-white/[0.03] transition-colors"
              >
                {/* Timestamp */}
                <span
                  className="flex-shrink-0 tabular-nums"
                  style={{ color: `${fontColor}30` }}
                >
                  {formatLogTime(log.timestamp)}
                </span>

                {/* Level Icon */}
                <span
                  className="flex-shrink-0"
                  style={{ color: getLogColor(log.level) }}
                >
                  {getLogIcon(log.level)}
                </span>

                {/* Source */}
                <span
                  className="flex-shrink-0 w-20 truncate"
                  style={{ color: `${glowColor}60` }}
                >
                  [{log.source}]
                </span>

                {/* Message */}
                <span
                  className="flex-1 break-all"
                  style={{ color: `${fontColor}80` }}
                >
                  {log.message}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Scroll to bottom button */}
        <AnimatePresence>
          {showScrollButton && (
            <motion.button
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              onClick={scrollToBottom}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full text-[9px] font-medium flex items-center gap-1.5 transition-all duration-150"
              style={{
                backgroundColor: "rgba(10,10,20,0.95)",
                color: glowColor,
                border: `1px solid ${glowColor}30`,
                boxShadow: `0 2px 8px rgba(0,0,0,0.5)`,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = `${glowColor}20`;
                e.currentTarget.style.borderColor = `${glowColor}50`;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = "rgba(10,10,20,0.95)";
                e.currentTarget.style.borderColor = `${glowColor}30`;
              }}
            >
              <Play size={10} className="rotate-90" />
              Scroll to bottom
            </motion.button>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default LogsPanel;
