import React, { useEffect, useState } from 'react';

/** What the backend auto-loader WOULD do with this model, computed by the same
 *  recommend_profile + derive_config the load path runs. Shown before the click
 *  so the card promises exactly what the loader delivers. */
interface LoadPlan {
  profile: string;
  n_ctx: number;
  native_ctx: number;
  kv_cache: string;
  vram_gb: number;
  vram_free_gb: number;
  fits: boolean;
  reason: string;
  /** REQ-4 AC3/AC5: on-disk size of the projector this plan already folded
   *  into vram_gb, when the model has one and it is attached by default.
   *  Optional — an older backend payload simply omits it, and the card
   *  must render as text-only rather than crash. */
  mmproj_gb?: number;
}

interface ModelEntry {
  path: string;
  filename: string;
  display_name: string;
  size_gb: number;
  architecture: string;
  params_b: number;
  quantization: string;
  vram_estimate_gb: number;
  native_ctx: number;
  loaded: boolean;
  plan?: LoadPlan;
  /** REQ-5 AC2/AC3: attached by scan_models when a sibling mmproj-*.gguf
   *  matched this base model by stem. All three are OPTIONAL — a payload
   *  from before T1/T8 simply omits them, and the card must degrade to a
   *  plain text-only row rather than throw. */
  has_vision?: boolean;
  mmproj_path?: string | null;
  mmproj_size_gb?: number;
}

interface ModelBrowserPanelProps {
  glowColor: string;
  fontColor: string;
  /** WebSocket sender from the dashboard. Loading and unloading both go
   *  straight down this — see the note on doLoad. */
  sendMessage?: (type: string, payload?: any) => boolean;
}

const LOADED_GREEN = '#22c55e';

/** 65536 -> "64k". Context numbers are the thing being compared here, and the
 *  raw digits are too wide for the card's second row. */
function fmtCtx(n: number): string {
  if (!n) return '';
  return n >= 1024 ? `${Math.round(n / 1024)}k` : String(n);
}

export function ModelBrowserPanel({ glowColor, fontColor, sendMessage }: ModelBrowserPanelProps) {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [modelsDir, setModelsDir] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedPath, setSelectedPath] = useState('');
  const [loadPct, setLoadPct] = useState(0);
  const [loadMsg, setLoadMsg] = useState('');
  const [loadPhase, setLoadPhase] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingPath, setLoadingPath] = useState('');

  // REQ-10 AC2: user-chosen, ordered vision fallback ladder. Holds model
  // `path` strings only — order in the array IS priority. Seeded from
  // `cfg.inference.vision_fallback_ladder` on every fetch (single source of
  // truth is the backend, not local-only state), filtered to models that are
  // both has_vision AND still present in the current scan (REQ-10 AC6: a
  // configured model missing from disk is dropped here too, not just in the
  // backend's own skip-and-continue).
  const [visionLadder, setVisionLadder] = useState<string[]>([]);
  const [ladderMsg, setLadderMsg] = useState('');

  const loadedModel = models.find(m => m.loaded);
  // REQ-10 AC1: every scanned has_vision model is a ladder candidate — no
  // separate discovery mechanism, same data T9 already put on the payload.
  const visionCandidates = models.filter(m => m.has_vision);

  // ── Fetch model list ────────────────────────────────────────────────
  const fetchModels = async () => {
    setLoading(true);
    setError('');
    // Bounded fetch. Without the abort, a request issued while the backend is
    // still starting hangs forever against the dev proxy's dead upstream, so
    // `loading` never clears — and because Rescan is `disabled={loading}`, the
    // panel wedges permanently on "Scanning models..." with no way for the user
    // to retry. Observed live: two fetches fired at mount during a backend
    // restart and never settled, while the same call from the page returned 200
    // in 365 ms.
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 15000);
    try {
      const res = await fetch('/api/models', { signal: ctl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const fetchedModels: ModelEntry[] = data.models || [];
      setModels(fetchedModels);
      setModelsDir(data.models_dir || '');
      // Seed the ladder from the backend's persisted config (T15b/AC3), not
      // from anything held only in this component — a second browser tab or
      // a config edit on disk must show up here on the next fetch. Filtered
      // to paths that are both has_vision and still on disk right now, so a
      // deleted model silently drops out of the UI's selection instead of
      // rendering an order entry for a candidate that no longer exists.
      const visionPaths = new Set(
        fetchedModels.filter(m => m.has_vision).map(m => m.path)
      );
      const persistedLadder: unknown = data.vision_fallback_ladder;
      const nextLadder = Array.isArray(persistedLadder)
        ? persistedLadder.filter((p): p is string => typeof p === 'string' && visionPaths.has(p))
        : [];
      setVisionLadder(nextLadder);
    } catch (err: any) {
      setError(err.message || 'Failed to load models');
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  // ── WS progress listener ─────────────────────────────────────────────
  // Terminal states are handled explicitly. This used to treat only
  // ready/pct>=100 as an ending and leave every other outcome to a blind
  // 60-second timeout in doLoad, so a load that ERRORED showed a spinner for a
  // full minute and then quietly stopped — indistinguishable from success.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      // Backend sends "local_model_loading" with { status, pct, msg, phase }.
      // The WS handler forwards it as iris:ws_message with
      // detail = { type: "local_model_loading", payload: { pct, msg, ... } }
      if (!detail) return;
      const msgType = detail.type ?? '';
      const payload = detail.payload ?? detail; // normalize nested payload
      if (!msgType.startsWith('local_model')) return;

      const status = payload.status ?? '';
      const pct = payload.pct ?? payload.percent ?? 0;

      if (status === 'error' || status === 'crashed' || payload.error) {
        setIsLoading(false);
        setLoadingPath('');
        setLoadPct(0);
        setLoadPhase('error');
        setLoadMsg('✗ ' + (payload.error || payload.msg || 'Load failed'));
        fetchModels();
        return;
      }

      setLoadPct(pct);
      setLoadMsg(payload.msg || payload.message || '');
      setLoadPhase(payload.phase || status);

      if (pct >= 100 || status === 'ready' || status === 'unloaded') {
        setIsLoading(false);
        setLoadingPath('');
        setTimeout(() => fetchModels(), 500);
      } else {
        setIsLoading(true);
      }
    };
    window.addEventListener('iris:ws_message', handler as EventListener);
    return () => window.removeEventListener('iris:ws_message', handler as EventListener);
  }, []);

  // ── Load a model ─────────────────────────────────────────────────────
  // Straight down the WebSocket `load_local_model` path. That handler is the
  // single source of truth: it honors the backend load result, wires the kernel
  // to the iris_local provider, and registers the provider in the
  // InferenceRouter — which is what makes a local model behave like an API-key
  // provider in the reasoning/tool dropdowns.
  //
  // This used to dispatch a `model-load-request` CustomEvent that
  // dark-glass-dashboard listened for and forwarded to the same sendMessage.
  // The panel is a direct child of that dashboard, so the bounce bought
  // nothing and cost the one thing that matters: if the listener was not
  // mounted, the click vanished with no error and the spinner ran for a
  // minute. sendMessage arrives as a prop now, and its absence is reported.
  //
  // No `profile` is sent. The backend picks it per model from the real GGUF
  // shape and free VRAM (recommend_profile -> derive_config); a hardcoded
  // 'balanced' here would just be overridden.
  //
  // withProjector (REQ-4 AC2): defaults to true — attaching the projector is
  // the default per Decisions Locked 6. `with_projector` is only added to the
  // payload when the caller opted OUT, mirroring the backend's own
  // back-compat contract (`payload.get("with_projector", True)` — an ABSENT
  // key still means attach; CT-5).
  const doLoad = (path: string, withProjector: boolean = true) => {
    if (!path || isLoading) return;
    if (!sendMessage) {
      setLoadPhase('error');
      setLoadMsg('✗ Not connected to backend');
      return;
    }
    setLoadingPath(path);
    setIsLoading(true);
    setLoadPct(0);
    setLoadPhase('loading');
    setLoadMsg(withProjector ? 'Loading model…' : 'Loading model (text-only)…');
    const payload: { model_path: string; with_projector?: false } = { model_path: path };
    if (!withProjector) payload.with_projector = false;
    const sent = sendMessage('load_local_model', payload);
    if (!sent) {
      setIsLoading(false);
      setLoadingPath('');
      setLoadPhase('error');
      setLoadMsg('✗ WebSocket not connected — load not sent');
    }
  };

  // ── Unload current model ─────────────────────────────────────────────
  // Also over the WebSocket, so load and unload share ONE path. The HTTP
  // /api/models/unload endpoint stops the server but cannot de-wire the kernel
  // or drop the provider from the router, which left a dead `local:<stem>`
  // entry selectable in the Brain/Tool dropdowns after an unload.
  const doUnload = () => {
    if (isLoading) return;
    if (!sendMessage) {
      setLoadPhase('error');
      setLoadMsg('✗ Not connected to backend');
      return;
    }
    setIsLoading(true);
    setLoadPhase('unloading');
    setLoadMsg('Unloading model…');
    const sent = sendMessage('unload_local_model', {});
    if (!sent) {
      setIsLoading(false);
      setLoadPhase('error');
      setLoadMsg('✗ WebSocket not connected — unload not sent');
      return;
    }
    setSelectedPath('');
  };

  // ── Select a model (fills the field in inference mode) ───────────────
  const selectModel = (m: ModelEntry) => {
    setSelectedPath(m.path);
    window.dispatchEvent(new CustomEvent('model-selected', {
      detail: {
        path: m.path,
        name: m.filename,
        native_ctx: m.native_ctx || 4096,
        quantization: m.quantization || '',
        params_b: m.params_b || 0,
      }
    }));
  };

  // ── Vision fallback ladder (REQ-10 AC2/AC3) ──────────────────────────
  // Persisted straight down the SAME confirm_card channel every other
  // settings section on this WebSocket already uses (see the local_model /
  // inference_mode sections in iris_gateway.py) — no new message type.
  // `section_id: 'vision_fallback_ladder'` is a new confirm_card section,
  // not a new channel. Fires on every add/remove/reorder; there is no
  // separate Save step, matching this panel's existing "action = persisted
  // immediately" idiom (doLoad/doUnload).
  const persistLadder = (next: string[]) => {
    setVisionLadder(next);
    if (!sendMessage) {
      setLadderMsg('✗ Not connected to backend — ladder not saved');
      return;
    }
    const sent = sendMessage('confirm_card', {
      section_id: 'vision_fallback_ladder',
      values: { vision_fallback_ladder: next },
    });
    setLadderMsg(sent ? '' : '✗ WebSocket not connected — ladder not saved');
  };

  const toggleLadderModel = (path: string) => {
    const next = visionLadder.includes(path)
      ? visionLadder.filter(p => p !== path)
      : [...visionLadder, path];
    persistLadder(next);
  };

  // Order = priority (REQ-10 AC2). Swaps the entry with its neighbor rather
  // than a full drag-and-drop reorder — fewer moving parts, same result, and
  // matches the up/down idiom already legible at a glance.
  const moveLadderModel = (path: string, direction: -1 | 1) => {
    const idx = visionLadder.indexOf(path);
    if (idx === -1) return;
    const swapIdx = idx + direction;
    if (swapIdx < 0 || swapIdx >= visionLadder.length) return;
    const next = [...visionLadder];
    [next[idx], next[swapIdx]] = [next[swapIdx], next[idx]];
    persistLadder(next);
  };

  return (
    <div className="flex flex-col h-full" style={{ color: fontColor }}>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0"
        style={{ borderColor: glowColor + '40' }}>
        <div className="text-sm font-semibold">MODELS BROWSER</div>
        <div className="text-[10px] opacity-60 truncate ml-2" title={modelsDir}>
          {modelsDir || 'No directory'}
        </div>
      </div>

      {/* ── Vision fallback ladder (REQ-10 AC1/AC2/AC5) ───────────────
          Only rendered when there is at least one has_vision candidate —
          an empty section for a models directory with no vision models
          would just be noise. Order is priority, made legible with a
          numbered pill per selected model rather than leaving it implicit
          in list position alone. */}
      {visionCandidates.length > 0 && (
        <div
          className="px-3 py-2 border-b shrink-0"
          style={{ borderColor: glowColor + '30' }}
          data-testid="vision-ladder-section"
        >
          <div className="flex items-center justify-between mb-1.5">
            <div className="text-[10px] font-semibold tracking-wide" style={{ color: glowColor }}>
              VISION FALLBACK LADDER
            </div>
            {/* REQ-10 AC5: nothing chosen must read as a deliberate AUTO
                state, never an empty/broken list. */}
            {visionLadder.length === 0 ? (
              <span
                className="text-[9px] px-1.5 py-[1px] rounded font-medium"
                style={{ backgroundColor: glowColor + '15', color: glowColor }}
                title="No models selected — the widest has_vision model that fits current free VRAM is used"
              >
                AUTO — widest that fits
              </span>
            ) : (
              <span className="text-[9px] opacity-50">{visionLadder.length} in ladder</span>
            )}
          </div>
          <div className="flex flex-col gap-1">
            {visionCandidates.map(m => {
              const priority = visionLadder.indexOf(m.path);
              const inLadder = priority !== -1;
              return (
                <div
                  key={m.path}
                  data-testid={`vision-candidate-${m.path}`}
                  className="flex items-center gap-1.5 text-[10px] px-1.5 py-1 rounded"
                  style={{ backgroundColor: inLadder ? glowColor + '10' : 'transparent' }}
                >
                  <button
                    onClick={() => toggleLadderModel(m.path)}
                    title={
                      inLadder
                        ? 'Remove from the vision fallback ladder'
                        : 'Add to the vision fallback ladder'
                    }
                    className="w-4 h-4 rounded-full flex items-center justify-center text-[9px]
                      font-bold shrink-0 border transition-colors"
                    style={{
                      borderColor: glowColor + '50',
                      backgroundColor: inLadder ? glowColor : 'transparent',
                      color: inLadder ? '#000' : glowColor,
                    }}
                  >
                    {inLadder ? priority + 1 : '+'}
                  </button>
                  <span className="flex-1 truncate">{m.display_name || m.filename}</span>
                  {/* Size + projector cost — the fallback's footprint is
                      weights + projector, and that must be visible to make
                      the choice informed (REQ-10 AC2 in spirit). */}
                  <span className="opacity-50 shrink-0">
                    {m.size_gb > 0 ? `${m.size_gb.toFixed(1)}GB` : ''}
                    {(m.mmproj_size_gb ?? 0) > 0 ? ` +${(m.mmproj_size_gb ?? 0).toFixed(1)}GB proj` : ''}
                  </span>
                  {inLadder && (
                    <div className="flex gap-0.5 shrink-0">
                      <button
                        onClick={() => moveLadderModel(m.path, -1)}
                        disabled={priority === 0}
                        title="Higher priority"
                        className="w-4 h-4 flex items-center justify-center disabled:opacity-20"
                        style={{ color: glowColor }}
                      >
                        ↑
                      </button>
                      <button
                        onClick={() => moveLadderModel(m.path, 1)}
                        disabled={priority === visionLadder.length - 1}
                        title="Lower priority"
                        className="w-4 h-4 flex items-center justify-center disabled:opacity-20"
                        style={{ color: glowColor }}
                      >
                        ↓
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {ladderMsg && <div className="text-[9px] mt-1" style={{ color: '#ff6b6b' }}>{ladderMsg}</div>}
        </div>
      )}

      {/* ── Load progress bar (global, visible while any model loads) ── */}
      {isLoading && (
        <div className="px-3 py-2 border-b shrink-0" style={{ borderColor: glowColor + '30' }}>
          <div className="flex items-center justify-between mb-1">
            <div className="text-[10px] font-medium truncate flex items-center gap-1.5" style={{ color: glowColor }}>
              <span className="inline-block w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ backgroundColor: glowColor }} />
              {loadPhase ? loadPhase.toUpperCase() : 'LOADING'}
            </div>
            <div className="text-[10px] font-mono" style={{ color: fontColor }}>{loadPct}%</div>
          </div>
          <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: glowColor + '20' }}>
            <div className="h-full rounded-full transition-all duration-300 ease-out"
              style={{
                width: `${loadPct}%`,
                backgroundColor: glowColor,
                boxShadow: `0 0 8px ${glowColor}60`,
              }} />
          </div>
          {loadMsg && <div className="text-[9px] opacity-50 mt-1 truncate">{loadMsg}</div>}
        </div>
      )}

      {/* ── Model list ─────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-2 py-1" data-testid="model-list">
        {loading && (
          <div className="flex items-center justify-center h-24">
            <div className="text-xs animate-pulse">Scanning models…</div>
          </div>
        )}
        {error && (
          <div className="flex items-center justify-center h-24">
            <div className="text-xs" style={{ color: '#ff6b6b' }}>{error}</div>
          </div>
        )}
        {!loading && !error && models.length === 0 && (
          <div className="flex flex-col items-center justify-center h-24 gap-1">
            <div className="text-xs opacity-60">No GGUF models found</div>
            <div className="text-[10px] opacity-40">Check models directory setting</div>
          </div>
        )}

        {!loading && models.map((m, i) => {
          const isSelected = selectedPath === m.path;
          const isThisLoading = loadingPath === m.path;
          return (
            <div
              key={m.path}
              data-testid={`model-row-${m.path}`}
              className={`group flex items-center gap-1.5 px-2 py-1.5 rounded cursor-pointer text-xs transition-all ${
                m.loaded ? 'bg-green-500/8' : isSelected ? 'bg-white/10' : 'hover:bg-white/5'
              }`}
              style={{
                borderBottom: i < models.length - 1 ? `1px solid ${glowColor}10` : 'none',
                borderLeft: m.loaded ? `2px solid ${LOADED_GREEN}` : isSelected ? `2px solid ${glowColor}50` : '2px solid transparent',
              }}
              onClick={() => selectModel(m)}
            >
              {/* Icon */}
              <div className="w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold shrink-0"
                style={{
                  backgroundColor: m.loaded ? LOADED_GREEN + '25' : glowColor + '20',
                  color: m.loaded ? LOADED_GREEN : glowColor,
                }}>
                {m.architecture?.slice(0, 2).toUpperCase() || 'GG'}
              </div>

              {/* Model info — clickable to select */}
              <div className="flex-1 min-w-0 cursor-pointer" onClick={() => selectModel(m)}>
                <div className={`font-medium truncate ${m.loaded ? 'text-green-400' : ''}`}>
                  {m.display_name || m.filename}
                  {/* REQ-5 AC3: has_vision comes straight off scan_models — a
                      sibling mmproj-*.gguf matched this base model by stem
                      (T1). The projector itself never appears as its own
                      row (REQ-5 AC1); this badge is the only place its
                      existence surfaces. */}
                  {m.has_vision && (
                    <span
                      className="ml-1.5 px-1 py-[1px] rounded text-[8px] font-semibold align-middle"
                      style={{ backgroundColor: glowColor + '20', color: glowColor }}
                      title="Vision-capable — a CLIP projector loads alongside this model by default"
                    >
                      VISION
                    </span>
                  )}
                </div>
                {/* Row 1 — what the file IS. Row 2 — what loading it WILL do.
                    The plan comes from the backend's own recommend_profile +
                    derive_config, so it cannot drift from the loader. */}
                <div className="flex gap-2 text-[9px] opacity-50">
                  {m.quantization && m.quantization !== 'unknown' && <span>{m.quantization}</span>}
                  {m.size_gb > 0 && <span>{m.size_gb.toFixed(1)}GB</span>}
                  {m.native_ctx > 0 && <span>{fmtCtx(m.native_ctx)} native</span>}
                </div>
                {m.plan && (
                  <div
                    className="flex gap-2 text-[9px]"
                    style={{ color: m.plan.fits ? glowColor : '#f59e0b', opacity: 0.85 }}
                    title={
                      m.plan.fits
                        ? `Loads with the ${m.plan.profile} profile: ${m.plan.n_ctx} context, `
                          + `${m.plan.kv_cache} KV cache, ~${m.plan.vram_gb}GB of `
                          + `${m.plan.vram_free_gb}GB free VRAM`
                        : m.plan.reason
                    }
                  >
                    {m.plan.fits ? (
                      <>
                        <span>→ {fmtCtx(m.plan.n_ctx)} ctx</span>
                        <span>{m.plan.vram_gb.toFixed(1)}GB VRAM</span>
                        <span className="opacity-70">{m.plan.profile}</span>
                        {/* REQ-4 AC5 (Decisions Locked 6): the projector is
                            attached by default and its cost must be SURFACED,
                            never hidden. vram_gb above already includes it
                            (T8 re-plans with mmproj_size_gb) — this adds the
                            isolated figure plus the measured generation-speed
                            hit, so the user can knowingly trade speed for
                            sight rather than discover the cost after the
                            click. The -35% is the one measured reference
                            point we have (gemma-4-E4B); per-model generation
                            speed is not measured here, so the tooltip names
                            the source rather than implying it is per-model. */}
                        {m.has_vision && (m.plan.mmproj_gb ?? 0) > 0 && (
                          <span
                            style={{ color: '#f59e0b' }}
                            title={`Vision projector adds ${(m.plan.mmproj_gb ?? 0).toFixed(1)}GB VRAM (already counted above). Attaching a projector measurably slows generation — gemma-4-E4B: 64.5 → 42.1 tok/s (~-35%). Use "Text only" to load without it.`}
                          >
                            +{(m.plan.mmproj_gb ?? 0).toFixed(1)}GB vision (~-35% gen)
                          </span>
                        )}
                      </>
                    ) : (
                      <span>⚠ {m.plan.reason || "won't fit"}</span>
                    )}
                  </div>
                )}
              </div>

              {/* ── Per-model action button ── */}
              {(() => {
                if (m.loaded) {
                  // Loaded → show Unload on hover (glass-pill red)
                  return (
                    <button
                      onClick={(e) => { e.stopPropagation(); doUnload(); }}
                      disabled={isLoading}
                      className="flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full
                        opacity-0 group-hover:opacity-100 transition-all duration-200 shrink-0 disabled:opacity-20
                        hover:scale-105 active:scale-95"
                      style={{
                        backgroundColor: '#ef444415',
                        color: '#ef4444',
                        border: '1px solid #ef444430',
                        backdropFilter: 'blur(8px)',
                      }}
                    >
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                      </svg>
                      Unload
                    </button>
                  );
                }
                if (isThisLoading) {
                  // Currently loading this model
                  return (
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full shrink-0"
                      style={{
                        backgroundColor: glowColor + '12',
                        color: glowColor + 'aa',
                        border: `1px solid ${glowColor}20`,
                      }}>
                      <span className="inline-block w-2 h-2 rounded-full border-2 border-t-transparent animate-spin"
                        style={{ borderColor: glowColor + '80', borderTopColor: 'transparent' }} />
                      {loadPct}%
                    </div>
                  );
                }
                // Not loaded → glass-pill Load on hover/select
                const show = isSelected || false;  // always visible when selected
                return (
                  <div className="flex items-center gap-1 shrink-0">
                    {/* REQ-4 AC2: load without the projector. Only offered for
                        has_vision models — a text-only model has nothing to
                        opt out of. Sends with_projector: false; default Load
                        (right) stays attach-by-default (CT-5 back-compat). */}
                    {m.has_vision && (
                      <button
                        onClick={(e) => { e.stopPropagation(); doLoad(m.path, false); }}
                        disabled={isLoading}
                        title="Load without the vision projector — text-only, faster generation, no vision VRAM"
                        className={`text-[9px] font-medium px-2 py-1 rounded-full border
                          transition-all duration-200 disabled:opacity-20
                          hover:scale-105 active:scale-95 ${
                            isSelected ? '' : 'opacity-0 group-hover:opacity-100'
                          }`}
                        style={{
                          backgroundColor: 'transparent',
                          color: fontColor + 'aa',
                          borderColor: glowColor + '25',
                        }}
                      >
                        Text only
                      </button>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); doLoad(m.path); }}
                      disabled={isLoading}
                      className={`flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full
                        transition-all duration-200 shrink-0 disabled:opacity-20
                        hover:scale-105 active:scale-95 ${
                          isSelected ? '' : 'opacity-0 group-hover:opacity-100'
                        }`}
                      style={{
                        backgroundColor: glowColor + '12',
                        color: glowColor,
                        border: `1px solid ${glowColor}25`,
                        backdropFilter: 'blur(8px)',
                      }}
                    >
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      Load
                    </button>
                  </div>
                );
              })()}
            </div>
          );
        })}
      </div>

      {/* ── Footer — model count + Rescan ─────────────────────────── */}
      <div className="px-3 py-2 border-t shrink-0 flex items-center justify-between"
        style={{ borderColor: glowColor + '30' }}>
        <div className="text-[10px] opacity-40">{models.length} model{models.length !== 1 ? 's' : ''}</div>
        <button
          onClick={fetchModels}
          className="text-[10px] px-2 py-0.5 rounded hover:bg-white/10 transition-colors"
          style={{ color: glowColor }}
          disabled={loading}
        >
          {loading ? 'Scanning…' : '↻ Rescan'}
        </button>
      </div>
    </div>
  );
}
