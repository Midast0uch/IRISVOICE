'use client';

import { useState, useEffect, useCallback } from 'react';
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
  const { sendMessage } = useIRISWebSocket();
  const [state, setState] = useState<InferenceState>({
    providers: [],
    role_bindings: [],
    default_role: 'reasoning',
    provider_presets: [],
    model_catalog: {},
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch on mount
  useEffect(() => {
    let cancelled = false;
    fetch('/api/inference/state')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: InferenceState) => {
        if (!cancelled) {
          setState({
            providers: data.providers ?? [],
            role_bindings: data.role_bindings ?? [],
            default_role: data.default_role ?? 'reasoning',
            provider_presets: data.provider_presets ?? [],
            model_catalog: data.model_catalog ?? {},
          });
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn('[useInferenceState] Failed to fetch state:', err);
          setError(err.message);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, []);

  // Listen for provider_added — append or merge the new provider
  useEffect(() => {
    const handler = (e: Event) => {
      const provider = (e as CustomEvent).detail as Provider;
      if (provider && provider.id) {
        setState((prev) => ({
          ...prev,
          providers: [
            ...prev.providers.filter((p) => p.id !== provider.id),
            provider,
          ],
        }));
      }
    };
    window.addEventListener('iris:provider_added', handler as EventListener);
    return () => window.removeEventListener('iris:provider_added', handler as EventListener);
  }, []);

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
