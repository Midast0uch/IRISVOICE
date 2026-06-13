"use client";

/**
 * useCaducean — React hook for live Caducean Engine state.
 *
 * v2: Polls the Tauri command `caducean_get_state` at 500ms intervals
 * and returns the latest state for the active session.
 *
 * Architecture (per plan):
 *   - Frontend calls invoke('caducean_get_state', { sessionId })
 *   - Tauri Rust proxies to GET /api/caducean/state?session_id=...
 *   - Python FastAPI calls ffi_caducean_get_state()
 *   - C++ iris_core.dll returns the SessionState
 *
 * Latency: ~500ms polling means at most 500ms staleness. This is
 * acceptable for v2; v3 will move to WebSocket broadcast when
 * latency becomes a felt problem.
 *
 * Usage:
 *   const { state, error, isLoading, refresh } = useCaducean(sessionId);
 *   if (state) console.log(state.u, state.xi, state.c_eff);
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

// ── Types — match the C++ CaduceanStateResponse and IrisDirectionSignal ──

export interface CaduceanState {
  session_id: string;
  engine_live: boolean;
  x: number;
  y: number;
  xi: number;
  u: number;
  a: number;
  b: number;
  s: number;
  c_eff: number;
}

export interface DirectionSignal {
  session_id: string;
  target_u: number;
  force_magnitude: number;
  u_current: number;
  phase: number;
  balance: number;
}

export interface CaduceanHealth {
  engine_live: boolean;
  engine_initialized_at: string | null;
}

export interface SetParamsResult {
  ok: boolean;
  session_id: string;
  applied: { a: number; b: number; s: number } | null;
}

// ── Main hook — polls state at 500ms intervals ─────────────────────

export interface UseCaduceanOptions {
  /** Polling interval in ms. Default 500. */
  pollMs?: number;
  /** If true, does not start polling (e.g., for dev panels that want manual refresh). */
  paused?: boolean;
}

export interface UseCaduceanResult {
  state: CaduceanState | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
  /** Most recent DirectionSignal (separate fetch — only called when state changes). */
  direction: DirectionSignal | null;
}

export function useCaducean(
  sessionId: string | null,
  options: UseCaduceanOptions = {}
): UseCaduceanResult {
  const { pollMs = 500, paused = false } = options;
  const [state, setState] = useState<CaduceanState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [direction, setDirection] = useState<DirectionSignal | null>(null);
  const inFlight = useRef(false);

  const fetchState = useCallback(async () => {
    if (!sessionId) return;
    if (inFlight.current) return; // skip overlapping requests
    inFlight.current = true;
    try {
      const result = await invoke<CaduceanState>("caducean_get_state", {
        sessionId,
      });
      setState(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
    }
  }, [sessionId]);

  const fetchDirection = useCallback(async () => {
    if (!sessionId) return;
    try {
      const result = await invoke<DirectionSignal>(
        "caducean_get_direction_signal",
        { sessionId, balance: 1.0 }
      );
      setDirection(result);
    } catch {
      // Direction is best-effort — don't overwrite main error
    }
  }, [sessionId]);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    await Promise.all([fetchState(), fetchDirection()]);
    setIsLoading(false);
  }, [fetchState, fetchDirection]);

  useEffect(() => {
    if (!sessionId || paused) {
      return;
    }
    // Initial fetch immediately
    refresh();
    // Set up polling
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [sessionId, pollMs, paused, refresh]);

  return { state, error, isLoading, refresh, direction };
}

// ── Helper hook — just for the health check (no polling) ───────────

export function useCaduceanHealth() {
  const [health, setHealth] = useState<CaduceanHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const result = await invoke<CaduceanHealth>("caducean_health");
        setHealth(result);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    fetchHealth();
    const id = setInterval(fetchHealth, 5000); // poll every 5s
    return () => clearInterval(id);
  }, []);

  return { health, error };
}

// ── Action hook — setParams mutation (no polling) ──────────────────

export interface SetParamsArgs {
  sessionId: string;
  a: number;
  b: number;
  s: number;
}

export function useCaduceanParams() {
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setParams = useCallback(
    async ({ sessionId, a, b, s }: SetParamsArgs): Promise<SetParamsResult | null> => {
      setIsPending(true);
      setError(null);
      try {
        const result = await invoke<SetParamsResult>("caducean_set_params", {
          sessionId,
          a,
          b,
          s,
        });
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        setIsPending(false);
      }
    },
    []
  );

  return { setParams, isPending, error };
}
