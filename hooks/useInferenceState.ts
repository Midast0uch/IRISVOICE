'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useIRISWebSocket } from './useIRISWebSocket';

interface Provider {
  id: string;
  label: string;
  kind: 'API' | 'LOCAL_OPENAI' | 'INPROCESS' | 'OLLAMA' | 'api' | 'local_openai' | 'inprocess' | 'ollama';
  model: string;
  api_base_url?: string;
  // Phase 5 (D-4): boolean ONLY — never a key or fragment reaches the frontend.
  has_key?: boolean;
  // Phase 1 REQ-3 AC2 — truthful for local models as of Phase 3.
  loaded?: boolean;
  loading?: boolean;
  // Phase 1 REQ-4 AC3 — the ModelSwitcher (Phase 5 REQ-2 AC4) filters to "chat".
  purpose?: string;
}

interface ProviderPreset {
  id: string;
  label: string;
  kind: string;
  needs_key: boolean;
  api_base_url: string;
}

interface RoleBinding {
  role: string;
  instance_id: string;
  model_override?: string;
}

interface InferenceState {
  providers: Provider[];
  role_bindings: RoleBinding[];
  default_role: string;
  provider_presets: ProviderPreset[];
  model_catalog?: Record<string, { id: string; name: string }[]>;
}

export function useInferenceState() {
  const { sendMessage, isConnected } = useIRISWebSocket();
  const [state, setState] = useState<InferenceState>({
    providers: [],
    role_bindings: [],
    default_role: 'reasoning',
    provider_presets: [],
    model_catalog: {},
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Version counter incremented by every WS binding update. The isConnected
  // re-fetch captures this at start and discards its result if the version
  // changed while in flight — preventing the stale-fetch-overwrite race that
  // made dropdown selections appear to revert (a WS-driven binding update
  // arriving before the async REST fetch completes would get overwritten by
  // the older snapshot).
  const wsBindingVersionRef = useRef(0);

  // Fetch on mount.
  //
  // RETRIES. This used to be a single one-shot fetch: if it failed, `error`
  // was set and nothing ever asked again. The backend takes minutes to become
  // responsive on a cold start (it imports torch/numpy, probes every
  // configured provider endpoint and spawns the vision server), and the page
  // is often already open when it comes up — so the provider dropdowns stayed
  // empty until a manual refresh. That is the same class of bug as the
  // "provider card empty until refresh" one root-caused at main.py:1828,
  // just on the client instead of the server.
  //
  // Bounded: ~8 attempts over ~40s, cancelled on unmount. Long enough to
  // outlast a normal startup race; short enough that a genuinely dead backend
  // stops being hammered. Recovery after that is the reconnect effect below
  // and the WS liveness watchdog, both of which re-run a successful fetch.
  useEffect(() => {
    let cancelled = false;
    const MAX_ATTEMPTS = 8;
    const BASE_DELAY_MS = 1_200;

    const load = async () => {
      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        if (cancelled) return;
        try {
          const res = await fetch('/api/inference/state');
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = (await res.json()) as InferenceState;
          if (cancelled) return;
          setState({
            providers: data.providers ?? [],
            role_bindings: data.role_bindings ?? [],
            default_role: data.default_role ?? 'reasoning',
            provider_presets: data.provider_presets ?? [],
            model_catalog: data.model_catalog ?? {},
          });
          setError(null);
          setLoading(false);
          return;
        } catch (err) {
          if (cancelled) return;
          if (attempt === MAX_ATTEMPTS) {
            console.warn(
              `[useInferenceState] Gave up after ${attempt} attempts:`, err
            );
            setError((err as Error).message);
            setLoading(false);
            return;
          }
          if (process.env.NODE_ENV !== 'production') {
            console.warn(
              `[useInferenceState] Fetch attempt ${attempt}/${MAX_ATTEMPTS} failed, retrying:`,
              err
            );
          }
          await new Promise((r) => setTimeout(r, BASE_DELAY_MS * attempt));
        }
      }
    };

    void load();
    return () => { cancelled = true; };
  }, []);

  // Listen for provider_added — append, or merge FIELD-WISE into the existing
  // entry. Emission sites differ in how complete their payload is; replacing
  // the whole entry meant a payload that omitted `loaded` blanked it, and both
  // the ModelSwitcher and the settings panel gate local providers on `loaded` —
  // so a model demonstrably resident in VRAM vanished from the dropdowns.
  // Position is preserved too, so the list does not reshuffle on every event.
  useEffect(() => {
    const handler = (e: Event) => {
      const provider = (e as CustomEvent).detail as Provider;
      if (provider && provider.id) {
        setState((prev) => {
          const idx = prev.providers.findIndex((p) => p.id === provider.id);
          if (idx === -1) {
            return { ...prev, providers: [...prev.providers, provider] };
          }
          const next = [...prev.providers];
          next[idx] = { ...next[idx], ...provider };
          return { ...prev, providers: next };
        });
      }
    };
    window.addEventListener('iris:provider_added', handler as EventListener);
    return () => window.removeEventListener('iris:provider_added', handler as EventListener);
  }, []);

  // REQ-4 (specs/local-model-lifecycle-sync): re-fetch the inference snapshot
  // on every WS reconnect. The WS `request_state` push exists but depends on
  // `peek_active_kernel` (iris_gateway.py:7235) which can return None → empty
  // snapshot; REST `/api/inference/state` (main.py:1828) reads the shared
  // registry directly, so it is the reliable reconciliation that heals a stale
  // `loaded` flag — the red trigger on a resident local model. Field-wise merge
  // (`?? prev`) so a partial payload never clobbers provider_presets/catalog.
  useEffect(() => {
    if (!isConnected) return;
    let cancelled = false;
    const versionAtFetch = wsBindingVersionRef.current;
    fetch('/api/inference/state')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: InferenceState) => {
        if (!cancelled) {
          // Discard if a WS binding update arrived while the fetch was in
          // flight — the WS data is always newer than the REST snapshot.
          if (wsBindingVersionRef.current !== versionAtFetch) return;
          setState((prev) => ({
            ...prev,
            providers: data.providers ?? prev.providers,
            role_bindings: data.role_bindings ?? prev.role_bindings,
            default_role: data.default_role ?? prev.default_role,
            provider_presets: data.provider_presets ?? prev.provider_presets,
            model_catalog: data.model_catalog ?? prev.model_catalog,
          }));
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn('[useInferenceState] Reconnect fetch failed:', err);
        }
      });
    return () => { cancelled = true; };
  }, [isConnected]);

  // Listen for role_bindings_updated — merge FIELD-WISE. Broadcast sites
  // vary in which fields they include (e.g. a payload built before every
  // emission site sent the full snapshot), so gating the WHOLE update on
  // one field's presence (the old `if (snapshot.providers)` guard) silently
  // dropped updates that had everything BUT `providers` — that was the
  // ModelSwitcher desync bug. Apply each field that is actually present;
  // never overwrite existing state with `undefined`.
  useEffect(() => {
    const handler = (e: Event) => {
      const snapshot = (e as CustomEvent).detail as Partial<InferenceState> | undefined;
      if (snapshot) {
        wsBindingVersionRef.current++;
        setState((prev) => ({
          ...prev,
          providers: snapshot.providers ?? prev.providers,
          role_bindings: snapshot.role_bindings ?? prev.role_bindings,
          default_role: snapshot.default_role ?? prev.default_role,
          provider_presets: snapshot.provider_presets ?? prev.provider_presets,
          model_catalog: snapshot.model_catalog ?? prev.model_catalog,
        }));
      }
      setLoading(false);
    };
    window.addEventListener('iris:role_bindings_updated', handler as EventListener);
    return () => window.removeEventListener('iris:role_bindings_updated', handler as EventListener);
  }, []);

  // Direct reply `role_binding_updated` (singular) — useInferenceState ignored it
  // and only handled the broadcast plural, so a switch reverted when the
  // broadcast was missed. This is the root cause of the Brain/Tool revert.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { snapshot?: Partial<InferenceState> } | undefined;
      const snap = detail?.snapshot;
      if (snap) {
        wsBindingVersionRef.current++;
        setState((prev) => ({
          ...prev,
          providers: (snap as any).providers ?? prev.providers,
          role_bindings: (snap as any).role_bindings ?? prev.role_bindings,
          default_role: (snap as any).default_role ?? prev.default_role,
          provider_presets: (snap as any).provider_presets ?? prev.provider_presets,
          model_catalog: (snap as any).model_catalog ?? prev.model_catalog,
        }));
        setLoading(false);
      }
    };
    window.addEventListener('iris:role_binding_updated', handler as EventListener);
    return () => window.removeEventListener('iris:role_binding_updated', handler as EventListener);
  }, []);

  // Live-merge the periodic `system_status` broadcast.  The backend pushes
  // `router.snapshot()` (providers/role_bindings/default_role) inside every
  // system_status payload; the HUD already consumes it, but the inference
  // cards did not — so provider/model state only changed on user action or
  // full page reload (root-caused 2026-08-12, pin_05511443f03b).  Merge the
  // SAME field-wise way as role_bindings_updated so an update that carries
  // only some fields never clobbers the rest.  system_status does NOT carry
  // provider_presets/model_catalog, so those fields are deliberately left to
  // the REST fetch + role_bindings_updated — `?? prev` keeps them stable.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { inference?: Partial<InferenceState> }
        | undefined;
      const inf = detail?.inference;
      if (inf) {
        setState((prev) => ({
          ...prev,
          providers: inf.providers ?? prev.providers,
          role_bindings: inf.role_bindings ?? prev.role_bindings,
          default_role: inf.default_role ?? prev.default_role,
        }));
      }
    };
    window.addEventListener('iris:system_status', handler as EventListener);
    return () => window.removeEventListener('iris:system_status', handler as EventListener);
  }, []);

  // No refresh needed after a local load (Tauri bad UX). provider_added can be
  // missed if the session lookup fails — local_model_status with loaded=true
  // is the reliable terminal signal after a successful load, so re-fetch the
  // authoritative REST snapshot when it fires.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { status?: string } | undefined;
      if (detail?.status === 'loaded') {
        const versionAtFetch = wsBindingVersionRef.current;
        fetch('/api/inference/state')
          .then((res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json() as Promise<InferenceState>;
          })
          .then((data) => {
            // Discard if a WS binding update arrived while the fetch was in
            // flight — same race as the isConnected re-fetch.
            if (wsBindingVersionRef.current !== versionAtFetch) return;
            setState((prev) => ({
              ...prev,
              providers: data.providers ?? prev.providers,
              role_bindings: data.role_bindings ?? prev.role_bindings,
              default_role: data.default_role ?? prev.default_role,
              provider_presets: data.provider_presets ?? prev.provider_presets,
              model_catalog: data.model_catalog ?? prev.model_catalog,
            }));
            setLoading(false);
          })
          .catch(() => {});
      }
    };
    window.addEventListener('iris:local_model_status', handler as EventListener);
    return () => window.removeEventListener('iris:local_model_status', handler as EventListener);
  }, []);

  const sendRoleBinding = useCallback(
    (role: string, instanceId: string, modelOverride?: string) => {
      const payload: Record<string, unknown> = { role, instance_id: instanceId };
      if (modelOverride !== undefined && modelOverride !== '') {
        payload.model_override = modelOverride;
      }
      sendMessage('set_role_binding', payload);
    },
    [sendMessage]
  );

  // Configure an API/local provider (Provider dropdown + API key / endpoint).
  // Backed by the existing set_model_selection handler, which registers the
  // provider instance in the router and binds roles to it.
  const sendModelSelection = useCallback(
    (payload: {
      model_provider: string;
      reasoning_model?: string;
      tool_execution_model?: string;
      api_key?: string;
      api_base_url?: string;
      lmstudio_endpoint?: string;
    }) => {
      sendMessage('set_model_selection', payload);
    },
    [sendMessage]
  );

  // Apply inference-behaviour fields (Thinking Style / Max Response /
  // Reasoning Effort / Tool Mode). Backed by the confirm_card handler for the
  // inference_mode section.
  const sendInferenceMode = useCallback(
    (values: Record<string, string>) => {
      sendMessage('confirm_card', { section_id: 'inference_mode', values });
    },
    [sendMessage]
  );

  return {
    providers: state.providers,
    role_bindings: state.role_bindings,
    default_role: state.default_role,
    provider_presets: state.provider_presets,
    model_catalog: state.model_catalog,
    loading,
    error,
    sendRoleBinding,
    sendModelSelection,
    sendInferenceMode,
  };
}
