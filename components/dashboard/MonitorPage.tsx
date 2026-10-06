"use client";

// ONE Monitor page: the old Monitor tab (Analytics | Logs | Diagnostics) and
// the Inference console, merged with nothing shown twice. Inventory and where
// each item went: docs/architecture/MONITOR.md. Look: docs/design/
// chatview-2026-10-06/iris-dashboard.html (`monitor` rows).

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fmtClock, fmtMs, fmtNum, shortModel,
  useDcpStats, useInferenceStream, useMonitorAnalytics, useMonitorDiagnostics, useMonitorLogs,
  type StreamFilter,
} from "./monitor/useMonitorData";

export type MonitorRowId = "now" | "stream" | "usage" | "logs" | "diagnostics" | "context";

export interface MonitorPageProps {
  glowColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
  /** Shows the Context row (DCP pruner stats). */
  developerMode?: boolean;
  /** Open a row from outside; `n` changes on every request so a repeat re-opens it. */
  openRow?: { row: MonitorRowId; n: number } | null;
}

// ── Row + field chrome (the concept's .sec / .srow / .fields / .f) ───────────

function Row({ id, name, summary, open, onToggle, children }: {
  id: MonitorRowId; name: string; summary: string; open: boolean; onToggle: (id: MonitorRowId) => void; children: React.ReactNode;
}) {
  return (
    <div className={`iris-mon-sec${open ? " open" : ""}`} data-row={id}>
      <button className="iris-mon-srow" aria-expanded={open} aria-controls={`iris-mon-${id}`} onClick={() => onToggle(id)}>
        <span className="o" aria-hidden="true">{open ? "●" : "○"}</span>
        <b>{name}</b>
        <small>{summary}</small>
      </button>
      {open && <div className="iris-mon-fields" id={`iris-mon-${id}`}>{children}</div>}
    </div>
  );
}

function F({ label, hint, dot, tone, value, wide, children }: {
  label?: React.ReactNode; hint?: string; dot?: string; tone?: "bad" | "warn" | "ok"; value?: React.ReactNode; wide?: boolean; children?: React.ReactNode;
}) {
  return (
    <div className="iris-mon-f">
      {label !== undefined && (
        <div className="l">
          <b>{dot && <i style={{ ["--dot" as any]: dot }} />}{label}</b>
          {hint && <small>{hint}</small>}
        </div>
      )}
      <div className={`c${wide ? " wide" : ""}`}>
        {value !== undefined && <span className={`num${tone ? " " + tone : ""}`}>{value}</span>}
        {children}
      </div>
    </div>
  );
}

function Seg<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: readonly T[]; onChange: (v: T) => void }) {
  return (
    <div className="iris-mon-sg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o} aria-pressed={o === value} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

const HEALTH_TONE = { healthy: "ok", warning: "warn", error: "bad", idle: undefined } as const;
const HEALTH_DOT = { healthy: "var(--mon-ok)", warning: "var(--mon-run)", error: "var(--mon-bad)", idle: "#8a92a8" } as const;
const LEVELS = ["ALL", "ERROR", "WARNING", "INFO", "DEBUG"] as const;
type Level = (typeof LEVELS)[number];

function levelOf(l: string): "error" | "warn" | "debug" | "info" {
  const u = l.toUpperCase();
  if (u.includes("ERROR") || u.includes("CRITICAL") || u.includes("FATAL")) return "error";
  if (u.includes("WARN")) return "warn";
  if (u.includes("DEBUG") || u.includes("TRACE")) return "debug";
  return "info";
}

function clock(ts: string): string {
  if (!ts) return "--:--:--";
  const d = new Date(ts);
  return isNaN(d.getTime()) ? ts.slice(11, 19) || "--:--:--" : d.toTimeString().slice(0, 8);
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function MonitorPage({ glowColor = "#6b9bff", sendMessage, developerMode = false, openRow = null }: MonitorPageProps) {
  const stream = useInferenceStream();
  const usage = useMonitorAnalytics(sendMessage);
  const logs = useMonitorLogs(sendMessage);
  const diag = useMonitorDiagnostics(sendMessage);
  const dcp = useDcpStats(developerMode);

  const [open, setOpen] = useState<Set<MonitorRowId>>(() => new Set<MonitorRowId>(["now"]));
  const [filter, setFilter] = useState<StreamFilter>("all");
  const [streamScroll, setStreamScroll] = useState(true);
  const [logScroll, setLogScroll] = useState(true);
  const [level, setLevel] = useState<Level>("ALL");
  const [search, setSearch] = useState("");

  // Logs and Diagnostics are read from the backend the first time their row
  // opens (diagnostics runs process and GPU probes, so it never runs unasked).
  const asked = useRef({ logs: false, diagnostics: false });
  const [askedView, setAskedView] = useState({ logs: false, diagnostics: false });
  const refreshLogs = logs.refresh;
  const refreshDiag = diag.refresh;
  const fetchOnce = useCallback((id: MonitorRowId) => {
    if ((id !== "logs" && id !== "diagnostics") || asked.current[id]) return;
    asked.current[id] = true;
    setAskedView({ ...asked.current });
    (id === "logs" ? refreshLogs : refreshDiag)();
  }, [refreshLogs, refreshDiag]);

  const toggle = useCallback((id: MonitorRowId) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
    fetchOnce(id);
  }, [fetchOnce]);

  const openN = openRow?.n;
  useEffect(() => {
    if (!openRow) return;
    setOpen((prev) => new Set(prev).add(openRow.row));
    fetchOnce(openRow.row);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openN]);

  // ── Now ──
  const modelEntries = Object.entries(stream.models);
  const speed = stream.last ? `${stream.last.tps} t/s · ${fmtMs(stream.last.latencyMs)}` : null;
  const nowSummary = [
    modelEntries.length ? modelEntries.map(([, m]) => shortModel(m)).join(" + ") : "no model load seen",
    speed ?? "no calls yet",
  ].join(" · ");

  // ── Inference stream ──
  const visible = useMemo(
    () => stream.entries.filter((e) => filter === "all" || (filter === "calls" ? e.kind === "call" : e.kind === "load")),
    [stream.entries, filter],
  );
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (streamScroll && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [visible, streamScroll, open]);
  const calls = stream.entries.filter((e) => e.kind === "call").length;
  const streamSummary = stream.entries.length
    ? `${calls} calls · ${stream.entries.length - calls} loads${stream.paused ? " · paused" : ""}`
    : stream.paused ? "paused" : "waiting for calls and loads";

  // ── Usage ──
  const u = usage.data;
  const usageSummary = u
    ? `${fmtNum(u.stats.total_tokens)} tokens · ${fmtNum(u.stats.total_calls)} calls · $${u.stats.estimated_cost.toFixed(4)}`
    : "loading";
  const maxTokens = u && u.models.length ? Math.max(...u.models.map((m) => m.total_tokens)) : 0;

  // ── Logs ──
  const shownLogs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return logs.lines.filter((l) => {
      if (level !== "ALL") {
        const lv = levelOf(l.level);
        if (level === "ERROR" ? lv !== "error" : level === "WARNING" ? lv !== "warn" : level === "DEBUG" ? lv !== "debug" : lv !== "info") return false;
      }
      return !q || l.message.toLowerCase().includes(q) || l.source.toLowerCase().includes(q) || l.level.toLowerCase().includes(q);
    });
  }, [logs.lines, level, search]);
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (logScroll && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [shownLogs, logScroll, open]);
  const nErr = logs.lines.filter((l) => levelOf(l.level) === "error").length;
  const nWarn = logs.lines.filter((l) => levelOf(l.level) === "warn").length;
  const logsSummary = !askedView.logs && !logs.loaded
    ? "open to read"
    : !logs.loaded ? "loading" : `${nErr} errors · ${nWarn} warnings · ${logs.lines.length} lines`;

  // ── Diagnostics ──
  const cnt = { healthy: 0, warning: 0, error: 0, idle: 0 };
  diag.checks.forEach((c) => { if (c.status in cnt) cnt[c.status]++; });
  const diagSummary = !diag.loaded
    ? (askedView.diagnostics ? "running checks" : "open to run checks")
    : `${cnt.healthy} of ${diag.checks.length} pass${cnt.error ? ` · ${cnt.error} error` : ""}${cnt.warning ? ` · ${cnt.warning} warning` : ""}`;

  const L = dcp.last;
  return (
    <div className="iris-mon" style={{ ["--mon-acc" as any]: glowColor }}>
      <Row id="now" name="Now" summary={nowSummary} open={open.has("now")} onToggle={toggle}>
        {modelEntries.length === 0 ? (
          <F label="Model" hint="from model load events since this page opened" value="no load seen" />
        ) : modelEntries.map(([slot, m]) => (
          <F key={slot} label={slot === "model" ? "Model" : `${slot[0].toUpperCase()}${slot.slice(1)} model`} hint="loaded" value={shortModel(m)} />
        ))}
        <F label="Speed" hint="last call" value={speed ?? "—"} />
        <F label="Average speed" hint="all calls since this page opened" value={stream.avgTps !== null ? `${stream.avgTps.toFixed(1)} t/s` : "—"} />
      </Row>

      <Row id="stream" name="Inference stream" summary={streamSummary} open={open.has("stream")} onToggle={toggle}>
        <F label="Show" hint="every call and every model load">
          <Seg<StreamFilter> label="Show" value={filter} options={["all", "calls", "loads"] as const} onChange={setFilter} />
        </F>
        <F wide>
          <button className="iris-mon-btn" aria-pressed={stream.paused} onClick={() => stream.setPaused(!stream.paused)}>{stream.paused ? "Resume" : "Pause"}</button>
          <button className="iris-mon-btn" aria-pressed={streamScroll} onClick={() => setStreamScroll(!streamScroll)}>Auto-scroll</button>
          <button className="iris-mon-btn" disabled={stream.entries.length === 0} onClick={stream.exportJson}>Export</button>
          <button className="iris-mon-btn" disabled={stream.entries.length === 0} onClick={stream.clear}>Clear</button>
        </F>
        <div className="iris-mon-lines" ref={listRef} aria-label="Inference stream" role="log">
          {visible.length === 0 ? (
            <div className="iris-mon-empty">Waiting for inference events…</div>
          ) : visible.map((e) => (
            <div key={e.id} className="iris-mon-line">
              <span className="t">{fmtClock(e.ts)}</span>
              {e.kind === "call" ? (
                <span className="m"><em>{shortModel(e.model)}</em> · ↑{e.promptTok} ↓{e.compTok} tok · {e.tps} t/s · {e.latencyMs}ms</span>
              ) : (
                <span className="m">{e.action === "loaded" ? "▶ Loaded" : "■ Unloaded"}: {shortModel(e.model)}{e.action === "loaded" && e.profile ? ` · ${e.profile}` : ""}</span>
              )}
            </div>
          ))}
        </div>
      </Row>

      <Row id="usage" name="Usage" summary={usageSummary} open={open.has("usage")} onToggle={toggle}>
        {!u ? <div className="iris-mon-empty">Loading usage…</div> : (
          <>
            <F label="Tokens" hint={`↑${fmtNum(u.stats.total_prompt_tokens)} prompt · ↓${fmtNum(u.stats.total_completion_tokens)} completion`} value={fmtNum(u.stats.total_tokens)} />
            <F label="Calls" hint={u.stats.total_audio_tokens ? `${fmtNum(u.stats.total_audio_tokens)} audio tokens` : undefined} value={fmtNum(u.stats.total_calls)} />
            <F label="Estimated cost" hint="USD" value={`$${u.stats.estimated_cost.toFixed(4)}`} />
            <F label="Session" value={`${u.stats.session_duration_minutes.toFixed(1)} min`} />
            {u.latency && u.latency.count > 0 && (
              <>
                <F label="Latency, median" hint="p50" value={fmtMs(u.latency.p50_ms)} />
                <F label="Latency, slow end" hint="p95" value={fmtMs(u.latency.p95_ms)} />
                <F label="Latency, average" value={fmtMs(u.latency.avg_ms)} />
                <F label="Latency, range" hint="min to max" value={`${fmtMs(u.latency.min_ms)} – ${fmtMs(u.latency.max_ms)}`} />
              </>
            )}
            {u.models.length === 0 ? (
              <F label="Models" value="no usage recorded yet" />
            ) : u.models.map((m) => (
              <F key={m.model} label={m.model} hint={`${m.total_calls} calls · ${m.percentage}% of tokens`}>
                <span className="iris-mon-bar" aria-hidden="true"><i style={{ width: `${maxTokens ? (m.total_tokens / maxTokens) * 100 : 0}%` }} /></span>
                <span className="num">{fmtNum(m.total_tokens)} tok · ${m.estimated_cost.toFixed(4)}</span>
              </F>
            ))}
            <F wide><button className="iris-mon-btn" onClick={usage.refresh}>Refresh</button></F>
          </>
        )}
      </Row>

      <Row id="logs" name="Logs" summary={logsSummary} open={open.has("logs")} onToggle={toggle}>
        <F label="Level" hint="app logs; model calls stay in the stream">
          <Seg<Level> label="Level" value={level} options={LEVELS} onChange={setLevel} />
        </F>
        <F wide>
          <input className="iris-mon-find" type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter…" aria-label="Filter logs" />
          <button className="iris-mon-btn" aria-pressed={logScroll} onClick={() => setLogScroll(!logScroll)}>Auto-scroll</button>
          <button className="iris-mon-btn" onClick={logs.refresh}>Refresh</button>
        </F>
        <div className="iris-mon-lines" ref={logRef} aria-label="Logs" role="log">
          {!logs.loaded ? (
            <div className="iris-mon-empty">Loading logs…</div>
          ) : shownLogs.length === 0 ? (
            <div className="iris-mon-empty">No log lines match.</div>
          ) : shownLogs.map((l, i) => (
            <div key={`${l.timestamp}-${i}`} className={`iris-mon-line ${levelOf(l.level)}`}>
              <span className="t">{clock(l.timestamp)}</span>
              <span className="m">{l.level} {l.source ? `${l.source} · ` : ""}{l.message}</span>
            </div>
          ))}
        </div>
        {logs.hidden > 0 && <div className="iris-mon-empty">{logs.hidden} model-call lines hidden; they are in the Inference stream.</div>}
      </Row>

      <Row id="diagnostics" name="Diagnostics" summary={diagSummary} open={open.has("diagnostics")} onToggle={toggle}>
        <F wide><button className="iris-mon-btn" onClick={diag.refresh}>Run checks</button></F>
        {diag.checks.length === 0 && <div className="iris-mon-empty">{diag.loaded ? "No health data available." : "Running health checks…"}</div>}
        {diag.checks.map((c) => (
          <F key={c.component} label={c.component.split("_").map((w) => w[0]?.toUpperCase() + w.slice(1)).join(" ")} hint={c.message || undefined}
            dot={HEALTH_DOT[c.status] ?? HEALTH_DOT.idle} tone={HEALTH_TONE[c.status]}
            value={`${c.status === "healthy" ? "OK" : c.status === "warning" ? "WARN" : c.status === "error" ? "ERR" : "IDLE"}${c.latency_ms > 0 ? ` · ${c.latency_ms.toFixed(0)}ms` : ""}`} />
        ))}
        {diag.view.issues.map((t, i) => <F key={`i${i}`} label={t.replace(/^(ERROR|ISSUE):?\s*/, "")} hint="issue" dot="var(--mon-bad)" tone="bad" value="ERR" />)}
        {diag.view.warnings.map((t, i) => <F key={`w${i}`} label={t.replace(/^(WARN|NOTE):?\s*/, "")} hint="warning" dot="var(--mon-run)" tone="warn" value="WARN" />)}
        {diag.loaded && diag.view.issues.length === 0 && diag.view.warnings.length === 0 && (
          <F label="Issues and warnings" hint={diag.trouble.summary || undefined} tone="ok" value="none" />
        )}
        {diag.view.debug.map((line, i) => {
          const k = line.indexOf(":");
          return <F key={`d${i}`} label={k > 0 ? line.slice(0, k) : line} hint="debug" value={k > 0 ? line.slice(k + 1).trim() : undefined} />;
        })}
      </Row>

      {developerMode && (
        <Row id="context" name="Context" summary={dcp.passes ? `${dcp.passes} prune passes · ${fmtNum(dcp.saved)} tokens saved` : "pruner idle, no turns yet"} open={open.has("context")} onToggle={toggle}>
          <F label="Prune passes" hint="Dynamic Context Pruner" value={dcp.passes.toLocaleString()} />
          <F label="Tokens saved" value={dcp.saved.toLocaleString()} />
          <F label="Deduplicated" value={dcp.dedups.toLocaleString()} />
          <F label="Errors purged" value={dcp.errors.toLocaleString()} />
          <F label="Stale writes superseded" value={dcp.writes.toLocaleString()} />
          {L && <F label="Last pass" hint="in / out / saved / dedups / errors / writes" value={`${L.input_count} / ${L.output_count} / ${L.tokens_saved} / ${L.dedups} / ${L.errors_purged} / ${L.writes_superseded}`} />}
        </Row>
      )}
    </div>
  );
}

export default MonitorPage;
