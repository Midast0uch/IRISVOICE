"use client";

// ONE Monitor page: the old Monitor tab (Analytics | Logs | Diagnostics) and
// the Inference console, merged with nothing shown twice. Inventory and where
// each item went: docs/architecture/MONITOR.md. Look: docs/design/
// chatview-2026-10-06/iris-dashboard.html (`Monitor = an instrument panel`):
// a tile strip, then panes on a 12-column grid.

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fmtClock, fmtMs, fmtNum, shortModel,
  useDcpStats, useInferenceStream, useMonitorAnalytics, useMonitorDiagnostics, useMonitorLogs,
  type StreamFilter,
} from "./monitor/useMonitorData";

export type MonitorPaneId = "stream" | "usage" | "logs" | "diagnostics" | "context";

export interface MonitorPageProps {
  glowColor?: string;
  sendMessage?: (type: string, payload?: any) => boolean;
  /** Shows the Context pane (DCP pruner stats). */
  developerMode?: boolean;
  /** Bring a pane into view and focus it; `n` changes on every request so a repeat does it again. */
  openRow?: { row: MonitorPaneId; n: number } | null;
}

// ── Chrome ───────────────────────────────────────────────────────────────────

function Pane({ id, name, span, paneRef, header, children }: {
  id: MonitorPaneId; name: string; span: "w7" | "w5" | "w12"; paneRef: React.RefObject<HTMLElement | null>;
  header: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className={`iris-mon-pane ${span}`} data-area={id} aria-label={name} tabIndex={-1} ref={paneRef}>
      <h4>{header}</h4>
      {children}
    </section>
  );
}

function Chips<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: readonly T[]; onChange: (v: T) => void }) {
  return (
    <span role="group" aria-label={label} style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {options.map((o) => (
        <button key={o} aria-pressed={o === value} onClick={() => onChange(o)}>{o}</button>
      ))}
    </span>
  );
}

function Tile({ k, children, s, spark, big }: { k: string; children: React.ReactNode; s?: React.ReactNode; spark?: number[]; big?: boolean }) {
  const top = spark && spark.length ? Math.max(...spark, 1) : 1;
  return (
    <div className="iris-mon-tile">
      <span className="k">{k}</span>
      <span className={`v${big ? " big" : ""}`}>{children}</span>
      {spark && spark.length > 0 && (
        <div className="iris-mon-spark" aria-hidden="true">
          {spark.map((v, i) => <span key={i} style={{ height: `${Math.max(8, Math.round((v / top) * 100))}%` }} />)}
        </div>
      )}
      {s !== undefined && <span className="s">{s}</span>}
    </div>
  );
}

const STATUS_GLYPH = { healthy: ["●", ""], warning: ["◐", "w"], error: ["✕", "e"], idle: ["○", "i"] } as const;
const STATUS_WORD = { healthy: "ok", warning: "warning", error: "error", idle: "idle" } as const;
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

const secs = (ms: number) => (ms / 1000).toFixed(1);

// Calls fire `onView` once the element is first on screen. Without
// IntersectionObserver (old webview, tests) it fires at once.
function useFirstView(ref: React.RefObject<HTMLElement | null>, onView: () => void) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") { onView(); return; }
    const io = new IntersectionObserver((hits) => { if (hits.some((h) => h.isIntersecting)) { onView(); io.disconnect(); } });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, onView]);
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function MonitorPage({ glowColor = "#6b9bff", sendMessage, developerMode = false, openRow = null }: MonitorPageProps) {
  const stream = useInferenceStream();
  const usage = useMonitorAnalytics(sendMessage);
  const logs = useMonitorLogs(sendMessage);
  const diag = useMonitorDiagnostics(sendMessage);
  const dcp = useDcpStats(developerMode);

  const [filter, setFilter] = useState<StreamFilter>("all");
  const [streamScroll, setStreamScroll] = useState(true);
  const [logScroll, setLogScroll] = useState(true);
  const [level, setLevel] = useState<Level>("ALL");
  const [search, setSearch] = useState("");

  const panes = {
    stream: useRef<HTMLElement>(null), usage: useRef<HTMLElement>(null), logs: useRef<HTMLElement>(null),
    diagnostics: useRef<HTMLElement>(null), context: useRef<HTMLElement>(null),
  };

  // Logs and Diagnostics are read from the backend the first time their pane is
  // seen (diagnostics runs process and GPU probes, so it never runs unasked).
  const asked = useRef({ logs: false, diagnostics: false });
  const [askedView, setAskedView] = useState({ logs: false, diagnostics: false });
  const refreshLogs = logs.refresh;
  const refreshDiag = diag.refresh;
  const fetchOnce = useCallback((id: MonitorPaneId) => {
    if ((id !== "logs" && id !== "diagnostics") || asked.current[id]) return;
    asked.current[id] = true;
    setAskedView({ ...asked.current });
    (id === "logs" ? refreshLogs : refreshDiag)();
  }, [refreshLogs, refreshDiag]);
  const seeLogs = useCallback(() => fetchOnce("logs"), [fetchOnce]);
  const seeDiag = useCallback(() => fetchOnce("diagnostics"), [fetchOnce]);
  useFirstView(panes.logs, seeLogs);
  useFirstView(panes.diagnostics, seeDiag);

  // open_inference_console and friends: bring the pane into view and focus it.
  const openN = openRow?.n;
  useEffect(() => {
    if (!openRow) return;
    const el = panes[openRow.row]?.current;
    fetchOnce(openRow.row);
    if (!el) return;
    const calm = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest", behavior: calm ? "auto" : "smooth" });
    el.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openN]);

  // ── Now (tiles) ──
  const reasoning = stream.models.reasoning;
  const tool = stream.models.tool;
  const others = Object.entries(stream.models).filter(([k]) => k !== "reasoning" && k !== "tool");
  const u = usage.data;
  const lat = u && u.latency && u.latency.count > 0 ? u.latency : null;

  // ── Inference stream ──
  const visible = useMemo(
    () => stream.entries.filter((e) => filter === "all" || (filter === "calls" ? e.kind === "call" : e.kind === "load")),
    [stream.entries, filter],
  );
  const maxMs = useMemo(() => Math.max(2000, ...visible.map((e) => (e.kind === "call" ? e.latencyMs : 0))), [visible]);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (streamScroll && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [visible, streamScroll]);

  // ── Usage ──
  const maxTokens = u && u.models.length ? Math.max(...u.models.map((m) => m.total_tokens)) : 0;
  const promptShare = u && u.stats.total_tokens > 0 ? (u.stats.total_prompt_tokens / u.stats.total_tokens) * 100 : 0;

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
  }, [shownLogs, logScroll, logs.hidden]);

  const L = dcp.last;
  return (
    <div className="iris-mon" style={{ ["--mon-acc" as any]: glowColor }}>
      <div className="iris-mon-grid">
        <div className="iris-mon-tiles" data-area="now" aria-label="Now" role="group">
          <Tile k="Reasoning" s={reasoning ? "loaded" : "no load seen"}>
            <i className={reasoning ? "" : "off"} aria-hidden="true" />{reasoning ? shortModel(reasoning) : "—"}
          </Tile>
          <Tile k="Tool" s={tool || others.length === 0 ? (tool ? "loaded" : "no load seen") : `also ${others.map(([slot, m]) => `${slot}: ${shortModel(m)}`).join(", ")}`}>
            <i className={tool ? "" : "off"} aria-hidden="true" />{tool ? shortModel(tool) : "—"}
          </Tile>
          <Tile k="Speed" big spark={stream.recent} s={stream.last ? `last call ${fmtMs(stream.last.latencyMs)} · avg ${stream.avgTps?.toFixed(1)}` : "no calls yet"}>
            {stream.last ? <>{stream.last.tps}<small> tok/s</small></> : "—"}
          </Tile>
          <Tile k="Reply time" big s={lat ? `median call · p95 ${secs(lat.p95_ms)} s` : "no latency data yet"}>
            {lat ? <>{secs(lat.p50_ms)}<small> s</small></> : "—"}
          </Tile>
        </div>

        <Pane id="stream" name="Inference stream" span="w7" paneRef={panes.stream} header={
          <>
            <span className={`live${stream.paused ? " off" : ""}`} aria-hidden="true" />Inference stream<span className="sp" />
            <Chips<StreamFilter> label="Show" value={filter} options={["all", "calls", "loads"] as const} onChange={setFilter} />
            <button aria-pressed={stream.paused} onClick={() => stream.setPaused(!stream.paused)}>{stream.paused ? "Resume" : "Pause"}</button>
            <button aria-pressed={streamScroll} onClick={() => setStreamScroll(!streamScroll)}>Auto-scroll</button>
            <button disabled={stream.entries.length === 0} onClick={stream.exportJson}>Export</button>
            <button disabled={stream.entries.length === 0} onClick={stream.clear}>Clear</button>
          </>
        }>
          <div className="iris-mon-calls" ref={listRef} aria-label="Inference calls and loads" role="log">
            {visible.length === 0 ? (
              <div className="iris-mon-empty">Waiting for inference events…</div>
            ) : (
              <table>
                <colgroup><col className="t" /><col /><col className="k" /><col className="l" /></colgroup>
                <tbody>
                  {visible.map((e) => e.kind === "call" ? (
                    <tr key={e.id} title={`${e.tps} tok/s`}>
                      <td>{fmtClock(e.ts)}</td>
                      <td className="m" title={e.model}>{shortModel(e.model)}</td>
                      <td>{e.promptTok.toLocaleString()} → {e.compTok.toLocaleString()}</td>
                      <td>
                        <span className="iris-mon-lat">
                          <b className={e.latencyMs > 3000 ? "slow" : ""} style={{ width: Math.round((e.latencyMs / maxMs) * 30) }} />
                          {secs(e.latencyMs)} s
                        </span>
                      </td>
                    </tr>
                  ) : (
                    <tr key={e.id} className="load">
                      <td>{fmtClock(e.ts)}</td>
                      <td className="m" title={e.model}>{shortModel(e.model)}</td>
                      <td>{e.action === "loaded" ? `loaded · ${e.profile || "model"}` : "unloaded"}</td>
                      <td />
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Pane>

        <Pane id="usage" name="Usage" span="w5" paneRef={panes.usage} header={
          <>Usage<span className="sp" /><button onClick={usage.refresh}>Refresh</button></>
        }>
          {!u ? <div className="iris-mon-empty">Loading usage…</div> : (
            <div className="iris-mon-usage">
              <div className="row"><span>Tokens</span><b>{fmtNum(u.stats.total_tokens)}</b></div>
              <div className="iris-mon-split" aria-hidden="true"><b style={{ width: `${promptShare}%` }} /><i style={{ width: `${100 - promptShare}%` }} /></div>
              <div className="iris-mon-axis"><span>↑{fmtNum(u.stats.total_prompt_tokens)} prompt</span><span>↓{fmtNum(u.stats.total_completion_tokens)} completion</span></div>
              {u.stats.total_audio_tokens > 0 && <div className="iris-mon-axis"><span>{fmtNum(u.stats.total_audio_tokens)} audio tokens</span></div>}
              <div className="row"><span>Calls</span><b>{fmtNum(u.stats.total_calls)}</b></div>
              <div className="row"><span>Estimated cost, USD</span><b className="sm">{`$${u.stats.estimated_cost.toFixed(4)}`}</b></div>
              <div className="row"><span>Session</span><b className="sm">{`${u.stats.session_duration_minutes.toFixed(1)} min`}</b></div>
              {lat && (
                <>
                  <div className="row"><span>Latency, average</span><b className="sm">{fmtMs(lat.avg_ms)}</b></div>
                  <div className="row"><span>Latency, range</span><b className="sm">{`${fmtMs(lat.min_ms)} – ${fmtMs(lat.max_ms)}`}</b></div>
                </>
              )}
              {u.models.length === 0 ? (
                <div className="iris-mon-axis"><span>no usage recorded yet</span></div>
              ) : (
                <div className="iris-mon-model">
                  {u.models.map((m) => (
                    <div key={m.model} title={`${m.total_calls} calls · ${m.percentage}% of tokens`} style={{ flexDirection: "column", gap: 3 }}>
                      <div><span>{m.model}</span><small>{fmtNum(m.total_tokens)} tok · ${m.estimated_cost.toFixed(4)}</small></div>
                      <span className="iris-mon-bar" aria-hidden="true"><i style={{ width: `${maxTokens ? (m.total_tokens / maxTokens) * 100 : 0}%` }} /></span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Pane>

        <Pane id="logs" name="Logs" span="w7" paneRef={panes.logs} header={
          <>
            Logs<span className="sp" />
            <Chips<Level> label="Level" value={level} options={LEVELS} onChange={setLevel} />
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="search" aria-label="Filter logs" />
            <button aria-pressed={logScroll} onClick={() => setLogScroll(!logScroll)}>Auto-scroll</button>
            <button onClick={logs.refresh}>Refresh</button>
          </>
        }>
          <div className="iris-mon-logs" ref={logRef} aria-label="Log lines" role="log">
            {!logs.loaded ? (
              <div className="hid">{askedView.logs ? "Loading logs…" : "Logs load when this pane is first seen."}</div>
            ) : shownLogs.length === 0 ? (
              <div className="hid">No log lines match.</div>
            ) : shownLogs.map((l, i) => {
              const lv = levelOf(l.level);
              const text = `${l.source ? `${l.source} · ` : ""}${l.message}`;
              return (
                <div key={`${l.timestamp}-${i}`}>
                  <span className="t">{clock(l.timestamp)}</span>
                  <span className={`lv ${lv}`}>{lv}</span>
                  <span className="x" title={text}>{text}</span>
                </div>
              );
            })}
            {logs.hidden > 0 && (
              <div className="hid">{logs.hidden} model-call {logs.hidden === 1 ? "line is" : "lines are"} in the stream, not here</div>
            )}
          </div>
        </Pane>

        <Pane id="diagnostics" name="Diagnostics" span="w5" paneRef={panes.diagnostics} header={
          <>Diagnostics<span className="sp" /><button onClick={diag.refresh}>Run checks</button></>
        }>
          {diag.checks.length === 0 && diag.view.issues.length === 0 && diag.view.warnings.length === 0 && diag.view.debug.length === 0 ? (
            <div className="iris-mon-empty">
              {diag.loaded ? "No health data available." : askedView.diagnostics ? "Running health checks…" : "Checks run when this pane is first seen."}
            </div>
          ) : (
            <ul className="iris-mon-checks">
              {diag.checks.map((c) => {
                const [glyph, cls] = STATUS_GLYPH[c.status] ?? STATUS_GLYPH.idle;
                const word = STATUS_WORD[c.status] ?? "idle";
                const val = [c.message || word, c.latency_ms > 0 ? `${c.latency_ms.toFixed(0)} ms` : ""].filter(Boolean).join(" · ");
                const name = c.component.split("_").map((w) => w[0]?.toUpperCase() + w.slice(1)).join(" ");
                return (
                  <li key={c.component}>
                    <span className={`st ${cls}`} role="img" aria-label={word}>{glyph}</span>
                    <span className="n">{name}</span>
                    <small title={val}>{val}</small>
                  </li>
                );
              })}
              {diag.view.issues.map((t, i) => {
                const text = t.replace(/^(ERROR|ISSUE):?\s*/, "");
                return <li key={`i${i}`}><span className="st e" role="img" aria-label="error">✕</span><span className="n" title={text}>{text}</span><small>issue</small></li>;
              })}
              {diag.view.warnings.map((t, i) => {
                const text = t.replace(/^(WARN|NOTE):?\s*/, "");
                return <li key={`w${i}`}><span className="st w" role="img" aria-label="warning">◐</span><span className="n" title={text}>{text}</span><small>warning</small></li>;
              })}
              {diag.loaded && diag.view.issues.length === 0 && diag.view.warnings.length === 0 && (
                <li><span className="st" role="img" aria-label="ok">●</span><span className="n">Issues and warnings</span><small>{diag.trouble.summary || "none"}</small></li>
              )}
              {diag.view.debug.map((line, i) => {
                const k = line.indexOf(":");
                const val = k > 0 ? line.slice(k + 1).trim() : "";
                return <li key={`d${i}`}><span className="st i" aria-hidden="true">·</span><span className="n">{k > 0 ? line.slice(0, k) : line}</span><small title={val}>{val}</small></li>;
              })}
            </ul>
          )}
        </Pane>

        {developerMode && (
          <Pane id="context" name="Context" span="w12" paneRef={panes.context} header={
            <>Context<span className="sp" /><span style={{ letterSpacing: 0, textTransform: "none", fontWeight: 400 }}>Dynamic Context Pruner</span></>
          }>
            <div className="iris-mon-stats">
              <div><span>Prune passes</span><b>{dcp.passes.toLocaleString()}</b></div>
              <div><span>Tokens saved</span><b>{dcp.saved.toLocaleString()}</b></div>
              <div><span>Deduplicated</span><b>{dcp.dedups.toLocaleString()}</b></div>
              <div><span>Errors purged</span><b>{dcp.errors.toLocaleString()}</b></div>
              <div><span>Stale writes superseded</span><b>{dcp.writes.toLocaleString()}</b></div>
              {L && <div title="in / out / saved / dedups / errors / writes"><span>Last pass</span><b>{`${L.input_count} / ${L.output_count} / ${L.tokens_saved} / ${L.dedups} / ${L.errors_purged} / ${L.writes_superseded}`}</b></div>}
            </div>
          </Pane>
        )}
      </div>
    </div>
  );
}

export default MonitorPage;
