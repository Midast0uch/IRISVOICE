"use client";

// Data layer of the one Monitor page (docs/architecture/MONITOR.md).
// Each hook owns ONE source; MonitorPage renders every value from exactly one
// of them. The logic here was moved out of the old tabbed panels
// (MonitorAnalyticsPanel, MonitorLogsPanel, MonitorDiagnosticsPanel,
// InferenceConsolePanel, DCPStatsPanel) so no value is read twice.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Send = ((type: string, payload?: any) => boolean) | undefined;

// ── Formatting ───────────────────────────────────────────────────────────────

export function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function fmtClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function shortModel(model: string): string {
  const parts = model.split(/[\\/]/);
  const name = parts[parts.length - 1] || model;
  return name.length > 32 ? name.slice(0, 29) + "…" : name;
}

// ── Inference stream + Now (WS: inference_event, model_load_event) ───────────

export type StreamEntry =
  | { kind: "call"; id: number; ts: number; model: string; promptTok: number; compTok: number; tps: number; latencyMs: number }
  | { kind: "load"; id: number; ts: number; action: "loaded" | "unloaded"; model: string; profile: string };

export type StreamFilter = "all" | "calls" | "loads";

const STREAM_CAP = 500;

export function useInferenceStream() {
  const [entries, setEntries] = useState<StreamEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [models, setModels] = useState<Record<string, string>>({});
  const [last, setLast] = useState<{ tps: number; latencyMs: number } | null>(null);
  const [avg, setAvg] = useState({ calls: 0, tpsSum: 0 });
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const seq = useRef(0);

  useEffect(() => {
    const handler = (e: Event) => {
      const { type, payload } = (e as CustomEvent).detail || {};
      if (type === "inference_event") {
        const entry: StreamEntry = {
          kind: "call",
          id: seq.current++,
          ts: payload.timestamp ?? Date.now() / 1000,
          model: payload.model ?? "",
          promptTok: payload.prompt_tokens ?? 0,
          compTok: payload.completion_tokens ?? 0,
          tps: payload.tps ?? 0,
          latencyMs: payload.time_ms ?? 0,
        };
        // Pause freezes the stream list only; Now keeps following live.
        setLast({ tps: entry.tps, latencyMs: entry.latencyMs });
        setAvg((a) => ({ calls: a.calls + 1, tpsSum: a.tpsSum + entry.tps }));
        if (!pausedRef.current) setEntries((prev) => [...prev.slice(-(STREAM_CAP - 1)), entry]);
      } else if (type === "model_load_event") {
        const loaded = payload.action === "loaded";
        const entry: StreamEntry = {
          kind: "load",
          id: seq.current++,
          ts: payload.timestamp ?? Date.now() / 1000,
          action: loaded ? "loaded" : "unloaded",
          model: payload.model ?? "",
          profile: payload.profile ?? "",
        };
        const slot = entry.profile || "model";
        setModels((m) => {
          if (loaded) return { ...m, [slot]: entry.model };
          // An unload without a profile removes whichever slot held that model.
          const next = { ...m };
          for (const k of Object.keys(next)) if (k === slot || (!entry.profile && next[k] === entry.model)) delete next[k];
          return next;
        });
        if (!pausedRef.current) setEntries((prev) => [...prev.slice(-(STREAM_CAP - 1)), entry]);
      }
    };
    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  const clear = useCallback(() => setEntries([]), []);

  const exportJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(entries, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `inference_console_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [entries]);

  const avgTps = avg.calls > 0 ? avg.tpsSum / avg.calls : null;
  return { entries, paused, setPaused, clear, exportJson, models, last, avgTps };
}

// ── Usage (WS: monitor_analytics_data, polled) ───────────────────────────────

export interface ModelBreakdown {
  model: string; total_calls: number; total_tokens: number; estimated_cost: number; percentage: number;
}
export interface AnalyticsData {
  stats: {
    total_calls: number; total_prompt_tokens: number; total_completion_tokens: number; total_tokens: number;
    total_audio_tokens: number; estimated_cost: number; session_duration_minutes: number;
  };
  models: ModelBreakdown[];
  latency: { count: number; min_ms: number; max_ms: number; avg_ms: number; p50_ms: number; p95_ms: number };
}

export function useMonitorAnalytics(sendMessage: Send) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const request = useCallback(() => {
    sendMessage?.("confirm_card", { section_id: "analytics", values: {} });
  }, [sendMessage]);

  useEffect(() => {
    const handler = (e: Event) => {
      const { type, payload } = (e as CustomEvent).detail || {};
      if (type === "monitor_analytics_data") setData(payload);
    };
    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  useEffect(() => {
    request();
    const t = setInterval(request, 10000);
    return () => clearInterval(t);
  }, [request]);

  return { data, refresh: request };
}

// ── Logs (WS: update_field system_logs / error_logs) ─────────────────────────

export interface LogEntry { timestamp: string; level: string; source: string; message: string }

// A log line that mirrors an event the Inference stream already shows. The
// stream is fed by inference_event / model_load_event; these backend lines are
// emitted for the same calls and loads, so Logs hides them:
//   "[InferenceRouter] call done ..."        one per model call  (router.py)
//   "[Timing] process_text_message ..."       one per streamed turn (iris_gateway.py)
//   "[LocalModelManager] ... model unloaded"  one per unload (local_model_manager.py)
const MODEL_CALL_LINE = /^\s*\[(?:InferenceRouter\] call done\b|Timing\] process_text_message\b|LocalModelManager\] (?:In-process model|Model) (?:unloaded|released)\b)/;

export function isModelCallLine(entry: LogEntry): boolean {
  return MODEL_CALL_LINE.test(entry.message || "");
}

function parseList(value: unknown): any[] | null {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value) : value;
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function useMonitorLogs(sendMessage: Send) {
  const [system, setSystem] = useState<LogEntry[]>([]);
  const [errors, setErrors] = useState<LogEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  const request = useCallback(() => {
    sendMessage?.("confirm_card", { section_id: "logs", card_id: "logs_refresh", action: "refresh", values: {} });
  }, [sendMessage]);

  useEffect(() => {
    const handler = (e: Event) => {
      const { type, payload } = (e as CustomEvent).detail || {};
      if (type !== "update_field") return;
      const { field_id: fieldId, value } = payload || {};
      if (!value) return;
      if (fieldId === "system_logs") {
        const list = parseList(value);
        if (list) setSystem(list);
        else if (typeof value === "string") {
          // Raw text fallback: one entry per non-empty line.
          setSystem(value.split("\n").filter((l) => l.trim()).map((l) => ({
            timestamp: "", level: l.toUpperCase().includes("ERROR") ? "ERROR" : "INFO", source: "system", message: l,
          })));
        }
        setLoaded(true);
      } else if (fieldId === "error_logs") {
        const list = parseList(value);
        if (list) setErrors(list);
      }
    };
    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  // The backend sends info lines and warning/error lines as two arrays; the
  // page shows ONE list (level chips cover the old Error Stream), oldest first.
  const { lines, hidden } = useMemo(() => {
    const all = [...errors, ...system].sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || ""));
    const app = all.filter((l) => !isModelCallLine(l));
    return { lines: app, hidden: all.length - app.length };
  }, [system, errors]);

  return { lines, hidden, loaded, refresh: request };
}

// ── Diagnostics (WS: update_field system_health / troubleshoot / debug_info) ─

export type HealthStatus = "healthy" | "warning" | "error" | "idle";
export interface HealthCheck { component: string; status: HealthStatus; message: string; latency_ms: number }
export interface Troubleshoot { issues: string[]; warnings: string[]; summary: string }

export function useMonitorDiagnostics(sendMessage: Send) {
  const [checks, setChecks] = useState<HealthCheck[]>([]);
  const [trouble, setTrouble] = useState<Troubleshoot>({ issues: [], warnings: [], summary: "" });
  const [debug, setDebug] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);

  const request = useCallback(() => {
    sendMessage?.("confirm_card", { section_id: "diagnostics", card_id: "diagnostics_refresh", action: "refresh", values: {} });
  }, [sendMessage]);

  useEffect(() => {
    const handler = (e: Event) => {
      const { type, payload } = (e as CustomEvent).detail || {};
      if (type !== "update_field") return;
      const { field_id: fieldId, value } = payload || {};
      let parsed: any = value;
      try { parsed = typeof value === "string" ? JSON.parse(value) : value; } catch { /* plain text below */ }
      if (fieldId === "system_health" && Array.isArray(parsed)) {
        setChecks(parsed);
        setLoaded(true);
      } else if (fieldId === "troubleshoot" && parsed) {
        if (Array.isArray(parsed)) {
          setTrouble({
            issues: parsed.filter((s: string) => s.startsWith("ERROR") || s.startsWith("ISSUE")),
            warnings: parsed.filter((s: string) => s.startsWith("WARN") || s.startsWith("NOTE")),
            summary: parsed[0] || "",
          });
        } else if (typeof parsed === "object") setTrouble({ issues: [], warnings: [], summary: "", ...parsed });
      } else if (fieldId === "debug_info") {
        if (Array.isArray(parsed)) setDebug(parsed);
        else if (typeof value === "string") setDebug(value.split("\n"));
      }
    };
    window.addEventListener("iris:ws_message", handler as EventListener);
    return () => window.removeEventListener("iris:ws_message", handler as EventListener);
  }, []);

  // Dedupe inside Diagnostics and against Now:
  //  - the backend builds "ERROR [component]: ..." / "WARN [component]: ..."
  //    from health checks the System Health list already shows with an
  //    ERR/WARN badge, so only lines NOT tied to a listed check stay here;
  //  - "Reasoning model:" / "Tool model:" debug lines repeat the models Now shows.
  const view = useMemo(() => {
    const listed = new Set(checks.map((c) => c.component));
    const own = (s: string) => {
      const m = /^(?:ERROR|ISSUE|WARN|NOTE)\s*\[([^\]]+)\]/.exec(s);
      return !(m && listed.has(m[1]));
    };
    return {
      issues: trouble.issues.filter(own),
      warnings: trouble.warnings.filter(own),
      debug: debug.filter((l) => !/^(?:Reasoning|Tool) model:/.test(l)),
    };
  }, [checks, trouble, debug]);

  return { checks, trouble, view, loaded, refresh: request };
}

// ── Context (window event: iris:dcp_pruned) — developer mode only ────────────

export interface DcpEvent {
  input_count: number; output_count: number; dedups: number; errors_purged: number; writes_superseded: number; tokens_saved: number;
}

export function useDcpStats(enabled: boolean) {
  const [s, setS] = useState({ passes: 0, saved: 0, dedups: 0, errors: 0, writes: 0, last: null as DcpEvent | null });
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: Event) => {
      const d = (e as CustomEvent<DcpEvent>).detail;
      if (!d) return;
      setS((p) => ({
        passes: p.passes + 1,
        saved: p.saved + (d.tokens_saved ?? 0),
        dedups: p.dedups + (d.dedups ?? 0),
        errors: p.errors + (d.errors_purged ?? 0),
        writes: p.writes + (d.writes_superseded ?? 0),
        last: d,
      }));
    };
    window.addEventListener("iris:dcp_pruned", handler);
    return () => window.removeEventListener("iris:dcp_pruned", handler);
  }, [enabled]);
  return s;
}
