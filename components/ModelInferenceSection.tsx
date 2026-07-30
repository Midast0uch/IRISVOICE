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
}: {
  providers: { id: string; label: string; kind: string; model: string; purpose?: string; has_key?: boolean }[];
  role_bindings: { role: string; instance_id: string; model_override?: string }[];
  loading: boolean;
  sendRoleBinding: (role: string, instanceId: string, modelOverride?: string) => void;
  glowColor: string;
  provider_presets: { id: string; label: string; kind: string; needs_key: boolean; api_base_url: string }[];
  sendModelSelection: (payload: { model_provider: string; api_key?: string; api_base_url?: string; lmstudio_endpoint?: string }) => void;
  sendInferenceMode: (values: Record<string, string>) => void;
  inferenceValues?: Record<string, any>;
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

  // Merge provider + its current model into each option label so the Brain/Tool
  // selectors show "Provider · model" rather than just the provider name.
  // REQ-6 AC3: exclude non-chat providers (embedding, rerank, etc.) from
  // the Brain and Tool selectors so they cannot be bound to reasoning or
  // tool_execution. Backward-compat: undefined/empty purpose treats as chat.
  const chatProviderOptions = providers.filter(
    (p) => !p.purpose || p.purpose === "chat"
  );
  const providerOptions = chatProviderOptions.map((p) => ({
    label: p.model ? `${p.label} · ${p.model}` : p.label,
    value: p.id,
  }));

  const handleBrainChange = (value: string) => {
    setBindError(null);
    sendRoleBinding("reasoning", value);
    if (useSameModel) {
      sendRoleBinding("tool_execution", value);
    }
  };

  const handleToolChange = (value: string) => {
    setBindError(null);
    sendRoleBinding("tool_execution", value);
  };

  const handleSameModelToggle = (val: boolean) => {
    setUseSameModel(val);
    if (val && brainBinding?.instance_id) {
      sendRoleBinding("tool_execution", brainBinding.instance_id);
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
    const matchedProvider = providers.find((p) => p.id === selectedProvider);
    const payload: {
      model_provider: string;
      reasoning_model?: string;
      tool_execution_model?: string;
      api_key?: string;
      api_base_url?: string;
      lmstudio_endpoint?: string;
    } = {
      model_provider: selectedProvider,
      reasoning_model: matchedProvider?.model || "",
      tool_execution_model: matchedProvider?.model || "",
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
              options={provider_presets.map((p) => ({ label: p.label, value: p.id }))}
              onChange={(v) => { setSelectedProvider(v); setProviderMsg(null); }}
              glowColor={glowColor}
              className="text-[10px] py-1 px-2 h-7 w-full"
              placeholder="Select provider…"
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
        {/* Brain Model dropdown */}
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">
            Brain Model
          </span>
          <div className="w-[180px] flex-shrink-0">
            <CustomDropdown
              value={brainBinding?.instance_id || ""}
              options={providerOptions}
              onChange={handleBrainChange}
              glowColor={glowColor}
              className="text-[10px] py-1 px-2 h-7 w-full"
              placeholder="Select…"
            />
          </div>
        </div>

        {/* Tool Execution Model — hidden when useSameModel is on */}
        {!useSameModel && (
          <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
            <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">
              Tool Execution Model
            </span>
            <div className="w-[180px] flex-shrink-0">
              <CustomDropdown
                value={toolBinding?.instance_id || ""}
                options={providerOptions}
                onChange={handleToolChange}
                glowColor={glowColor}
                className="text-[10px] py-1 px-2 h-7 w-full"
                placeholder="Select…"
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
            <CustomDropdown value={thinkingStyle} options={["concise", "balanced", "thorough"]} onChange={(v) => { setThinkingStyle(v); pushInferenceMode({ thinkingStyle: v, maxResponse, reasoningEffort, toolMode }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Max Response</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={maxResponse} options={["short", "medium", "long"]} onChange={(v) => { setMaxResponse(v); pushInferenceMode({ thinkingStyle, maxResponse: v, reasoningEffort, toolMode }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Reasoning Effort</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={reasoningEffort} options={["fast", "balanced", "accurate"]} onChange={(v) => { setReasoningEffort(v); pushInferenceMode({ thinkingStyle, maxResponse, reasoningEffort: v, toolMode }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
          <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">Tool Mode</span>
          <div className="w-[140px] flex-shrink-0">
            <CustomDropdown value={toolMode} options={["auto", "ask_first", "disabled"]} onChange={(v) => { setToolMode(v); pushInferenceMode({ thinkingStyle, maxResponse, reasoningEffort, toolMode: v }); }} glowColor={glowColor} className="text-[10px] py-1 px-2 h-7 w-full" />
          </div>
        </div>
      </div>

      {/* Active Routing — read-only display */}
      <div className="py-2 col-span-full border-t border-white/5">
        <div className="flex flex-col gap-1 px-3 py-2 rounded-xl text-[10px] uppercase tracking-wider"
          style={{ background: `${glowColor}10`, border: `1px solid ${glowColor}30` }}>
          <div className="flex items-center justify-between">
            <span style={{ color: "rgba(255,255,255,0.5)" }}>BRAIN (reasoning)</span>
            <span style={{ color: glowColor }}>{brainBinding ? getProviderLabel(brainBinding.instance_id) : "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span style={{ color: "rgba(255,255,255,0.5)" }}>TOOL EXECUTION</span>
            <span style={{ color: glowColor }}>{toolBinding ? getProviderLabel(toolBinding.instance_id) : "—"}</span>
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
