"use client";

import { useState, useEffect } from "react";
import { Brain, CheckCircle, AlertTriangle, Loader2, Wifi, WifiOff, Cpu, Globe, Key, Mic, MicOff } from "lucide-react";
import { SectionHeader, DataRow, StatusBadge } from "@/components/launcher/DashboardPrimitives";
import { LiquidIcon } from "@/components/launcher/LiquidIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageTransition } from "@/components/launcher/PageTransition";
import { motion } from "framer-motion";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type Provider = "iris_local" | "api" | "lmstudio" | "local";

interface ProviderOption {
  id: Provider;
  label: string;
  description: string;
  icon: React.ReactNode;
  color: "primary" | "accent" | "success" | "warning";
}

const PROVIDERS: ProviderOption[] = [
  {
    id: "iris_local",
    label: "IRIS Local",
    description: "Built-in ik_llama.cpp inference engine — GPU accelerated, no API key needed",
    icon: <Cpu className="h-5 w-5" />,
    color: "success",
  },
  {
    id: "api",
    label: "Remote API",
    description: "Any OpenAI-compatible endpoint — OpenAI, Groq, Together, OpenRouter, etc.",
    icon: <Globe className="h-5 w-5" />,
    color: "accent",
  },
  {
    id: "lmstudio",
    label: "LM Studio",
    description: "Local LM Studio server — run models via the LM Studio desktop app",
    icon: <Brain className="h-5 w-5" />,
    color: "primary",
  },
  {
    id: "local",
    label: "Ollama",
    description: "Local Ollama server — pull and run models via Ollama CLI",
    icon: <Cpu className="h-5 w-5" />,
    color: "warning",
  },
];

const DEFAULT_URLS: Record<Provider, string> = {
  iris_local: "http://localhost:8082/v1",
  api: "https://api.openai.com/v1",
  lmstudio: "http://localhost:1234/v1",
  local: "http://localhost:11434",
};

type SaveState = "idle" | "saving" | "saved" | "error";
type TestState = "idle" | "testing" | "ok" | "fail";

const SettingsPage = () => {
  const [provider, setProvider] = useState<Provider>("iris_local");
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState(DEFAULT_URLS["iris_local"]);
  const [apiKeySet, setApiKeySet] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [testState, setTestState] = useState<TestState>("idle");
  const [testMsg, setTestMsg] = useState("");
  const [loading, setLoading] = useState(true);
  const [audioRunning, setAudioRunning] = useState(false);
  const [audioToggling, setAudioToggling] = useState(false);

  // Load current config from backend
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${BACKEND}/api/model-config`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        const p = (data.model_provider as Provider) || "iris_local";
        setProvider(p);
        setApiKeySet(data.api_key_set ?? false);
        setApiUrl(data.api_base_url || DEFAULT_URLS[p]);
      } catch {
        // backend offline — leave defaults
      }
      // Load audio status separately (non-fatal)
      try {
        const ar = await fetch(`${BACKEND}/api/audio/status`);
        if (!cancelled && ar.ok) {
          const ad = await ar.json();
          setAudioRunning(ad.running ?? false);
        }
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleProviderChange = (p: Provider) => {
    setProvider(p);
    setApiUrl(DEFAULT_URLS[p]);
    setTestState("idle");
    setSaveState("idle");
  };

  const handleApply = async () => {
    setSaveState("saving");
    try {
      const body: Record<string, string> = { model_provider: provider, api_base_url: apiUrl };
      if (apiKey) body.api_key = apiKey;
      const res = await fetch(`${BACKEND}/api/model-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setSaveState("saved");
        if (apiKey) { setApiKeySet(true); setApiKey(""); }
        setTimeout(() => setSaveState("idle"), 2500);
      } else {
        setSaveState("error");
      }
    } catch {
      setSaveState("error");
    }
  };

  const handleAudioToggle = async () => {
    setAudioToggling(true);
    try {
      const endpoint = audioRunning ? "/api/audio/stop" : "/api/audio/start";
      const res = await fetch(`${BACKEND}${endpoint}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (data.ok !== false) setAudioRunning(!audioRunning);
    } catch { /* ignore */ }
    setAudioToggling(false);
  };

  const handleTest = async () => {
    setTestState("testing");
    setTestMsg("");
    try {
      const body: Record<string, string> = { api_url: apiUrl };
      if (apiKey) body.api_key = apiKey;
      const res = await fetch(`${BACKEND}/api/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        setTestState("ok");
        setTestMsg(data.message || "Connection successful");
      } else {
        setTestState("fail");
        setTestMsg(data.error || data.message || "Connection failed");
      }
    } catch (err: any) {
      setTestState("fail");
      setTestMsg(err?.message || "Could not reach backend");
    }
  };

  const selectedProviderInfo = PROVIDERS.find((p) => p.id === provider)!;
  const needsUrl = provider === "api" || provider === "lmstudio" || provider === "local";
  const needsKey = provider === "api";

  return (
    <PageTransition variant="blur">
      <div className="space-y-10 max-w-2xl">
        <SectionHeader
          title="Inference Settings"
          description="Choose how IRIS runs language model inference"
          action={
            loading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : (
              <StatusBadge
                status={provider === "iris_local" ? "online" : "warning"}
                label={selectedProviderInfo.label.toUpperCase()}
              />
            )
          }
        />

        {/* Provider selector */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {PROVIDERS.map((opt) => (
            <motion.button
              key={opt.id}
              onClick={() => handleProviderChange(opt.id)}
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.98 }}
              className={[
                "glass-card rounded-2xl p-5 text-left transition-all focus:outline-none focus:ring-2 focus:ring-primary/30",
                provider === opt.id
                  ? "ring-2 ring-primary/60 bg-primary/5"
                  : "opacity-70 hover:opacity-100",
              ].join(" ")}
              aria-pressed={provider === opt.id}
            >
              <div className="flex items-start gap-3">
                <LiquidIcon color={opt.color} size="sm">
                  {opt.icon}
                </LiquidIcon>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-semibold text-foreground">{opt.label}</span>
                    {provider === opt.id && (
                      <CheckCircle className="h-3.5 w-3.5 text-primary shrink-0" />
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">{opt.description}</p>
                </div>
              </div>
            </motion.button>
          ))}
        </div>

        {/* Credentials */}
        {(needsUrl || needsKey) && (
          <motion.div
            key={provider}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="glass-card rounded-2xl p-6 space-y-5"
          >
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <LiquidIcon color={selectedProviderInfo.color} size="sm">
                {selectedProviderInfo.icon}
              </LiquidIcon>
              {selectedProviderInfo.label} Configuration
            </h3>

            {needsUrl && (
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-muted-foreground uppercase tracking-widest">
                  Endpoint URL
                </label>
                <Input
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  placeholder={DEFAULT_URLS[provider]}
                  className="font-mono glass-subtle border-0 text-foreground placeholder:text-muted-foreground"
                  autoComplete="off"
                />
              </div>
            )}

            {needsKey && (
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                  <Key className="h-3 w-3" />
                  API Key
                  {apiKeySet && !apiKey && (
                    <span className="text-success ml-1">(saved — enter new key to change)</span>
                  )}
                </label>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={apiKeySet ? "••••••••••••••••" : "sk-..."}
                  className="font-mono glass-subtle border-0 text-foreground placeholder:text-muted-foreground"
                  autoComplete="new-password"
                />
              </div>
            )}

            {/* Test connection row */}
            <div className="flex items-center gap-3 pt-1">
              <Button
                variant="outline"
                size="sm"
                onClick={handleTest}
                disabled={testState === "testing"}
                className="font-mono text-xs"
              >
                {testState === "testing" ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : testState === "ok" ? (
                  <Wifi className="h-3.5 w-3.5 mr-1.5 text-success" />
                ) : testState === "fail" ? (
                  <WifiOff className="h-3.5 w-3.5 mr-1.5 text-destructive" />
                ) : (
                  <Wifi className="h-3.5 w-3.5 mr-1.5" />
                )}
                {testState === "testing" ? "Testing…" : "Test Connection"}
              </Button>

              {testMsg && (
                <span
                  className={[
                    "text-xs font-mono truncate",
                    testState === "ok" ? "text-success" : "text-destructive",
                  ].join(" ")}
                >
                  {testMsg}
                </span>
              )}
            </div>
          </motion.div>
        )}

        {/* IRIS Local info card */}
        {provider === "iris_local" && (
          <motion.div
            key="iris_local_info"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="glass-card rounded-2xl p-6 space-y-3"
          >
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <LiquidIcon color="success" size="sm"><Cpu className="h-5 w-5" /></LiquidIcon>
              IRIS Local — No Configuration Needed
            </h3>
            <div className="space-y-1">
              <DataRow label="Inference Server" value="ik_llama.cpp (port 8082)" />
              <DataRow label="API Key" value="Not required" />
              <DataRow label="GPU Acceleration" value="CUDA / Metal / Vulkan via llama.cpp" />
              <DataRow label="Models" value="Load from the Models screen in the widget" />
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              IRIS Local uses the built-in llama.cpp sidecar. Load a GGUF model from the widget's
              Models tab to activate inference.
            </p>
          </motion.div>
        )}

        {/* Voice / wake word toggle */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
          className="glass-card rounded-2xl p-6"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <LiquidIcon color={audioRunning ? "success" : "warning"} size="sm">
                {audioRunning ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
              </LiquidIcon>
              <div>
                <p className="text-sm font-semibold text-foreground">Voice & Wake Word</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {audioRunning
                    ? "Porcupine listening — microphone active, PortAudio running"
                    : "Audio pipeline stopped — zero mic CPU overhead"}
                </p>
              </div>
            </div>
            <Button
              variant={audioRunning ? "destructive" : "outline"}
              size="sm"
              onClick={handleAudioToggle}
              disabled={audioToggling}
              className="font-mono text-xs min-w-[100px]"
            >
              {audioToggling ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : audioRunning ? (
                <><MicOff className="h-3.5 w-3.5 mr-1.5" />Stop Audio</>
              ) : (
                <><Mic className="h-3.5 w-3.5 mr-1.5" />Start Audio</>
              )}
            </Button>
          </div>
          {!audioRunning && (
            <p className="text-xs text-muted-foreground mt-3 font-mono">
              On WSL, audio is disabled by default to prevent CPU spikes from the PortAudio
              callback loop. Enable only when you need wake word or microphone input.
            </p>
          )}
        </motion.div>

        {/* Apply button */}
        <div className="flex items-center gap-3">
          <Button
            onClick={handleApply}
            disabled={saveState === "saving"}
            className="font-mono bg-primary text-primary-foreground hover:bg-primary/90 min-w-[120px]"
          >
            {saveState === "saving" ? (
              <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Applying…</>
            ) : saveState === "saved" ? (
              <><CheckCircle className="h-4 w-4 mr-2 text-success" />Applied</>
            ) : saveState === "error" ? (
              <><AlertTriangle className="h-4 w-4 mr-2 text-destructive" />Failed</>
            ) : (
              "Apply Settings"
            )}
          </Button>

          {saveState === "saved" && (
            <motion.span
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              className="text-xs font-mono text-success"
            >
              Settings applied — launch the widget to use them
            </motion.span>
          )}

          {saveState === "error" && (
            <span className="text-xs font-mono text-destructive">
              Backend offline — start the backend first
            </span>
          )}
        </div>
      </div>
    </PageTransition>
  );
};

export default SettingsPage;
