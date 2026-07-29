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
import { Cpu } from "lucide-react"
import { CustomDropdown } from "@/components/ui/CustomDropdown"
import { useInferenceState } from "@/hooks/useInferenceState"

interface SwitcherEntry {
  id: string
  label: string
}

const ROLE_LABELS: Record<string, string> = {
  reasoning: "Brain",
  tool_execution: "Tool",
}

/** Long provider · model labels truncate in the trigger, following
 * ContextPill's own ACTION_CAP precedent — full name stays in `title`. */
const TRIGGER_LABEL_CAP = 18

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

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    const handle = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handle)
    return () => document.removeEventListener("mousedown", handle)
  }, [open])

  // REQ-2 AC2/AC3/AC4: API providers need `has_key`; local/inprocess/ollama
  // providers need `loaded`; chat purpose only (embedding/rerank excluded —
  // Phase 4 already filters the settings panel, this is the chat-row
  // equivalent, not a duplicate of that logic).
  const entries: SwitcherEntry[] = useMemo(() => {
    return providers
      .filter((p) => !p.purpose || p.purpose === "chat")
      .filter((p) => (isApiKind(p.kind) ? !!p.has_key : !!p.loaded))
      .map((p) => ({
        id: p.id,
        label: p.model ? `${p.label} · ${p.model}` : p.label,
      }))
  }, [providers])

  const options = useMemo(
    () => entries.map((e) => ({ label: e.label, value: e.id })),
    [entries]
  )

  const getLabel = useCallback(
    (instanceId?: string) => {
      if (!instanceId) return null
      const p = providers.find((prov) => prov.id === instanceId)
      if (!p) return instanceId
      return p.model ? `${p.label} · ${p.model}` : p.label
    },
    [providers]
  )

  const brainBinding = role_bindings.find((b) => b.role === "reasoning")
  const toolBinding = role_bindings.find((b) => b.role === "tool_execution")

  // REQ-2 AC6: what's active BEFORE the dropdown opens. If the bound
  // instance is no longer in `entries` (key removed / unloaded), it still
  // shows — as unavailable, never as a silently-working model (edge case).
  const activeLabel = getLabel(brainBinding?.instance_id)
  const brainAvailable = !!entries.find((e) => e.id === brainBinding?.instance_id)
  const truncatedActive =
    activeLabel && activeLabel.length > TRIGGER_LABEL_CAP
      ? activeLabel.slice(0, TRIGGER_LABEL_CAP) + "…"
      : activeLabel

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
          getLabel(toolBinding?.instance_id) || "—"
        }\nClick to switch model`
      : "No model bound — click to choose one"

  return (
    <div ref={containerRef} className="relative flex-shrink-0" data-testid="model-switcher">
      <button
        type="button"
        data-testid="model-switcher-trigger"
        onClick={() => setOpen((o) => !o)}
        disabled={loading}
        title={triggerTitle}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Switch model"
        className="flex items-center gap-1 h-[32px] px-2 rounded-full transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 max-w-[140px]"
        style={{
          color: brainAvailable || !brainBinding ? glowColor : "#f87171",
          background:
            "linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)",
          border: `1px solid ${fontColor}80`,
          boxShadow: open
            ? `0 0 12px ${glowColor}30, inset 0 1px 0 rgba(255,255,255,0.03)`
            : "0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
        }}
      >
        <Cpu size={14} className="shrink-0" />
        {/* REQ-3 edge case: the switcher collapses to an icon before the pill
            loses information — the text label is the part that goes at a
            narrow width, never the pill. */}
        {truncatedActive && (
          <span className="hidden sm:inline text-[9px] font-mono uppercase tracking-wide truncate">
            {truncatedActive}
          </span>
        )}
      </button>

      {open && (
        <div
          data-testid="model-switcher-panel"
          className="absolute z-50 bottom-[calc(100%+6px)] right-0 w-[220px] max-h-[70vh] overflow-y-auto rounded-xl p-2.5"
          style={{
            background: "rgba(10, 10, 14, 0.96)",
            border: `1px solid ${glowColor}30`,
            boxShadow: `0 8px 32px rgba(0,0,0,0.6), 0 0 20px ${glowColor}10`,
            backdropFilter: "blur(12px)",
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
                      className="text-[10px] py-1 px-2 h-7 w-full"
                      placeholder="Select…"
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
      )}
    </div>
  )
}
