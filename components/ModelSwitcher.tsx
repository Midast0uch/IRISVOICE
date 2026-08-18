"use client"

/**
 * ModelSwitcher — Phase 5 (specs/phase-5-switcher).
 *
 * Sibling of ContextPill in the chat input row (D-2): reads the SAME
 * useInferenceState hook the settings panel (ModelInferenceSection) uses and
 * writes through its existing sendRoleBinding — no new backend surface
 * (D-3), so the switcher and settings panel cannot disagree (REQ-4 AC4).
 *
 * ContextPillProps is untouched (CT-S1) — this is a wholly separate
 * component, never a new prop on the pill.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { CustomDropdown } from "@/components/ui/CustomDropdown"
import { IconRobot } from "@tabler/icons-react"
import { useInferenceState } from "@/hooks/useInferenceState"

interface SwitcherEntry {
  id: string
  label: string
  /** True for a local/in-process provider whose weights are loaded right now.
   *  Used to float it above the API catalog entries. */
  resident?: boolean
}

const ROLE_LABELS: Record<string, string> = {
  reasoning: "Brain",
  tool_execution: "Tool",
}

/** Long provider · model labels truncate in the trigger, following
 * ContextPill's own ACTION_CAP precedent — full name stays in `title`. */
const TRIGGER_LABEL_CAP = 18

/** Abbreviate provider/model names for the compact trigger so the visible
 * switcher stays legible (e.g. "cerebras · gemma-4-31b" → "cer · gem-4-31b").
 * The full label is always preserved in `title` and in the dropdown list. */
const PROVIDER_ABBR: Record<string, string> = {
  cerebras: "cer",
  cohere: "coh",
  openai: "oai",
  ollama: "oll",
  lmstudio: "lms",
  venice: "ven",
  local: "loc",
  vps: "vps",
  api: "api",
}

function abbreviateLabel(label: string | null): string | null {
  if (!label) return label
  const idx = label.indexOf(" · ")
  const prov = idx >= 0 ? label.slice(0, idx) : label
  const model = idx >= 0 ? label.slice(idx + 3) : ""
  const abbrProv = PROVIDER_ABBR[prov.toLowerCase()] || (prov ? prov.slice(0, 3) : prov)
  if (!model) return abbrProv
  const abbrModel = model
    .replace(/^gemma-(\d+)-(\d+b)$/i, "gem-$1-$2")
    .replace(/^command-a-(\d+)-(\d+)$/i, "cmd-a")
  return `${abbrProv} · ${abbrModel}`
}

function isApiKind(kind: string | undefined): boolean {
  return (kind || "").toLowerCase() === "api"
}

export default function ModelSwitcher({
  glowColor = "#00d4ff",
  fontColor = "#ffffff",
}: {
  glowColor?: string
  fontColor?: string
}) {
  const {
    providers,
    role_bindings,
    loading,
    sendRoleBinding,
  } = useInferenceState()

  const [open, setOpen] = useState(false)
  const [bindError, setBindError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [triggerRect, setTriggerRect] = useState<DOMRect | null>(null)

  // REQ-4 AC3: surface a bind failure but never show the failed selection as
  // active — this listener only ever sets a transient message. The "active"
  // label below is derived exclusively from role_bindings (which the backend
  // only broadcasts on a SUCCESSFUL bind), so a failure can never render as
  // if it took effect.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { error?: string; role?: string; instance_id?: string }
        | undefined
      if (detail?.error) setBindError(detail.error)
    }
    window.addEventListener("iris:role_binding_error", handler as EventListener)
    return () =>
      window.removeEventListener("iris:role_binding_error", handler as EventListener)
  }, [])

  // Outside-click is handled by the transparent backdrop rendered alongside
  // the portaled panel (mirrors ConversationChips), so the panel is not clipped
  // by the chat view's overflow:hidden + transform ancestor.

  // REQ-2 AC2/AC3/AC4: API providers need `has_key`; local/inprocess
  // providers need `loaded`; ollama is ALWAYS available — the ollama server
  // loads models on demand, so `loaded` (which tracks in-process llama-cpp
  // loads) is never set for it and must not gate it (2026-08-16: ollama
  // showed "(unavailable)" while routing worked fine). Chat purpose only
  // (embedding/rerank excluded — Phase 4 already filters the settings panel,
  // this is the chat-row equivalent, not a duplicate of that logic).
  const entries: SwitcherEntry[] = useMemo(() => {
    return providers
      .filter((p) => !p.purpose || p.purpose === "chat")
      .filter((p) => {
        if (isApiKind(p.kind)) return !!p.has_key
        if ((p.kind || "").toLowerCase() === "ollama") return true
        return !!p.loaded
      })
      .map((p) => ({
        id: p.id,
        label: p.model ? `${p.label} · ${p.model}` : p.label,
        // A locally-loaded model is resident in VRAM right now and is almost
        // always what the user just came here to pick. Everything else is a
        // catalog entry that is merely reachable.
        resident: !isApiKind(p.kind) && (p.kind || "").toLowerCase() !== "ollama" && !!p.loaded,
      }))
      // Loaded local models first, preserving registry order within each group.
      // Without this the local provider is appended after every API preset —
      // measured live: the freshly loaded local model sat below ~40 Cohere /
      // OpenAI / Cerebras / OpenCodeGo entries and had to be scrolled to.
      .sort((a, b) => Number(b.resident) - Number(a.resident))
  }, [providers])

  const options = useMemo(
    () => entries.map((e) => ({ label: e.label, value: e.id })),
    [entries]
  )

  const getLabel = useCallback(
    (binding?: { instance_id?: string; model_override?: string }) => {
      const instanceId = binding?.instance_id
      if (!instanceId) return null
      const p = providers.find((prov) => prov.id === instanceId)
      if (!p) return instanceId
      // The ACTIVE model is the role binding's model_override (what the user
      // picked in the dashboard Brain/Tool dropdowns), NOT the provider's
      // default `model`. Showing the default here desyncs the switcher from
      // the settings panel and from what routing actually uses (e.g. ollama
      // defaulted to gpt-oss:120b-cloud while the user chose nemotron).
      const model = binding?.model_override || p.model
      return model ? `${p.label} · ${model}` : p.label
    },
    [providers]
  )

  const brainBinding = role_bindings.find((b) => b.role === "reasoning")
  const toolBinding = role_bindings.find((b) => b.role === "tool_execution")

  // REQ-2 AC6: what's active BEFORE the dropdown opens. If the bound
  // instance is no longer in `entries` (key removed / unloaded), it still
  // shows — as unavailable, never as a silently-working model (edge case).
  const activeLabel = getLabel(brainBinding)
  const brainAvailable = !!entries.find((e) => e.id === brainBinding?.instance_id)
  const abbreviatedActive = abbreviateLabel(activeLabel)
  const truncatedActive =
    abbreviatedActive && abbreviatedActive.length > TRIGGER_LABEL_CAP
      ? abbreviatedActive.slice(0, TRIGGER_LABEL_CAP) + "…"
      : abbreviatedActive

  const handleChange = useCallback(
    (role: string, value: string) => {
      setBindError(null)
      sendRoleBinding(role, value)
    },
    [sendRoleBinding]
  )

  const triggerTitle = loading
    ? "Loading models…"
    : activeLabel
      ? `Brain: ${activeLabel}${brainAvailable ? "" : " (unavailable)"}\nTool: ${
          getLabel(toolBinding) || "—"
        }\nClick to switch model`
      : "No model bound — click to choose one"

  return (
    <div ref={containerRef} className="relative flex-shrink-0 -mr-2" data-testid="model-switcher">
      <button
        type="button"
        data-testid="model-switcher-trigger"
        disabled={loading}
        title={triggerTitle}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Switch model"
        ref={triggerRef}
        onClick={() => {
          // Single handler (TS17001 fix): records the trigger rect for the
          // popover anchor AND toggles open — the duplicate onClick was a
          // merge artifact; the first one was removed.
          const tr = triggerRef.current?.getBoundingClientRect()
          setTriggerRect(tr || null)
          setOpen((o) => !o)
        }}
        className="flex items-center gap-1 h-[32px] px-2 rounded-full transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 max-w-[140px]"
        style={{
          color: brainAvailable || !brainBinding ? glowColor : "#f87171",
          background:
            "linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)",
          border: `1px solid ${fontColor}80`,
          boxShadow: `0 0 12px ${glowColor}30, inset 0 1px 0 rgba(255,255,255,0.03)`,
        }}
      >
        <IconRobot size={14} className="shrink-0" />
        {/* REQ-3 edge case: the switcher collapses to an icon before the pill
            loses information — the text label is the part that goes at a
            narrow width, never the pill. */}
        {truncatedActive && (
          <span className="hidden sm:inline text-[9px] font-mono uppercase tracking-wide truncate">
            {truncatedActive}
          </span>
        )}
      </button>

      {open && triggerRect && createPortal(
        <>
          {/* transparent backdrop catches outside clicks and closes the panel */}
          <div
            onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 9000 }}
          />
          <div
            data-testid="model-switcher-panel"
            className="overflow-y-auto rounded-xl"
            style={{
              position: "fixed",
              bottom: window.innerHeight - triggerRect.top + 6,
              right: window.innerWidth - triggerRect.right,
              zIndex: 9050,
              width: 147,
              maxHeight: "47vh",
              padding: 12,
              background: "rgba(14, 14, 24, 0.98)",
              border: `1px solid ${glowColor}30`,
              boxShadow: `0 8px 32px rgba(0,0,0,0.6), 0 0 20px ${glowColor}10`,
              backdropFilter: "blur(12px)",
              WebkitBackdropFilter: "blur(12px)",
            }}
          >
          {loading ? (
            <div data-testid="model-switcher-loading" className="text-[10px] text-white/40 px-1 py-1.5">
              Loading models…
            </div>
          ) : entries.length === 0 ? (
            // REQ-2 AC9: actionable, distinct from the loading state.
            <div data-testid="model-switcher-empty" className="text-[10px] text-white/50 px-1 py-1.5 leading-relaxed">
              No usable model yet. Add an API key or load a local model in
              Settings → Model & Inference.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {(["reasoning", "tool_execution"] as const).map((role) => {
                const binding = role === "reasoning" ? brainBinding : toolBinding
                return (
                  <div key={role} data-testid={`model-switcher-${role}`}>
                    <label className="text-[9px] uppercase tracking-wider text-white/40 block mb-1">
                      {ROLE_LABELS[role]}
                    </label>
                    <CustomDropdown
                      value={binding?.instance_id || ""}
                      options={options}
                      onChange={(v) => handleChange(role, v)}
                      glowColor={glowColor}
                      className="text-[9px] py-1 px-2 h-6 w-full"
                      placeholder="Select…"
                      forceOpenUp
                    />
                  </div>
                )
              })}
            </div>
          )}
          {bindError && (
            <p data-testid="model-switcher-error" className="text-[9px] text-red-400 mt-2 px-1">
              {bindError}
            </p>
          )}
        </div>
        </>,
        document.body
      )}
    </div>
  )
}
