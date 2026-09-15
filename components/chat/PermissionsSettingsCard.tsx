"use client"

import React, { useState, useEffect, useCallback } from "react"
import { RefreshCw, Loader } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"

export type PermissionMode = "personal" | "developer"

export interface PermissionsConfig {
  mode: PermissionMode | null
  effective_mode: PermissionMode
  approved_tools: string[]
  available_tools: string[]
  auto_approve: boolean
}

interface PermissionsSettingsCardProps {
  /** Optional override for the config endpoint (used by tests). */
  configUrl?: string
}

/**
 * PermissionsSettingsCard — the standing APPROVED-TOOLS list for the Tools
 * card (REQ-19 AC3/AC5).
 *
 * Session-331: this renders ONLY the approved-tools checklist. The permission
 * MODE dropdown and the AUTO-APPROVE toggle are ordinary dashboard fields
 * (`permission_mode` / `auto_approve` in data/cards.ts), so they use the same
 * native row style as every other settings card. This component previously
 * wrapped everything in the chat-stream `CardChassis`, which made the Tools
 * card look nothing like the rest of the dashboard; that wrapper is gone.
 *
 * Each row is a dashboard-native toggle row (matching dark-glass-dashboard's
 * toggle style) so the card is visually consistent.
 */
export function PermissionsSettingsCard({
  configUrl = "/api/config",
}: PermissionsSettingsCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"

  const [config, setConfig] = useState<PermissionsConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toolsBusy, setToolsBusy] = useState(false)

  const loadConfig = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(configUrl)
      if (!res.ok) throw new Error(`GET ${configUrl} returned ${res.status}`)
      const data = (await res.json()) as PermissionsConfig
      setConfig(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load permissions")
    } finally {
      setLoading(false)
    }
  }, [configUrl])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  const toggleTool = useCallback(
    async (tool: string) => {
      if (toolsBusy || !config) return
      const isApproved = config.approved_tools.includes(tool)
      const next = isApproved
        ? config.approved_tools.filter((t) => t !== tool)
        : [...config.approved_tools, tool]
      setToolsBusy(true)
      try {
        const res = await fetch("/api/approved-tools", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved_tools: next }),
        })
        if (!res.ok) throw new Error(`POST /api/approved-tools returned ${res.status}`)
        await loadConfig()
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update approved tools")
      } finally {
        setToolsBusy(false)
      }
    },
    [toolsBusy, config, loadConfig],
  )

  const approvedSet = new Set(config?.approved_tools ?? [])
  const availableTools = config?.available_tools ?? []

  if (loading && !config) {
    return (
      <div className="flex items-center gap-2 py-1.5 px-1 text-[11px]" style={{ color: "rgba(255,255,255,0.5)" }}>
        <Loader size={12} className="animate-spin" />
        Loading tools…
      </div>
    )
  }

  if (error && !config) {
    return (
      <div className="flex items-center gap-2 py-1.5 px-1">
        <span className="text-[11px]" style={{ color: "rgba(239,68,68,0.9)" }}>{error}</span>
        <button
          type="button"
          onClick={loadConfig}
          className="flex items-center gap-1 text-[10px] font-semibold"
          style={{ color: glowColor }}
        >
          <RefreshCw size={11} /> Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide px-1 pt-1 pb-0.5" style={{ color: "rgba(255,255,255,0.35)" }}>
        Pre-approved tools
      </span>
      {availableTools.length === 0 ? (
        <span className="text-[11px] px-1 py-1" style={{ color: "rgba(255,255,255,0.4)" }}>
          No tools available to pre-approve.
        </span>
      ) : (
        availableTools.map((tool) => {
          const on = approvedSet.has(tool)
          return (
            <div key={tool} className="flex items-center justify-between py-1.5 px-1 gap-2">
              <span className="text-[11px] font-mono text-white/60 flex-1 min-w-0 leading-tight truncate">
                {tool}
              </span>
              <button
                type="button"
                disabled={toolsBusy}
                onClick={() => toggleTool(tool)}
                aria-pressed={on}
                aria-label={`Approve ${tool}`}
                className="relative w-8 h-4 rounded-full transition-colors disabled:opacity-50 shrink-0"
                style={{ backgroundColor: on ? glowColor : "rgba(255,255,255,0.1)" }}
              >
                <span
                  className="absolute top-0.5 w-3 h-3 rounded-full bg-white shadow-sm transition-all"
                  style={{ left: on ? "18px" : "2px" }}
                />
              </button>
            </div>
          )
        })
      )}
      {error && (
        <span className="text-[10px] px-1" style={{ color: "rgba(239,68,68,0.9)" }}>
          {error}
        </span>
      )}
    </div>
  )
}

export default PermissionsSettingsCard
