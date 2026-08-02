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

jest.mock("@/hooks/useIRISWebSocket", () => ({
  useIRISWebSocket: () => ({ sendMessage: jest.fn() }),
}));

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
