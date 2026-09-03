/**
 * Regression test for the ModelSwitcher/Dashboard provider-state desync.
 *
 * Root cause (verified against hooks/useInferenceState.ts before this fix):
 * the `role_bindings_updated` handler gated the ENTIRE update on
 * `snapshot.providers` being present —
 *
 *     if (snapshot && snapshot.providers) { ...apply fields... }
 *
 * iris_gateway.py's `set_model_selection` broadcast site sends
 * `{"role_bindings": [...]}` with NO `providers` key. That payload made the
 * guard false, so the WHOLE update — including `role_bindings` — was
 * silently dropped. No error, no warning: `ModelSwitcher`, the dashboard's
 * Model & Inference card, and the wheel-view `SidePanel` (all four
 * `useInferenceState()` instances) simply never saw the applied config.
 *
 * The fix replaces the all-or-nothing guard with a field-wise merge: apply
 * whatever fields ARE present, never blank a field that is absent.
 */
import "@testing-library/jest-dom";
import { renderHook, act } from "@testing-library/react";
import { useInferenceState } from "@/hooks/useInferenceState";

// Track isConnected so tests can toggle it.
let mockIsConnected = false;
const mockSendMessage = jest.fn();
jest.mock("@/hooks/useIRISWebSocket", () => ({
  useIRISWebSocket: () => ({ sendMessage: mockSendMessage, isConnected: mockIsConnected }),
}));

/** Set isConnected and trigger the useEffect by re-rendering the hook. */
function setConnected(connected: boolean) {
  mockIsConnected = connected;
}

/** Fire the singular role_binding_updated event (direct reply to sender). */
function fireRoleBindingUpdated(detail: { snapshot?: unknown }) {
  window.dispatchEvent(new CustomEvent("iris:role_binding_updated", { detail }));
}

const INITIAL_SNAPSHOT = {
  providers: [
    { id: "cerebras", label: "Cerebras", kind: "API", model: "gemma-4-31b", has_key: true, purpose: "chat" },
  ],
  role_bindings: [{ role: "reasoning", instance_id: "cerebras" }],
  default_role: "reasoning",
  provider_presets: [
    { id: "cerebras", label: "Cerebras", kind: "api", needs_key: true, api_base_url: "https://api.cerebras.ai/v1" },
  ],
  model_catalog: { cerebras: [{ id: "gemma-4-31b", name: "Gemma 4 31B" }] },
};

function mockFetchOnce(body: unknown) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  }) as unknown as typeof fetch;
}

function fireRoleBindingsUpdated(detail: unknown) {
  window.dispatchEvent(new CustomEvent("iris:role_bindings_updated", { detail }));
}

describe("useInferenceState — role_bindings_updated field-wise merge", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("applies role_bindings from a payload that has NO `providers` key (the exact silent-drop case)", async () => {
    mockFetchOnce(INITIAL_SNAPSHOT);
    const { result } = renderHook(() => useInferenceState());

    // Let the mount-time fetch resolve and populate initial state.
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "cerebras" }]);

    // Exactly what iris_gateway.py's set_model_selection broadcast sent
    // before the fix: role_bindings only, no `providers` key at all.
    act(() => {
      fireRoleBindingsUpdated({
        role_bindings: [{ role: "reasoning", instance_id: "openai" }],
      });
    });

    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "openai" }]);
  });

  it("does not blank existing providers/provider_presets when a payload omits them", async () => {
    mockFetchOnce(INITIAL_SNAPSHOT);
    const { result } = renderHook(() => useInferenceState());
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.providers).toHaveLength(1);
    expect(result.current.provider_presets).toHaveLength(1);

    act(() => {
      fireRoleBindingsUpdated({
        role_bindings: [{ role: "tool_execution", instance_id: "openai" }],
      });
    });

    // The fields the payload didn't carry must survive untouched — a
    // field-wise merge, not an all-or-nothing replace.
    expect(result.current.providers).toEqual(INITIAL_SNAPSHOT.providers);
    expect(result.current.provider_presets).toEqual(INITIAL_SNAPSHOT.provider_presets);
    expect(result.current.role_bindings).toEqual([{ role: "tool_execution", instance_id: "openai" }]);
  });

  it("still applies a FULL snapshot payload (providers present) — the already-working path stays working", async () => {
    mockFetchOnce(INITIAL_SNAPSHOT);
    const { result } = renderHook(() => useInferenceState());
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      fireRoleBindingsUpdated({
        providers: [
          { id: "openai", label: "OpenAI", kind: "API", model: "gpt-4o", has_key: true, purpose: "chat" },
        ],
        role_bindings: [{ role: "reasoning", instance_id: "openai" }],
        default_role: "reasoning",
        provider_presets: INITIAL_SNAPSHOT.provider_presets,
        model_catalog: { openai: [{ id: "gpt-4o", name: "GPT-4o" }] },
      });
    });

    expect(result.current.providers).toEqual([
      { id: "openai", label: "OpenAI", kind: "API", model: "gpt-4o", has_key: true, purpose: "chat" },
    ]);
    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "openai" }]);
  });
});

/* ------------------------------------------------------------------ */
/*  Fix 1 — version-staleness check on isConnected re-fetch            */
/* ------------------------------------------------------------------ */

describe("useInferenceState — isConnected re-fetch version-staleness", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    setConnected(false);
  });

  it("discards stale REST data when a WS binding update arrives mid-fetch", async () => {
    // Arrange: create a deferred fetch promise we control.
    let resolveFetch!: (data: unknown) => void;
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = (body: unknown) => {
        resolve({ ok: true, json: async () => body } as Response);
      };
    });
    global.fetch = jest.fn().mockReturnValue(fetchPromise);

    // Mount with isConnected=true so the re-fetch fires.
    setConnected(true);
    const { result } = renderHook(() => useInferenceState());

    // Let the mount fetch resolve first so we have initial state.
    await act(async () => {
      resolveFetch(INITIAL_SNAPSHOT);
      await Promise.resolve();
    });
    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "cerebras" }]);

    // Now trigger isConnected re-fetch by toggling connected state.
    // The hook's useEffect depends on isConnected, so we need to re-render.
    // Since isConnected is a module-level variable, the hook reads it on
    // every render. We need to force a re-render by triggering a state
    // change, then resolve the fetch AFTER a WS binding update.
    //
    // Create a new deferred fetch for the re-fetch.
    let resolveReFetch!: (data: unknown) => void;
    const reFetchPromise = new Promise<Response>((resolve) => {
      resolveReFetch = (body: unknown) => {
        resolve({ ok: true, json: async () => body } as Response);
      };
    });
    global.fetch = jest.fn().mockReturnValue(reFetchPromise);

    // Toggle isConnected to trigger the re-fetch effect.
    setConnected(false);
    // Re-render by triggering a small state change
    await act(async () => {
      // Fire a harmless event to trigger re-render
      window.dispatchEvent(new CustomEvent("iris:system_status", {
        detail: { inference: { default_role: "reasoning" } },
      }));
    });

    setConnected(true);
    await act(async () => {
      // Re-render to pick up isConnected=true
      window.dispatchEvent(new CustomEvent("iris:system_status", {
        detail: { inference: { default_role: "reasoning" } },
      }));
    });

    // The re-fetch is now in flight. Fire a WS binding update BEFORE
    // the fetch resolves — this is the race condition.
    act(() => {
      fireRoleBindingUpdated({
        snapshot: {
          role_bindings: [{ role: "reasoning", instance_id: "openai" }],
        },
      });
    });
    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "openai" }]);

    // Now resolve the stale fetch with OLD data (cerebras).
    await act(async () => {
      resolveReFetch({
        ...INITIAL_SNAPSHOT,
        role_bindings: [{ role: "reasoning", instance_id: "cerebras" }],
      });
      await Promise.resolve();
    });

    // The stale data must be DISCARDED — role_bindings should still be openai.
    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "openai" }]);
  });

  it("applies REST data when no WS binding update raced ahead", async () => {
    let resolveFetch!: (data: unknown) => void;
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = (body: unknown) => {
        resolve({ ok: true, json: async () => body } as Response);
      };
    });
    global.fetch = jest.fn().mockReturnValue(fetchPromise);

    setConnected(true);
    const { result } = renderHook(() => useInferenceState());

    // Let mount fetch resolve.
    await act(async () => {
      resolveFetch(INITIAL_SNAPSHOT);
      await Promise.resolve();
    });

    // Trigger re-fetch
    let resolveReFetch!: (data: unknown) => void;
    const reFetchPromise = new Promise<Response>((resolve) => {
      resolveReFetch = (body: unknown) => {
        resolve({ ok: true, json: async () => body } as Response);
      };
    });
    global.fetch = jest.fn().mockReturnValue(reFetchPromise);

    setConnected(false);
    await act(async () => {
      window.dispatchEvent(new CustomEvent("iris:system_status", {
        detail: { inference: { default_role: "reasoning" } },
      }));
    });

    setConnected(true);
    await act(async () => {
      window.dispatchEvent(new CustomEvent("iris:system_status", {
        detail: { inference: { default_role: "reasoning" } },
      }));
    });

    // Resolve the fetch WITHOUT any WS binding update in between.
    const NEW_DATA = {
      ...INITIAL_SNAPSHOT,
      role_bindings: [{ role: "reasoning", instance_id: "openai" }],
    };
    await act(async () => {
      resolveReFetch(NEW_DATA);
      await Promise.resolve();
    });

    // The data should be applied since no WS update raced ahead.
    expect(result.current.role_bindings).toEqual([{ role: "reasoning", instance_id: "openai" }]);
  });
});
