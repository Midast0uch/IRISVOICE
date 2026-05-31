import React, { useEffect, useState } from 'react';

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
}

interface ModelBrowserPanelProps {
  glowColor: string;
  fontColor: string;
}

const LOADED_GREEN = '#22c55e';

export function ModelBrowserPanel({ glowColor, fontColor }: ModelBrowserPanelProps) {
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

  const loadedModel = models.find(m => m.loaded);

  // ── Fetch model list ────────────────────────────────────────────────
  const fetchModels = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/models');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setModels(data.models || []);
      setModelsDir(data.models_dir || '');
    } catch (err: any) {
      setError(err.message || 'Failed to load models');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  // ── WS progress listener ─────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (!detail || detail.type !== 'model_load_progress') return;
      const pct = detail.percent ?? 0;
      setLoadPct(pct);
      setLoadMsg(detail.message || '');
      setLoadPhase(detail.phase || '');
      setIsLoading(pct < 100);
      if (pct >= 100) {
        setTimeout(() => fetchModels(), 500);
      }
    };
    window.addEventListener('iris:ws_message', handler as EventListener);
    return () => window.removeEventListener('iris:ws_message', handler as EventListener);
  }, []);

  // ── Load a model ─────────────────────────────────────────────────────
  const doLoad = async (path: string) => {
    if (!path || isLoading) return;
    setLoadingPath(path);
    setIsLoading(true);
    setLoadMsg('Loading model…');
    setLoadPhase('loading');
    try {
      const res = await fetch('/api/models/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, profile: 'balanced' }),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        setLoadMsg('Model loaded ✓');
        setLoadPct(100);
        setTimeout(() => fetchModels(), 300);
      } else if (data.status === 'loading') {
        // Started in background — progress comes via WS events
        setLoadMsg(data.message || 'Loading…');
        setLoadPct(0);
      } else {
        setLoadMsg('✗ ' + (data.message || 'Unknown error'));
        setLoadPct(0);
      }
    } catch (err: any) {
      setLoadMsg('✗ ' + (err.message || 'Connection failed'));
      setLoadPct(0);
    } finally {
      setLoadingPath('');
      // Keep progress bar alive until WS says 100% or timeout
      setTimeout(() => setIsLoading(false), 60000);
    }
  };

  // ── Unload current model ─────────────────────────────────────────────
  const doUnload = async () => {
    if (isLoading) return;
    setIsLoading(true);
    setLoadMsg('Unloading model…');
    setLoadPhase('unloading');
    try {
      const res = await fetch('/api/models/unload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.status === 'ok') {
        setLoadMsg('Model unloaded ✓');
        setSelectedPath('');
        setTimeout(() => fetchModels(), 300);
      } else {
        setLoadMsg('✗ ' + (data.message || 'Unknown'));
      }
    } catch (err: any) {
      setLoadMsg('✗ ' + (err.message || 'Connection failed'));
    } finally {
      setTimeout(() => setIsLoading(false), 2500);
    }
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
      <div className="flex-1 overflow-y-auto px-2 py-1">
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
                </div>
                <div className="flex gap-2 text-[9px] opacity-50">
                  {m.quantization && <span>{m.quantization}</span>}
                  {m.params_b > 0 && <span>{m.params_b.toFixed(1)}B</span>}
                  {m.vram_estimate_gb > 0 && <span>~{m.vram_estimate_gb.toFixed(1)}GB VRAM</span>}
                  {m.size_gb > 0 && <span>{m.size_gb.toFixed(1)}GB</span>}
                </div>
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
