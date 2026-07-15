'use client';

import { useState, useEffect, useCallback } from 'react';
import { useIRISWebSocket } from './useIRISWebSocket';

interface Provider {
  id: string;
  label: string;
  kind: 'API' | 'LOCAL_OPENAI' | 'INPROCESS' | 'OLLAMA';
  model: string;
  api_base_url?: string;
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
}

export function useInferenceState() {
  const { sendMessage } = useIRISWebSocket();
  const [state, setState] = useState<InferenceState>({
    providers: [],
    role_bindings: [],
    default_role: 'reasoning',
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
          setState(data);
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

  // Listen for role_bindings_updated — full snapshot
  useEffect(() => {
    const handler = (e: Event) => {
      const snapshot = (e as CustomEvent).detail as InferenceState;
      if (snapshot && snapshot.providers) {
        setState(snapshot);
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

  return {
    providers: state.providers,
    role_bindings: state.role_bindings,
    default_role: state.default_role,
    loading,
    error,
    sendRoleBinding,
  };
}
