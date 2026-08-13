"use client";

import React, { memo, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CustomDropdown } from "@/components/ui/CustomDropdown";

/**
 * Model & Inference Section — shared by the dashboard wing and the wheel.
 *
 * Renders the full SLICE 5 "Model & Inference" card:
 *   • Provider setup   — pick an API/local provider, enter key / endpoint
 *   • Model routing    — Brain (reasoning) + Tool (tool_execution) role
 *                        selectors bound to provider instances (same or
 *                        different providers)
 *   • Per-role model   — a second dropdown per role showing models available
 *                        for the bound provider (from model_catalog), allowing
 *                        model override without changing the provider binding.
 *   • Inference behaviour — Thinking Style / Max Response / Reasoning
 *                        Effort / Tool Mode
 *   • Active Routing   — read-only summary of current role bindings
 *
 * All data is sourced from the backend routing layer via useInferenceState;
 * nothing is hardcoded.
 */
const ModelInferenceSection = memo(function ModelInferenceSection({
  providers,
  role_bindings,
  loading,
  sendRoleBinding,
  glowColor,
  provider_presets,
  sendModelSelection,
  sendInferenceMode,
  inferenceValues,
  model_catalog = {},
}: {
  providers: { id: string; label: string; kind: string; model: string; purpose?: string; has_key?: boolean; loaded?: boolean; loading?: boolean }[];
  role_bindings: { role: string; instance_id: string; model_override?: string }[];
  loading: boolean;
  sendRoleBinding: (role: string, instanceId: string, modelOverride?: string) => void;
  glowColor: string;
  provider_presets: { id: string; label: string; kind: string; needs_key: boolean; api_base_url: string }[];
  sendModelSelection: (payload: { model_provider: string; api_key?: string; api_base_url?: string; lmstudio_endpoint?: string }) => void;
  sendInferenceMode: (values: Record<string, string>) => void;
  inferenceValues?: Record<string, any>;
  model_catalog?: Record<string, { id: string; name: string }[]>;
}) {
  const [useSameModel, setUseSameModel] = useState(true);
  const [bindError, setBindError] = useState<string | null>(null);

  // Provider setup (API / local provider configuration)
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [apiKey, setApiKey] = useState<string>("");
  const [endpoint, setEndpoint] = useState<string>("http://localhost:1234");
  const [providerMsg, setProviderMsg] = useState<string | null>(null);
  const [providerStatus, setProviderStatus] = useState<"idle" | "applied">("idle");

  // Inference behaviour fields (from the old inference_mode card)
  const [thinkingStyle, setThinkingStyle] = useState<string>(inferenceValues?.agent_thinking_style ?? "balanced");
  const [maxResponse, setMaxResponse] = useState<string>(inferenceValues?.max_response_length ?? "medium");
  const [reasoningEffort, setReasoningEffort] = useState<string>(inferenceValues?.reasoning_effort ?? "balanced");
  const [toolMode, setToolMode] = useState<string>(inferenceValues?.tool_mode ?? "auto");

  // Listen for role_binding_error to show inline messages (e.g. binding to local with no model loaded)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { error?: string; role?: string; instance_id?: string } | undefined;
      if (detail?.error) setBindError(detail.error);
    };
    window.addEventListener("iris:role_binding_error", handler as EventListener);
    return () => window.removeEventListener("iris:role_binding_error", handler as EventListener);
  }, []);

  // Derive current binding values
  const brainBinding = role_bindings.find((r) => r.role === "reasoning");
  const toolBinding = role_bindings.find((r) => r.role === "tool_execution");

  const getProviderLabel = (instanceId: string) => {
    const p = providers.find((prov) => prov.id === instanceId);
    return p ? p.label : instanceId;
  };

  // Keep Provider Setup dropdown initialized with the active role binding, but allow user selection.
  useEffect(() => {
    const active = brainBinding?.instance_id || toolBinding?.instance_id || "";
    if (active && !selectedProvider) {
      setSelectedProvider(active);
    }
  }, [brainBinding?.instance_id, toolBinding?.instance_id, selectedProvider]);

  // Determine active provider: user-selected provider in Provider Setup takes priority,
  // falling back to active brain binding or first preset.
  const activeProviderId = selectedProvider || brainBinding?.instance_id || provider_presets[0]?.id || "opencodego";

  // Every provider instance the backend actually knows about that can serve a
  // chat role. This is what makes a locally-loaded GGUF selectable: it is
  // registered as a provider instance ("local:<stem>") but is NOT a preset, and
  // building the dropdown from presets alone meant a model sitting in VRAM could
  // never be chosen as the Brain or Tool model.
  const chatProviders = providers.filter(
    (p) => !p.purpose || p.purpose === "chat"
  );

  // Build model options for Brain/Tool dropdowns.
  // Prioritizes the active provider's models at the top, followed by every
  // provider preset and every registered chat provider instance.
  const buildModelOptions = () => {
    const options: { label: string; value: string }[] = [];
    const added = new Set<string>();

    const appendModelsForProvider = (pId: string) => {
      if (!pId || added.has(pId)) return;
      added.add(pId);

      const preset = provider_presets.find((p) => p.id === pId);
      const pInst = providers.find((p) => p.id === pId);
      const label = preset?.label || pInst?.label || pId;
      const catalog = model_catalog[pId] ?? [];

      if (catalog.length > 0) {
        for (const m of catalog) {
          options.push({
            label: `${label} · ${m.name}`,
            value: `${pId}::${m.id}`,
          });
        }
      } else {
        const defaultModel = pInst?.model || "";
        options.push({
          label: defaultModel ? `${label} · ${defaultModel}` : label,
          value: `${pId}::`,
        });
      }
    };

    // 1. Add active provider's catalog models first
    if (activeProviderId) {
      appendModelsForProvider(activeProviderId);
    }

    // 2. Add all other provider presets (all 15 providers)
    for (const preset of provider_presets) {
      appendModelsForProvider(preset.id);
    }

    // 3. Add every registered chat provider instance that is not a preset —
    //    loaded local models, ollama, any endpoint configured at runtime.
    for (const p of chatProviders) {
      appendModelsForProvider(p.id);
    }

    return options;
  };

  const modelOptions = buildModelOptions();

  // Provider Setup dropdown: presets plus any registered chat provider that has
  // no preset (again, the loaded local model), so it is reachable from here too.
  const providerSetupOptions = [
    ...provider_presets.map((p) => ({ label: p.label, value: p.id })),
    ...chatProviders
      .filter((p) => !provider_presets.some((pp) => pp.id === p.id))
      .map((p) => ({ label: p.label || p.id, value: p.id })),
  ];

  // Encode current binding as "providerId::modelOverride" for the dropdown value
  const encodeBrainValue = brainBinding
    ? `${brainBinding.instance_id}::${brainBinding.model_override || ""}`
    : "";
  const encodeToolValue = toolBinding
    ? `${toolBinding.instance_id}::${toolBinding.model_override || ""}`
    : "";

  const handleBrainChange = (encoded: string) => {
    setBindError(null);
    const [providerId, modelId] = encoded.split("::");
    if (providerId) setSelectedProvider(providerId);
    sendRoleBinding("reasoning", providerId, modelId || undefined);
    if (useSameModel) {
      sendRoleBinding("tool_execution", providerId, modelId || undefined);
    }
  };

  const handleToolChange = (encoded: string) => {
    setBindError(null);
    const [providerId, modelId] = encoded.split("::");
    if (providerId) setSelectedProvider(providerId);
    sendRoleBinding("tool_execution", providerId, modelId || undefined);
  };

  const handleSameModelToggle = (val: boolean) => {
    setUseSameModel(val);
    if (val && brainBinding?.instance_id) {
      sendRoleBinding("tool_execution", brainBinding.instance_id, brainBinding.model_override);
    }
  };

  // ── Provider setup handlers ──
  const selectedPreset = provider_presets.find((p) => p.id === selectedProvider);
  const needsKey = selectedPreset?.needs_key ?? false;
  const isLmstudio = selectedProvider === "lmstudio";
  // Does the backend already hold a key for the selected provider instance?
  const providerHasKey = !!providers.find((p) => p.id === selectedProvider)?.has_key;
  // When a key is already configured we don't require the user to re-enter it.
  const keyRequired = needsKey && !providerHasKey;

  const handleApplyProvider = () => {
    if (!selectedProvider || providerStatus === "applied") return;
    setProviderMsg(null);
    setProviderStatus("applied");  // optimistic — button shows "✓ Applied" immediately
    // The model sent with a provider MUST belong to that provider. Prefer the
    // model the backend already has registered for this exact instance, else
    // the provider's own catalog default. Sending "" here registered the new
    // provider with no model at all, and every downstream "which model?"
    // resolution then fell through to the value left over from the PREVIOUS
    // provider — that is how selecting Cohere produced "cohere · gemma-4-31b".
    const matchedProvider = providers.find((p) => p.id === selectedProvider);
    const modelForProvider =
      matchedProvider?.model || model_catalog[selectedProvider]?.[0]?.id || "";
    const payload: {
      model_provider: string;
      reasoning_model?: string;
      tool_execution_model?: string;
      api_key?: string;
      api_base_url?: string;
      lmstudio_endpoint?: string;
    } = {
      model_provider: selectedProvider,
      reasoning_model: modelForProvider,
      tool_execution_model: modelForProvider,
    };
    if (needsKey) {
      // Only send the key if the user typed a new one; otherwise the backend
      // keeps the already-configured credential.
      if (apiKey) payload.api_key = apiKey;
      payload.api_base_url = selectedPreset?.api_base_url;
    } else if (isLmstudio) {
      payload.lmstudio_endpoint = endpoint;
    }
    sendModelSelection(payload);
    setProviderMsg(`Provider "${selectedPreset?.label ?? selectedProvider}" applied`);
    // Reset button state after 2.5s so it can be clicked again if needed
    setTimeout(() => setProviderStatus("idle"), 2500);
  };

  // ── Inference behaviour handlers ──
  const pushInferenceMode = (next: { thinkingStyle: string; maxResponse: string; reasoningEffort: string; toolMode: string }) => {
    sendInferenceMode({
      agent_thinking_style: next.thinkingStyle,
      max_response_length: next.maxResponse,
      reasoning_effort: next.reasoningEffort,
      tool_mode: next.toolMode,
    });
  };

  const inputCls = "w-full bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-[11px] text-white/90 placeholder:text-white/25 outline-none transition-all focus:border-white/25 focus:bg-white/[0.08]";
  const monoCls = { fontFamily: "'JetBrains Mono', monospace" } as React.CSSProperties;
  const labelCls = "text-[11px] font-medium text-white/55 block mb-1";
  const sectionHeadCls = "text-[10px] uppercase tracking-wider text-white/40 mb-1.5 mt-1";

  return (
    <div className="col-span-full space-y-1 w-full">
      {/* ── Provider setup ── */}
      <div className="pb-2">
        <div className={sectionHeadCls}>Provider Setup</div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">
            Provider
          </span>
          <div className="w-[180px] flex-shrink-0">
            <CustomDropdown
              value={selectedProvider}
              options={providerSetupOptions}
              onChange={(v) => { setSelectedProvider(v); setProviderMsg(null); }}
              glowColor={glowColor}
              className="text-[10px] py-1 px-2 h-7 w-full"
              placeholder="Select provider…"
              forceOpenUp
            />
          </div>
        </div>

        {needsKey && (
          <div className="py-1.5 px-1">
            <div className="flex items-center justify-between mb-1">
              <label className={labelCls} style={{ marginBottom: 0 }}>API Key</label>
              {providerHasKey && (
                <span
                  className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-full"
                  style={{ background: `${glowColor}1a`, border: `1px solid ${glowColor}40`, color: glowColor }}
                >
                  ✓ Key set
                </span>
              )}
            </div>
            <input
              type="password"
              value={apiKey}
              placeholder={providerHasKey ? "Key already configured — enter to replace" : "sk-..."}
              onChange={(e) => setApiKey(e.target.value)}
              className={inputCls}
              style={monoCls}
            />
          </div>
        )}

        {isLmstudio && (
          <div className="py-1.5 px-1">
            <label className={labelCls}>Endpoint</label>
            <input
              type="text"
              value={endpoint}
              placeholder="http://localhost:1234"
              onChange={(e) => setEndpoint(e.target.value)}
              className={inputCls}
              style={monoCls}
            />
          </div>
        )}

        <div className="px-1 pt-1">
          <button
            onClick={handleApplyProvider}
            disabled={!selectedProvider || (keyRequired && !apiKey) || providerStatus === "applied"}
            className="w-full rounded-lg py-1.5 text-[10px] font-semibold uppercase tracking-wider transition-all disabled:opacity-40"
            style={{
              background: providerStatus === "applied" ? `${glowColor}30` : `${glowColor}1a`,
              border: `1px solid ${providerStatus === "applied" ? glowColor : `${glowColor}40`}`,
              color: providerStatus === "applied" ? glowColor : glowColor,
            }}
          >
            {providerStatus === "applied" ? `✓ Applied` : `Apply Provider`}
          </button>
          {providerMsg && <p className="text-[9px] text-white/50 mt-1">{providerMsg}</p>}
        </div>
      </div>

      {/* ── Model routing ── */}
      <div className="pt-2 pb-1 border-t border-white/5">
        <div className={sectionHeadCls}>Model Routing</div>

        {/* Brain Model — single dropdown with provider · model */}
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">
            Brain
          </span>
          <div className="w-[180px] flex-shrink-0">
            <CustomDropdown
              value={encodeBrainValue}
              options={modelOptions}
              onChange={handleBrainChange}
              glowColor={glowColor}
              className="text-[10px] py-1 px-2 h-7 w-full"
              placeholder="Select model…"
              forceOpenUp
            />
          </div>
        </div>

        {/* Tool Execution Model — hidden when useSameModel is on */}
        {!useSameModel && (
          <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
            <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">
              Tool
            </span>
            <div className="w-[180px] flex-shrink-0">
              <CustomDropdown
                value={encodeToolValue}
                options={modelOptions}
                onChange={handleToolChange}
                glowColor={glowColor}
                className="text-[10px] py-1 px-2 h-7 w-full"
                placeholder="Select model…"
                forceOpenUp
              />
            </div>
          </div>
        )}

        {/* Use Same Model toggle */}
        <div className="flex items-center justify-between py-1.5 px-1 gap-2">
          <span className="text-[11px] font-medium text-white/60 flex-1 min-w-0 leading-tight">Use Same Model</span>
          <button
            onClick={() => handleSameModelToggle(!useSameModel)}
            className="relative w-8 h-4 rounded-full transition-colors shrink-0"
            style={{ backgroundColor: useSameModel ? glowColor : "rgba(255,255,255,0.1)" }}
          >
            <motion.span
              className="absolute top-0.5 w-3 h-3 rounded-full bg-white shadow-sm"
              animate={{ left: useSameModel ? "18px" : "2px" }}
            />
          </button>
        </div>
      </div>

      {/* ── Inference behaviour ── */}
      <div className="pt-2 pb-1 border-t border-white/5">
        <div className={sectionHeadCls}>Inference Behaviour</div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Thinking Style</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={thinkingStyle} options={["concise", "balanced", "thorough"]} onChange={(v) => { setThinkingStyle(v); pushInferenceMode({ thinkingStyle: v, maxResponse, reasoningEffort, toolMode }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" forceOpenUp />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Max Response</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={maxResponse} options={["short", "medium", "long"]} onChange={(v) => { setMaxResponse(v); pushInferenceMode({ thinkingStyle, maxResponse: v, reasoningEffort, toolMode }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" forceOpenUp />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Reasoning Effort</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={reasoningEffort} options={["fast", "balanced", "accurate"]} onChange={(v) => { setReasoningEffort(v); pushInferenceMode({ thinkingStyle, maxResponse, reasoningEffort: v, toolMode }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" forceOpenUp />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Tool Mode</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={toolMode} options={["auto", "ask_first", "disabled"]} onChange={(v) => { setToolMode(v); pushInferenceMode({ thinkingStyle, maxResponse, reasoningEffort, toolMode: v }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" forceOpenUp />
          </div>
        </div>
      </div>

      {/* Active Routing — read-only display */}
      <div className="py-2 col-span-full border-t border-white/5">
        <div className="flex flex-col gap-1 px-3 py-2 rounded-xl text-[10px] uppercase tracking-wider"
          style={{ background: `${glowColor}10`, border: `1px solid ${glowColor}30` }}>
          <div className="flex items-center justify-between">
            <span style={{ color: "rgba(255,255,255,0.5)" }}>BRAIN (reasoning)</span>
            <span style={{ color: glowColor }}>
              {brainBinding
                ? `${getProviderLabel(brainBinding.instance_id)}${brainBinding.model_override ? ` · ${brainBinding.model_override}` : ""}`
                : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span style={{ color: "rgba(255,255,255,0.5)" }}>TOOL EXECUTION</span>
            <span style={{ color: glowColor }}>
              {toolBinding
                ? `${getProviderLabel(toolBinding.instance_id)}${toolBinding.model_override ? ` · ${toolBinding.model_override}` : ""}`
                : "—"}
            </span>
          </div>
        </div>
      </div>

      {/* Binding error */}
      {bindError && (
        <div className="px-3 py-1 col-span-full">
          <p className="text-[9px] text-red-400">{bindError}</p>
        </div>
      )}

      {/* Loading indicator */}
      {loading && (
        <div className="px-3 py-1 col-span-full">
          <span className="text-[9px] text-white/40">Loading providers...</span>
        </div>
      )}
    </div>
  );
});

export { ModelInferenceSection };
